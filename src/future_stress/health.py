"""운영 상태 한 번에 보기 (Phase 4-4).

실행 (저장소 루트에서)
    .venv\\Scripts\\python -m future_stress.health              # 원본
    .venv\\Scripts\\python -m future_stress.health --synthetic  # 합성 데이터

무엇을 보나요? (위에서부터 차례로 기대고 있어서, 위가 실패하면 아래도 실패합니다)
    1. .env 계정          객체 저장소 · PostgreSQL 계정이 있나 (값은 출력하지 않음)
    2. 객체 저장소         연결되나, 가장 최근 배치 월 폴더에 영수증(_manifest.json)이 있나
    3. 새 원본             원본 폴더의 최신 배치가 저장소에 올라갔나 (안 올라갔으면 아직 처리 전)
    4. raw 적재            raw 표마다 마지막 적재 기록 (상태 · 행 수 · 시각)
    5. gold 표             dbt gold 표가 모두 있고 비어 있지 않나 (대시보드가 읽는 곳)
    6. Airflow             마지막 실행이 성공했나, 지금 떠 있나 (안 띄웠으면 '경고': 매달 자동 실행이 안 됨)

결과는 정상 · 경고 · 실패와 '할 일'로 보여 주고, 실패가 하나라도 있으면 종료 코드 1로 끝납니다.
그래서 운영 매뉴얼(docs/operations.md)의 '문제가 생기면 먼저 이것부터'로 쓰고, 다른 스크립트에서 이어 쓸 수도 있습니다.

왜 '판단'과 '읽기'를 나누나요?
    judge_* 함수는 읽어 온 값만 보고 판단하는 순수 함수라 서비스 없이 테스트합니다.
    서비스에 붙는 일은 run_checks()가 하고, 실제 서비스 테스트는 통합 테스트로 따로 돌립니다.
"""

import argparse
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from . import config
from .io_utils import read_env_value
from .object_store import DEFAULT_BUCKET, SYNTHETIC_BUCKET, ObjectStore
from .warehouse import CARD_TABLE, FUTURE_TABLE, RAW_SCHEMA, SYNTHETIC_RAW_SCHEMA, Warehouse

DATASETS = {
    "원본": {"bucket": DEFAULT_BUCKET, "raw": RAW_SCHEMA, "gold": "gold", "raw_dir": config.RAW_DATA_DIR},
    "합성": {"bucket": SYNTHETIC_BUCKET, "raw": SYNTHETIC_RAW_SCHEMA, "gold": "synthetic_gold",
           "raw_dir": config.SYNTHETIC_RAW_DIR},
}
REQUIRED_ENV = ["S3_ACCESS_KEY", "S3_SECRET_KEY", "POSTGRES_PASSWORD"]
RAW_TABLES = [CARD_TABLE.name, FUTURE_TABLE.name]
# dbt gold 모델 = dbt/models/gold/gold_*.sql (int_로 시작하는 것은 표가 생기지 않는 중간 단계)
GOLD_TABLES = sorted(path.stem for path in (config.PROJECT_ROOT / "dbt" / "models" / "gold").glob("gold_*.sql"))
DAG_ID = "future_stress_monthly"
AIRFLOW_HEALTH_URL = "http://127.0.0.1:58280/api/v2/monitor/health"
BATCH_PREFIX = re.compile(r"^batch_month=(\d{6})/")

OK, WARN, FAIL = "정상", "경고", "실패"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    action: str = ""


def display_width(text):
    """터미널에서 한글은 두 칸을 차지해서, 글자 수가 아니라 칸 수로 줄을 맞춥니다."""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def korea_time(moment):
    return moment.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M") if moment else "-"


# ===========================================================================
# 판단 (읽어 온 값만 보고 정함, 서비스 없이 테스트)
# ===========================================================================

def judge_env(missing):
    if missing:
        return Check(".env 계정", FAIL, f"없음: {', '.join(missing)}",
                     "python -m future_stress.local_env 로 만들기 (있는 값은 건드리지 않음)")
    return Check(".env 계정", OK, f"{len(REQUIRED_ENV)}개 있음 (값은 표시하지 않음)")


def latest_batch(keys):
    """객체 키 목록 → 가장 최근 배치 월 (없으면 None)."""
    months = [int(match.group(1)) for key in keys if (match := BATCH_PREFIX.match(key))]
    return max(months) if months else None


def judge_object_store(keys, bucket):
    batch = latest_batch(keys)
    if batch is None:
        return Check("객체 저장소", FAIL, f"버킷 '{bucket}'에 배치가 없음",
                     "python -m future_stress.pipeline --object-store 로 Bronze 올리기")
    in_batch = [key for key in keys if key.startswith(f"batch_month={batch}/")]
    if f"batch_month={batch}/_manifest.json" not in in_batch:
        return Check("객체 저장소", FAIL, f"배치 {batch}에 영수증(_manifest.json)이 없음 · 파일 {len(in_batch)}개",
                     "올리다 멈춘 상태일 수 있음. pipeline --object-store 를 다시 실행 (같은 파일은 '변경 없음')")
    return Check("객체 저장소", OK, f"버킷 '{bucket}' 최근 배치 {batch} · 파일 {len(in_batch)}개 (영수증 포함)")


def judge_new_batch(raw_batch, stored_batch, store_reachable=True):
    """원본 폴더의 최신 배치가 저장소에 올라갔나. 원본 폴더가 비어 있으면(다른 PC 등) 판단하지 않음."""
    if not store_reachable:
        return Check("새 원본", WARN, "객체 저장소를 볼 수 없어 판단하지 않음 (위 항목부터 해결)")
    if raw_batch is None:
        return Check("새 원본", WARN, "원본 폴더에 BC카드 파일이 없음 (이 PC에 원본이 없으면 정상)")
    if stored_batch is None or raw_batch > stored_batch:
        return Check("새 원본", WARN, f"원본 폴더 배치 {raw_batch} > 저장소 배치 {stored_batch} · 아직 처리 전",
                     f"Airflow에서 batch_month={raw_batch}로 실행 (operations.md '매달 할 일')")
    return Check("새 원본", OK, f"원본 폴더 최신 배치 {raw_batch}까지 저장소에 있음")


def judge_raw(log_rows, schema):
    """log_rows: raw._load_log의 표마다 마지막 줄 [{table_name, row_count, status, loaded_at}]"""
    if log_rows is None:
        return Check("raw 적재", FAIL, f"{schema}._load_log 표가 없음 (한 번도 적재하지 않음)",
                     "python -m future_stress.pipeline --object-store --warehouse")
    latest = {row["table_name"]: row for row in log_rows}
    missing = [table for table in RAW_TABLES if table not in latest]
    if missing:
        return Check("raw 적재", FAIL, f"적재 기록 없음: {', '.join(missing)}",
                     "python -m future_stress.pipeline --object-store --warehouse")
    detail = " · ".join(f"{table} {latest[table]['row_count']:,}행 {latest[table]['status']}" for table in RAW_TABLES)
    when = max(latest[table]["loaded_at"] for table in RAW_TABLES)
    return Check("raw 적재", OK, f"{detail} (마지막 {korea_time(when)})")


def judge_gold(row_counts, schema):
    """row_counts: {표 이름: 행 수}. 없는 표는 빠져 있음."""
    missing = [table for table in GOLD_TABLES if table not in row_counts]
    empty = [table for table in GOLD_TABLES if row_counts.get(table) == 0]
    if missing or empty:
        problems = ([f"없음 {', '.join(missing)}"] if missing else []) + ([f"비어 있음 {', '.join(empty)}"] if empty else [])
        target = " --target synthetic --vars \"{raw_schema: raw_synthetic}\"" if schema.startswith("synthetic") else ""
        return Check("gold 표", FAIL, " · ".join(problems), f"docker compose run --rm dbt build{target}")
    return Check("gold 표", OK, f"{schema} {len(GOLD_TABLES)}개 표 · {sum(row_counts[t] for t in GOLD_TABLES):,}행")


def judge_airflow(last_run, failed_tasks, web_up):
    """last_run: 가장 최근에 시작하기로 한(run_after) 실행 {run_id, state, logical_date} 또는 None(기록 DB 없음)."""
    up = "떠 있음" if web_up else "꺼져 있음"
    if last_run is None:
        return Check("Airflow", WARN, f"실행 기록 없음 · {up}",
                     "매달 자동으로 돌리려면 docker compose --profile airflow up -d")
    detail = f"마지막 실행 {last_run['run_id']} ({last_run['state']}) · {up}"
    if last_run["state"] == "failed" or failed_tasks:
        tasks = f" · 실패한 단계 {', '.join(failed_tasks)}" if failed_tasks else ""
        return Check("Airflow", FAIL, detail + tasks, "operations.md '실패했을 때'에서 그 단계를 찾아 조치 후 다시 실행")
    if not web_up:
        return Check("Airflow", WARN, detail, "매달 자동으로 돌리려면 docker compose --profile airflow up -d")
    return Check("Airflow", OK, detail)


# ===========================================================================
# 읽기 (실제 서비스에 붙음)
# ===========================================================================

def check_env():
    missing = []
    for name in REQUIRED_ENV:
        try:
            read_env_value(name)
        except ValueError:
            missing.append(name)
    return judge_env(missing), not missing


def run_checks(dataset="원본"):
    """모든 항목을 차례로 확인합니다. 한 항목이 연결 오류로 실패해도 나머지는 계속 봅니다."""
    from .orchestration import raw_batch_month   # Airflow 단계 함수와 같은 규칙으로 배치 월을 읽음

    names = DATASETS[dataset]
    env_check, env_ok = check_env()
    checks = [env_check]
    if not env_ok:
        return checks

    stored_batch, store_reachable = None, False
    try:
        keys = ObjectStore.from_environment(bucket=names["bucket"]).list_keys()
        checks.append(judge_object_store(keys, names["bucket"]))
        stored_batch, store_reachable = latest_batch(keys), True
    except Exception as error:  # noqa: BLE001  (연결 실패도 '실패' 한 줄로 보여 주고 계속)
        checks.append(Check("객체 저장소", FAIL, f"연결할 수 없음 ({type(error).__name__})",
                            "docker compose up -d 후 docker compose ps 에서 healthy 확인"))
    checks.append(judge_new_batch(raw_batch_month(names["raw_dir"]), stored_batch, store_reachable))

    try:
        warehouse = Warehouse.from_environment()
        with warehouse.connect() as connection:
            connection.read_only = True
            has_log = connection.execute("SELECT to_regclass(%s) IS NOT NULL",
                                         (f"{names['raw']}._load_log",)).fetchone()[0]
            log_rows = None
            if has_log:
                cursor = connection.execute(
                    f"SELECT DISTINCT ON (table_name) table_name, row_count, status, loaded_at "
                    f"FROM {names['raw']}._load_log ORDER BY table_name, loaded_at DESC")
                log_rows = [dict(zip([c.name for c in cursor.description], row)) for row in cursor.fetchall()]
            checks.append(judge_raw(log_rows, names["raw"]))

            existing = {row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (names["gold"],))}
            counts = {table: connection.execute(f"SELECT count(*) FROM {names['gold']}.{table}").fetchone()[0]
                      for table in GOLD_TABLES if table in existing}
            checks.append(judge_gold(counts, names["gold"]))
    except Exception as error:  # noqa: BLE001
        checks.append(Check("PostgreSQL", FAIL, f"연결할 수 없음 ({type(error).__name__})",
                            "docker compose up -d 후 docker compose ps 에서 healthy 확인"))

    if dataset == "원본":                         # DAG는 원본만 처리합니다 (합성은 CI · 손으로)
        checks.append(airflow_check())
    return checks


def airflow_check():
    try:
        web_up = requests.get(AIRFLOW_HEALTH_URL, timeout=3).ok
    except requests.RequestException:
        web_up = False
    try:
        with Warehouse.from_environment(dbname="airflow").connect() as connection:
            connection.read_only = True
            row = connection.execute(
                "SELECT run_id, state, logical_date FROM dag_run WHERE dag_id = %s "
                "ORDER BY run_after DESC LIMIT 1", (DAG_ID,)).fetchone()
            if row is None:
                return judge_airflow(None, [], web_up)
            failed = [task for (task,) in connection.execute(
                "SELECT task_id FROM task_instance WHERE dag_id = %s AND run_id = %s AND state = 'failed' "
                "ORDER BY task_id", (DAG_ID, row[0]))]
            return judge_airflow({"run_id": row[0], "state": row[1], "logical_date": row[2]}, failed, web_up)
    except Exception:  # noqa: BLE001  (기록 DB가 아직 없으면 Airflow를 한 번도 안 띄운 것)
        return judge_airflow(None, [], web_up)


def report(checks):
    width = max(display_width(check.name) for check in checks)
    lines = []
    for check in checks:
        mark = {OK: "✓", WARN: "!", FAIL: "✗"}[check.status]
        name = check.name + " " * (width - display_width(check.name))
        lines.append(f"{mark} {check.status}  {name}  {check.detail}")
        if check.action and check.status != OK:
            lines.append(f"{' ' * (width + 10)}→ {check.action}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="운영 상태 한 번에 보기 (docs/operations.md)")
    parser.add_argument("--synthetic", action="store_true", help="합성 데이터 쪽 (bronze-synthetic · raw_synthetic · synthetic_gold)")
    arguments = parser.parse_args()
    dataset = "합성" if arguments.synthetic else "원본"
    checks = run_checks(dataset)
    print(f"[{dataset}] {datetime.now(timezone.utc).astimezone(ZoneInfo(config.TIMEZONE)):%Y-%m-%d %H:%M} 기준")
    print(report(checks))
    failed = [check.name for check in checks if check.status == FAIL]
    if failed:
        raise SystemExit(f"\n실패 {len(failed)}개: {', '.join(failed)}")


if __name__ == "__main__":
    main()
