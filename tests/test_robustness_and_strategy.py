"""외부유입 보정과 고객 구성 재조정 최적화를 확인합니다."""

import numpy as np
import pandas as pd
import pytest

from future_stress.robustness import (
    renormalize_shares,
    reweight_stress_by_external_population,
    summarize_robustness,
)
from future_stress.strategy import (
    optimize_mix_for_max_mitigation,
    optimize_mix_for_min_change,
    pick_representative_cases,
    stress_of_mix,
)

AGES = ["30대", "60대이상"]


def make_reweight_inputs(external_30s_share):
    structure = pd.DataFrame({
        "시군구": ["성동구", "성동구"], "업종코드": ["W01", "W01"], "업종명": ["서양음식", "서양음식"],
        "연령대": AGES, "이용금액": [60.0, 40.0],
    })
    external = pd.DataFrame({"시군구": ["성동구"] * 2, "연령대": AGES,
                             "생활인구비중": [external_30s_share, 100 - external_30s_share]})
    resident = pd.DataFrame({"시군구": ["성동구"] * 2, "연령대": AGES, "주민등록인구비중": [50.0, 50.0]})
    future = pd.DataFrame({"시군구": ["성동구"] * 2, "연령대": AGES, "2040 증감률": [-20.0, 10.0]})
    return structure, external, "생활인구비중", resident, future, AGES


def test_reweight_without_external_inflow_keeps_stress():
    """생활인구 구성이 주민등록인구와 같으면(보정계수 1) 보정 전후 Stress가 같아야 합니다."""
    comparison = reweight_stress_by_external_population(*make_reweight_inputs(50.0))
    row = comparison.iloc[0]
    assert row["기존Stress"] == pytest.approx(0.6 * -20 + 0.4 * 10)
    assert row["보정Stress"] == pytest.approx(row["기존Stress"])
    assert bool(row["분류일치"]) is True


def test_reweight_with_more_young_visitors_increases_risk():
    """30대 방문객이 많으면(30대 인구 감소 지역) 보정 후 Stress가 더 나빠져야 합니다."""
    comparison = reweight_stress_by_external_population(*make_reweight_inputs(70.0))
    row = comparison.iloc[0]
    assert row["보정Stress"] < row["기존Stress"]


def test_renormalize_shares_sums_to_100():
    shares = pd.DataFrame({"시군구": ["A"] * 3, "연령대": ["20대이하", "20대", "30대"], "유동인구비중": [20.0, 40.0, 40.0]})
    adults = renormalize_shares(shares, "유동인구비중", ["20대", "30대"])
    assert adults["유동인구비중"].tolist() == [50.0, 50.0]


def test_summarize_robustness():
    comparison = pd.DataFrame({"기존Stress": [-3.0, -2.0, 1.0, 2.0], "보정Stress": [-2.5, 0.5, 1.5, 2.5]})
    summary = summarize_robustness(comparison, "테스트")
    assert summary["검증사례수"] == 4
    assert summary["변경건수"] == 1          # 두 번째 사례만 위험 → 안정
    assert summary["분류일치율"] == 75.0
    assert summary["Spearman_rho"] == 1.0    # 순위는 그대로


@pytest.fixture
def customer_mix():
    current = np.array([10.0, 20.0, 40.0, 30.0])          # 합 100
    change = np.array([5.0, -10.0, -30.0, 20.0])          # 연령대별 인구증감률
    lower = current - 5
    upper = current + 10
    return current, change, lower, upper


def test_linear_optimization_respects_shift_limit(customer_mix):
    current, change, lower, upper = customer_mix
    new_mix = optimize_mix_for_max_mitigation(current, change, lower, upper, max_shift_pp=5)
    assert new_mix.sum() == pytest.approx(100)
    assert np.abs(new_mix - current).sum() / 2 == pytest.approx(5)      # 옮긴 양 = 5%p
    assert stress_of_mix(new_mix, change) > stress_of_mix(current, change)
    # 인구가 가장 많이 줄어드는 연령대(-30%)를 줄이고 가장 많이 느는 연령대(+20%)로 옮겨야 함
    assert np.argmin(new_mix - current) == 2 and np.argmax(new_mix - current) == 3


def test_min_change_optimization_reaches_target(customer_mix):
    current, change, lower, upper = customer_mix
    before = stress_of_mix(current, change)
    new_mix = optimize_mix_for_min_change(current, change, lower, upper, target_mitigation_pct=10)
    assert new_mix is not None
    assert stress_of_mix(new_mix, change) >= before + abs(before) * 0.10 - 1e-6
    assert np.sum((new_mix / 100) ** 2) <= np.sum((current / 100) ** 2) + 1e-9   # 연령 집중도 악화 없음


def test_representative_cases_do_not_repeat_region_or_industry():
    cases = pd.DataFrame({
        "시군구": ["성동구", "성동구", "도봉구", "종로구", "성북구"],
        "업종명": ["서양음식", "편의점", "편의점", "서양음식", "일반한식"],
        "2040 순인구효과": [-17.2, -16.9, -16.6, -14.6, -5.1],
    })
    picked = pick_representative_cases(cases)
    assert list(zip(picked["시군구"], picked["업종명"])) == [("성동구", "서양음식"), ("도봉구", "편의점"), ("성북구", "일반한식")]
