"""분석 대상 선정 · 현재 성장 판정 · 4유형 분류 (흐름도 STEP 2, 3, 5).

원래 위치: contest/notebooks/03_bc_data.ipynb 셀 42~44, 193~194, 226, 230, 234~240
"""

import numpy as np

from .. import config
from .stress import stress_column

# 4유형 이름과 전략 방향 (README · 발표자료와 같은 표현)
MARKET_TYPE_STRATEGY = {
    "착시성장형": "방어",   # 지금은 성장하지만 미래 고객 기반이 약해짐
    "지속성장형": "확장",   # 지금도 성장하고 미래 고객 기반도 안정적
    "구조취약형": "재편",   # 지금도 성장하지 않고 미래 고객 기반도 약해짐
    "회복기회형": "선점",   # 지금은 성장하지 않지만 미래 고객 기반은 안정적
}


def size_cutoff(profile, top_percent=None):
    """'이용금액 상위 N%'에 들어가기 위한 최소 업종총이용금액을 구합니다.

    상위 25% = 75분위수 이상이므로 quantile(1 - 25/100)을 사용합니다.

    주의 · 어떤 표로 기준을 계산하느냐에 따라 값이 달라집니다.
        발표자료의 '서울 성장 14건 vs 비성장 100건'은 전국 프로필로 계산한 기준을 썼고,
        3개 지역 비교(validation.validate_region)는 각 지역 안에서 계산한 기준을 썼습니다.
    """
    top_percent = top_percent or config.SIZE_TOP_PERCENT
    return profile["업종총이용금액"].quantile(1 - top_percent / 100)


def select_analysis_targets(region_result, minimum_total_amount):
    """분석 대상을 고릅니다. (흐름도 STEP 2)

    조건
        1. 6개월 모두 결제가 관측됨 → 성장 지표를 믿을 수 있음
        2. 업종총이용금액이 기준 이상 → 몇 건의 결제로 크게 흔들리지 않을 만큼 규모가 큼
    """
    is_target = (region_result["6개월완전"] == True) & (  # noqa: E712  NaN을 False로 다루기 위해 == True
        region_result["업종총이용금액"] >= minimum_total_amount
    )
    return region_result[is_target].reset_index(drop=True)


def is_strictly_growing(cases):
    """현재 성장 여부를 판정합니다. (흐름도 STEP 3)

    세 조건을 모두 만족해야 '성장'입니다.
        1. 1월 → 6월 증감률 > 0          (기간 전체로 보면 늘었다)
        2. 월평균 증감률 > 0             (평균적으로도 늘었다)
        3. 전월보다 오른 달 ≥ 3개월      (한두 달 급등이 아니라 꾸준히 늘었다)

    조건 하나만 쓰면 6월 한 달 반짝 오른 사례도 성장으로 잡히기 때문에 세 개를 함께 봅니다.
    값이 비어 있으면(6개월 미완전) 비교 결과가 False가 되어 자연스럽게 '성장 아님'이 됩니다.
    """
    return (
        (cases["첫달대비마지막달증감률"] > 0)
        & (cases["월평균증감률"] > 0)
        & (cases["상승개월수"] >= config.MIN_RISING_MONTHS)
    )


def classify_market_type(is_growing, future_stress):
    """현재 성장 여부와 Future Stress 부호로 4유형을 정합니다. (흐름도 STEP 5)

                     Stress < 0 (취약)   Stress ≥ 0 (안정)
        성장          착시성장형           지속성장형
        비성장        구조취약형           회복기회형
    """
    is_stable = future_stress >= 0
    return np.select(
        [is_growing & ~is_stable, is_growing & is_stable, ~is_growing & ~is_stable],
        ["착시성장형", "지속성장형", "구조취약형"],
        default="회복기회형",
    )


def add_market_type(cases, year=2040):
    """표에 '유형' 열을 추가합니다. 발표자료는 2040년 Stress 기준으로 분류했습니다."""
    result = cases.copy()
    result["유형"] = classify_market_type(is_strictly_growing(result), result[stress_column(year)])
    return result
