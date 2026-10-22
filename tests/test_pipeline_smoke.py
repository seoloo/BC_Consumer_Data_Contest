"""파이프라인 전체를 합성 원본으로 끝까지 실행해 보는 테스트 (smoke test).

숫자가 맞는지가 아니라, Bronze → Silver → Gold → 대사 → 내보내기가 중간에 끊기지 않고
이어지는지, 결과 표의 열 이름이 발표 결과 CSV와 같은지를 확인합니다.
모든 계층은 pytest가 만든 임시 폴더(tmp_path)에 만들어 실제 data/ 폴더를 건드리지 않습니다.
"""

import json

import pandas as pd
import pytest

from future_stress.medallion import build_bronze, run_quality_checks
from future_stress.pipeline import check_raw_files, compare_with_published, run_pipeline

PUBLISHED_COLUMNS = {
    "growth_vs_nongrowth_validation": ["구분", "사례수", "2035 위험비율(%)", "2035 스트레스 중앙값",
                                       "2040 추가악화비율(%)", "2040 스트레스 중앙값"],
    "statistical_validation": ["검정", "p-value"],
    "size_threshold_sensitivity": ["규모기준", "현재성장사례", "2035 위험사례", "2035 위험비율(%)",
                                   "2040 추가악화", "2040 추가악화비율(%)"],
    "stress_test_14_cases_table": ["시군구", "업종명", "현재 핵심연령대", "월평균 성장률", "1→6월 증감률",
                                   "2035 스트레스", "2040 스트레스", "2040 추가악화폭"],
    "representative_3_cases_table": ["지역", "업종", "현재 핵심고객", "진단", "방어형 고객",
                                     "전환 전", "전환 후", "위험완화율(%)"],
    "final_3region_robustness": ["지역", "검증사례수", "분류일치율", "변경건수", "Spearman_rho", "비고"],
}


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory, synthetic_raw_dir):
    """합성 원본으로 파이프라인을 한 번 실행하고, 여러 테스트가 결과를 함께 씁니다."""
    root = tmp_path_factory.mktemp("pipeline")
    data_dir, output_dir = root / "data", root / "output"
    tables = run_pipeline(synthetic_raw_dir, output_dir, data_dir)
    return {"raw": synthetic_raw_dir, "data": data_dir, "output": output_dir, "tables": tables}


def test_missing_raw_files_are_reported_at_once(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"bc_card_\*\.csv"):
        check_raw_files(tmp_path)


def test_each_layer_is_written(pipeline_run):
    data_dir = pipeline_run["data"]
    assert (data_dir / "bronze" / "_manifest.json").exists()
    assert (data_dir / "bronze" / "card_spending" / "bc_card_202601_202606.csv").exists()
    assert {p.stem for p in (data_dir / "silver").glob("*.parquet")} == {
        "card_spending", "future_population", "resident_population",
        "seoul_living_share", "busan_living_exposure", "gyeonggi_flow_share",
    }
    assert (data_dir / "gold" / "future_stress.parquet").exists()
    assert (data_dir / "gold" / "_quality_report.csv").exists()


def test_published_tables_have_same_columns(pipeline_run):
    tables, output_dir = pipeline_run["tables"], pipeline_run["output"]
    for name, columns in PUBLISHED_COLUMNS.items():
        assert (output_dir / f"{name}.csv").exists(), name
        assert tables[name].columns.tolist() == columns, name

    robustness = tables["final_3region_robustness"].set_index("지역")
    assert robustness.index.tolist() == ["서울", "부산", "경기"]
    assert (robustness["검증사례수"] > 0).all()

    # 4유형 건수는 한 건도 없는 유형이 있어도 항상 4줄 (합성 데이터에는 지속성장형이 없음 · dbt 모델과 같은 모양)
    assert tables["market_type_counts"]["유형"].tolist() == ["착시성장형", "지속성장형", "구조취약형", "회복기회형"]

    # 발표 결과와의 비교 함수도 끝까지 돌아야 함 (합성 데이터라 값은 '불일치'가 정상)
    report = compare_with_published(output_dir)
    assert set(report["결과"]) <= {"일치", "불일치", "비교불가"}


def test_quality_checks_reconcile_layers(pipeline_run):
    """합성 원본에는 개인이 아닌 결제(성별 3 · x)가 섞여 있습니다. 대사가 그만큼 정확히 맞아야 합니다."""
    report = pipeline_run["tables"]["quality_report"].set_index("검사")
    assert report.loc["카드 행 수 대사", "결과"] == "통과"
    assert report.loc["카드 금액 대사", "결과"] == "통과"
    assert report.loc["전국 소비구조 금액 대사", "결과"] == "통과"
    assert report.loc["경기 시 단위 통합 대사", "결과"] == "통과"
    assert "실패" not in set(report["결과"])


def test_quality_check_detects_lost_rows(pipeline_run):
    """Silver에서 행이 사라지면 대사가 '실패'를 내야 합니다 (검사가 실제로 동작하는지 확인)."""
    from future_stress.medallion import read_silver

    silver = read_silver(pipeline_run["data"] / "silver")
    silver["card_spending"] = silver["card_spending"].iloc[1:]   # 일부러 한 행을 지움
    report = run_quality_checks(pipeline_run["data"] / "bronze", silver, pipeline_run["tables"]).set_index("검사")
    assert report.loc["카드 행 수 대사", "결과"] == "실패"


def test_bronze_is_idempotent(pipeline_run):
    """같은 원본으로 다시 적재하면 파일을 다시 복사하지 않고 '변경 없음'으로 기록합니다."""
    manifest = build_bronze(pipeline_run["raw"], pipeline_run["data"] / "bronze")
    assert {entry["status"] for entry in manifest["files"]} == {"변경 없음"}
    saved = json.loads((pipeline_run["data"] / "bronze" / "_manifest.json").read_text(encoding="utf-8"))
    card_entry = next(e for e in saved["files"] if e["source"] == "card")
    assert len(card_entry["sha256"]) == 64 and card_entry["rows"] > 0
    assert isinstance(pd.Timestamp(saved["ingested_at"]), pd.Timestamp)
