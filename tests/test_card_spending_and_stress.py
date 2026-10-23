"""BC카드 정제 → 연령별 소비구조 → 성장 지표 → Future Stress 계산을 손계산 값과 비교합니다.

conftest.py의 성동구 · 서양음식 손계산
    30대     60+62+64+66+68+70 = 390      비중 390/630 = 61.9%
    60대이상  40 × 6           = 240      비중 240/630 = 38.1%
    월 합계   100, 102, 104, 106, 108, 110
    전월 대비 2.00, 1.96, 1.92, 1.89, 1.85 (%) → 평균 1.9, 상승 5개월, 1→6월 +10.0%
"""

import numpy as np
import pandas as pd
import pytest

from future_stress.analysis.card_spending import (
    build_age_spending_structure,
    build_region_industry_profile,
    calculate_age_concentration,
    clean_card_spending,
)
from future_stress.analysis.stress import build_region_result


@pytest.fixture
def cleaned(raw_card_spending):
    return clean_card_spending(raw_card_spending)


def test_clean_keeps_only_personal_payments(cleaned):
    assert 999999 not in cleaned["이용금액"].tolist()        # 성별 코드 9인 행 제외
    assert set(cleaned["연령대"]) == {"30대", "60대이상", "50대"}
    assert cleaned["업종명"].unique().tolist() == ["서양음식"]  # '서양 음식' → 공백 제거


def test_age_spending_share(cleaned):
    structure = build_age_spending_structure(cleaned)
    seongdong = structure[structure["시군구"] == "성동구"].set_index("연령대")
    assert seongdong.loc["30대", "이용금액비중"] == 61.9
    assert seongdong.loc["60대이상", "이용금액비중"] == 38.1
    assert seongdong.loc["30대", "업종총이용금액"] == 630


def test_age_concentration_hhi(cleaned):
    hhi = calculate_age_concentration(build_age_spending_structure(cleaned)).set_index("시군구")
    assert hhi.loc["성동구", "연령집중도"] == pytest.approx(0.619 ** 2 + 0.381 ** 2)
    assert hhi.loc["도봉구", "연령집중도"] == pytest.approx(1.0)   # 한 연령대뿐이면 1


def test_growth_metrics_and_incomplete_months(cleaned):
    profile = build_region_industry_profile(cleaned, build_age_spending_structure(cleaned)).set_index("시군구")

    seongdong = profile.loc["성동구"]
    assert seongdong["연령대"] == "30대"                  # 핵심 고객
    assert bool(seongdong["6개월완전"]) is True
    assert seongdong["월평균증감률"] == 1.9
    assert seongdong["상승개월수"] == 5
    assert seongdong["1월대비6월증감률"] == 10.0

    dobong = profile.loc["도봉구"]
    assert dobong["데이터보유개월수"] == 5
    assert bool(dobong["6개월완전"]) is False
    assert np.isnan(dobong["월평균증감률"])                # 빈 달이 있으면 성장 판정에서 제외


def test_future_stress_formula(cleaned):
    structure = build_age_spending_structure(cleaned)
    profile = build_region_industry_profile(cleaned, structure)
    future = pd.DataFrame({
        "시군구": ["성동구", "성동구", "도봉구"],
        "연령대": ["30대", "60대이상", "50대"],
        "2030 증감률": [0.0, 0.0, 0.0],
        "2035 증감률": [-10.0, 20.0, -5.0],
        "2040 증감률": [-25.0, 30.0, -8.0],
    })
    result, age_stress = build_region_result(profile, structure, future, "서울특별시")
    seongdong = result.set_index("시군구").loc["성동구"]

    # Stress = Σ 비중 × 증감률
    assert seongdong["2040 순인구효과"] == pytest.approx(0.619 * -25 + 0.381 * 30)
    assert seongdong["2035 순인구효과"] == pytest.approx(0.619 * -10 + 0.381 * 20)
    # 연령대별 기여도도 남아 있어야 전략 단계에서 쓸 수 있음
    assert len(age_stress[age_stress["시군구"] == "성동구"]) == 2
