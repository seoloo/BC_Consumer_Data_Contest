"""현재 성장 판정, 4유형 분류, 통계 검정을 확인합니다."""

import pandas as pd
import pytest

from future_stress.analysis.diagnosis import add_market_type, is_strictly_growing, select_analysis_targets, size_cutoff
from future_stress.analysis.validation import build_growth_comparison_table, run_statistical_tests, split_by_growth


def make_cases(growth_rows, stress_2035, stress_2040):
    """(1→6월, 월평균, 상승개월수) 튜플 목록으로 사례 표를 만듭니다."""
    return pd.DataFrame({
        "첫달대비마지막달증감률": [row[0] for row in growth_rows],
        "월평균증감률": [row[1] for row in growth_rows],
        "상승개월수": [row[2] for row in growth_rows],
        "2035 순인구효과": stress_2035,
        "2040 순인구효과": stress_2040,
    })


def test_strict_growth_needs_all_three_conditions():
    cases = make_cases(
        [(5.0, 1.0, 3), (5.0, 1.0, 2), (-1.0, 1.0, 4), (5.0, 0.0, 4), (None, None, None)],
        [0] * 5, [0] * 5,
    )
    # 세 조건을 모두 만족한 첫 번째만 성장. 값이 비어 있으면(6개월 미완전) 성장 아님.
    assert is_strictly_growing(cases).tolist() == [True, False, False, False, False]


def test_market_type_matrix():
    cases = make_cases(
        [(5, 1, 3), (5, 1, 3), (-5, -1, 1), (-5, -1, 1)],
        [0] * 4,
        [-3.0, 2.0, -3.0, 0.0],   # 0은 '안정'으로 분류
    )
    assert add_market_type(cases)["유형"].tolist() == ["착시성장형", "지속성장형", "구조취약형", "회복기회형"]


def test_select_analysis_targets_by_size_and_completeness():
    profile = pd.DataFrame({
        "업종총이용금액": [10, 20, 30, 40, 50, 60, 70, 80],
        "6개월완전": [True, True, True, True, True, True, False, True],
    })
    cutoff = size_cutoff(profile, 25)               # 75분위수 = 62.5
    targets = select_analysis_targets(profile, cutoff)
    assert targets["업종총이용금액"].tolist() == [80]  # 70은 6개월 미완전이라 제외


def test_fisher_p_value_is_computed_from_data():
    """원래 노트북에 손으로 적혀 있던 14/0, 74/26 표를 데이터에서 직접 만들어도
    결과표 수치(p = 0.0206)가 그대로 나오는지 확인합니다."""
    growth = make_cases([(5, 1, 3)] * 14, [-1.0] * 14, [-2.0] * 14)
    non_growth = make_cases([(-5, -1, 1)] * 100, [-1.0] * 74 + [1.0] * 26, [-2.0] * 74 + [1.0] * 26)
    cases = pd.concat([growth, non_growth], ignore_index=True)

    growth_cases, non_growth_cases = split_by_growth(cases)
    assert (len(growth_cases), len(non_growth_cases)) == (14, 100)

    tests = run_statistical_tests(growth_cases, non_growth_cases).set_index("검정")
    assert tests.loc["2035 위험비율 Fisher exact", "p-value"] == pytest.approx(0.0206, abs=1e-4)

    comparison = build_growth_comparison_table(growth_cases, non_growth_cases).set_index("구분")
    assert comparison.loc["현재 성장", "2035 위험비율(%)"] == 100.0
    assert comparison.loc["비성장", "2035 위험비율(%)"] == 74.0
