"""Airflow 월 배치의 단계별 작업 (Phase 4-2).

왜 DAG 파일에 코드를 다 쓰지 않나요?
    Airflow DAG 파일은 '무엇을 어떤 순서로'만 적고, 실제 일은 여기 있는 평범한 파이썬 함수가 합니다.
    그래야 Airflow 없이도 함수를 테스트할 수 있고, 같은 함수를 명령줄 · 테스트 · Airflow에서 함께 씁니다.
    (DAG: airflow/dags/future_stress_monthly.py, 기록: docs/notes/18_airflow.md)

배치 월이란?
    한 번에 도착한 원본 묶음의 이름입니다. BC카드 파일 이름 bc_card_<시작월>_<끝월>.csv의 끝월로 정합니다.
    DAG는 매달 1일(한국 시간)에 '지난달' 배치를 처리합니다 (7월 1일 실행 → 202606).
    공모전 데이터는 2026.01 ~ 06이 한 번에 온 묶음 하나라서 배치 월은 202606 하나뿐입니다.
    그래서 2 ~ 6월 1일 실행(배치 202601 ~ 202605)은 '새 원본 없음'으로 건너뛰고, 7월 1일 실행만 실제로 처리합니다.
    다음 달 원본(예: bc_card_202607_202607.csv)이 오면 8월 1일 실행이 그 달을 처리합니다. 앞의 파일과 합쳐
    분석 기간이 최근 6개월(2 ~ 7월)로 옮겨 갑니다 (card_spending.load_card_files · analysis_months, 2026-10-22부터).

모든 단계는 다시 돌려도 결과가 같습니다 (지문이 같으면 '변경 없음', 05 멱등성).
각 함수는 Airflow 화면에서 보기 좋은 작은 dict를 돌려줍니다 (XCom에 저장되므로 큰 표를 돌려주지 않음).
"""

import subprocess
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .medallion import DataQualityError, build_bronze, check_row, latest_card_batch
from .object_store import ObjectStore, download_bronze, upload_bronze
from .pipeline import build_layers_and_export
from .warehouse import Warehouse, compare_gold, compare_silver, load_raw


def batch_month_of(date):
    """날짜 → 그 날짜가 속한 달. 예: 2026-06-01 → 202606"""
    return date.year * 100 + date.month


def batch_month_for_run(run_time):
    """Airflow 실행 시각 → 이 실행이 처리할 배치 월 = 한국 시간으로 '지난달'.

    매달 1일 0시(한국 시간)에 돌며 지난달 원본을 처리합니다. 예: 2026-07-01 실행 → 202606
    Airflow는 실행 시각을 UTC로 넘겨줘서(2026-07-01 00:00 KST = 2026-06-30 15:00 UTC) 그대로 달을 읽으면
    한 달이 어긋납니다. 그래서 먼저 한국 시간으로 바꾼 뒤 지난달을 셉니다.
    """
    if run_time.tzinfo is not None:
        run_time = run_time.astimezone(ZoneInfo(config.TIMEZONE))
    last_day_of_previous_month = run_time.replace(day=1) - timedelta(days=1)
    return batch_month_of(last_day_of_previous_month)


def raw_batch_month(raw_dir=None):
    """원본 폴더에 있는 BC카드 파일의 배치 월(파일 이름의 끝월). 파일이 없으면 None.

    파일이 여러 개면 가장 최근 끝월을 돌려줍니다.
    """
    return latest_card_batch(raw_dir or config.RAW_DATA_DIR)


def layer_paths():
    """Airflow가 쓰는 폴더. 이 PC의 파이프라인과 같은 data/ 폴더를 씁니다."""
    return {
        "raw": config.RAW_DATA_DIR,
        "bronze": config.BRONZE_DIR,
        "bronze_cache": config.DATA_DIR / "bronze_cache",
        "silver": config.SILVER_DIR,
        "gold": config.GOLD_DIR,
        "output": config.OUTPUT_DIR,
    }


# ===========================================================================
# 단계별 작업 (DAG의 task 하나 = 함수 하나)
# ===========================================================================

def has_new_batch(batch_month, raw_dir=None):
    """이 배치 월의 원본이 와 있나? 없으면 False → DAG가 뒤 단계를 '건너뜀'으로 둡니다 (실패가 아님)."""
    return raw_batch_month(raw_dir) == batch_month


def step_build_bronze():
    """[1] 원본 → 로컬 Bronze (지문 영수증). Returns: 파일 수와 상태별 개수"""
    paths = layer_paths()
    manifest = build_bronze(paths["raw"], paths["bronze"])
    statuses = [entry["status"] for entry in manifest["files"]]
    return {"파일": len(statuses), **{status: statuses.count(status) for status in sorted(set(statuses))}}


def step_upload(batch_month):
    """[2] Bronze → 객체 저장소의 batch_month=YYYYMM/ 폴더."""
    report = upload_bronze(layer_paths()["bronze"], ObjectStore.from_environment(), batch_month)
    return {"올림": len(report), **report["상태"].value_counts().to_dict()}


def step_download(batch_month):
    """[3] 객체 저장소 → bronze_cache. 지문이 영수증과 다르면 DataQualityError로 멈춤."""
    target, file_count = download_bronze(ObjectStore.from_environment(), layer_paths()["bronze_cache"], batch_month)
    return {"받은 파일": file_count, "폴더": str(target)}


def step_load_raw():
    """[4] 저장소에서 받은 Bronze → PostgreSQL raw 스키마 (대사가 틀리면 되돌리고 멈춤)."""
    report = load_raw(layer_paths()["bronze_cache"], Warehouse.from_environment())
    return {row["표"]: f"{row['상태']} · {row['행 수']:,}행" for row in report.to_dict("records")}


def step_python_layers(batch_month, upload_summary=None, raw_summary=None):
    """[5] 파이썬 Silver · Gold · 대사 · 발표 형식 결과 내보내기 (통계 검정 · 보정 검증은 여기서만 함)."""
    paths = layer_paths()
    extra_checks = []
    if upload_summary:
        extra_checks.append(check_row("객체 저장소 왕복 지문", "Bronze → 저장소 → Silver", "영수증과 같음",
                                      f"{upload_summary.get('올림', 0):,}개", True, f"배치 {batch_month}"))
    for table, result in (raw_summary or {}).items():
        extra_checks.append(check_row(f"raw 적재 대사 ({table})", "Bronze → PostgreSQL", "원본과 행 수 · 합계 같음",
                                      result, True, f"배치 {batch_month}"))
    tables = build_layers_and_export(paths["bronze_cache"], paths["silver"], paths["gold"], paths["output"],
                                     extra_checks)
    report = tables["quality_report"]
    return {"대사": f"통과 {int((report['결과'] == '통과').sum())} · 경고 {int((report['결과'] == '경고').sum())}",
            "내보낸 표": len(list(Path(paths["output"]).glob("*.csv")))}


def step_dbt_build(dbt_executable, project_dir=None):
    """[6] dbt build (raw → silver → gold + 테스트). 실패하면 dbt의 마지막 출력을 담아 멈춤."""
    project_dir = Path(project_dir or config.PROJECT_ROOT / "dbt")
    result = subprocess.run(
        [dbt_executable, "build", "--project-dir", str(project_dir), "--profiles-dir", str(project_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    summary = [line for line in result.stdout.splitlines() if "Done." in line or "ERROR" in line or "FAIL" in line]
    print(result.stdout[-4000:])   # Airflow 작업 기록(log)에 남김
    if result.returncode != 0:
        raise RuntimeError("dbt build 실패:\n" + "\n".join(summary[-20:]))
    return {"dbt": summary[-1].split("Done.")[-1].strip() if summary else "끝"}


def step_compare():
    """[7] dbt Silver · Gold = 파이썬 Silver · Gold? 하나라도 다르면 실패."""
    warehouse = Warehouse.from_environment()
    reports = {"silver": compare_silver(warehouse), "gold": compare_gold(warehouse)}
    mismatched = {layer: report.loc[report["결과"] != "일치", "표"].tolist() for layer, report in reports.items()}
    if any(mismatched.values()):
        raise DataQualityError(f"dbt 결과와 파이썬 결과가 다릅니다: {mismatched}")
    return {layer: f"{len(report)}개 표 · {int(report['비교한 칸'].sum()):,}칸 일치" for layer, report in reports.items()}
