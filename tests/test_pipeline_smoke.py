"""파이프라인 전체를 가짜 원본으로 끝까지 실행해 보는 테스트 (smoke test).

숫자가 맞는지가 아니라, 파일 읽기 → 정제 → Stress → 검증 → 전략 → 저장이
중간에 끊기지 않고 이어지는지, 결과 표의 열 이름이 발표 결과 CSV와 같은지를 확인합니다.
"""

import pandas as pd
import pytest

from future_stress.pipeline import check_raw_files, compare_with_published, run_pipeline
from synthetic_raw_files import write_all_raw_files

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


def test_missing_raw_files_are_reported_at_once(tmp_path):
    with pytest.raises(FileNotFoundError, match="bc_card_202601_202606.csv"):
        check_raw_files(tmp_path)


def test_pipeline_runs_end_to_end(tmp_path):
    raw_dir, output_dir = tmp_path / "raw", tmp_path / "output"
    write_all_raw_files(raw_dir)

    tables = run_pipeline(raw_dir, output_dir)

    for name, columns in PUBLISHED_COLUMNS.items():
        assert (output_dir / f"{name}.csv").exists(), name
        assert tables[name].columns.tolist() == columns, name

    robustness = tables["final_3region_robustness"].set_index("지역")
    assert robustness.index.tolist() == ["서울", "부산", "경기"]
    assert (robustness["검증사례수"] > 0).all()
    assert set(tables["market_type_counts"].columns) == {"유형", "서울", "부산", "경기"}

    # 발표 결과와의 비교 함수도 끝까지 돌아야 함 (가짜 데이터라 값은 '불일치'가 정상)
    report = compare_with_published(output_dir)
    assert set(report["결과"]) <= {"일치", "불일치", "비교불가"}
    assert isinstance(report, pd.DataFrame)
