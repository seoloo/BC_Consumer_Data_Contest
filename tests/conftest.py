"""여러 테스트가 함께 쓰는 가상 데이터.

실제 BC카드 원본은 공개할 수 없어서 두 가지를 씁니다.
    - 결과를 손으로 계산할 수 있을 만큼 작은 데이터 (함수 하나하나의 계산 확인용)
    - future_stress.synthetic이 만드는 원본 형식 그대로의 합성 데이터 (파이프라인 전체 실행용)
"""

import pandas as pd
import pytest

from future_stress import config
from future_stress.synthetic import write_synthetic_raw_files


def make_raw_card_rows(region, industry, monthly_amounts_by_age):
    """원천 BC카드 형식(영문 컬럼, 코드값)의 행을 만듭니다.

    monthly_amounts_by_age: {AGE_CD: [1월, 2월, ..., 6월 이용금액]}
    """
    rows = []
    for age_code, amounts in monthly_amounts_by_age.items():
        for month, amount in zip(config.ANALYSIS_MONTHS, amounts):
            if amount is None:
                continue  # 그 달 결제가 없음
            rows.append({
                "STRD_YYMM": month, "SIDO_NM": "서울특별시", "CCG_NM": region,
                "GENDER_CD": "1", "AGE_CD": age_code,
                "TP_BUZ_NO": industry[0], "TP_BUZ_NM": industry[1],
                "amt": amount, "cnt": 1,
            })
    return rows


@pytest.fixture
def raw_card_spending():
    """구 2개 × 업종 1개.

    성동구 · 서양음식: 30대(AGE_CD 3) 중심, 매달 꾸준히 증가 → 성장
    도봉구 · 서양음식: 50대(AGE_CD 5) 중심, 4월 결제 없음 → 6개월 미완전
    """
    western_food = ("W01", "서양 음식")   # 업종명 안의 공백이 정제되는지 확인용
    rows = make_raw_card_rows("성동구", western_food, {
        "3": [60, 62, 64, 66, 68, 70],
        "6": [40, 40, 40, 40, 40, 40],
    })
    rows += make_raw_card_rows("도봉구", western_food, {
        "5": [100, 100, 100, None, 100, 100],
    })
    # 개인 결제가 아닌 행 (성별 코드 9) → 정제 단계에서 빠져야 함
    rows.append({
        "STRD_YYMM": 202601, "SIDO_NM": "서울특별시", "CCG_NM": "성동구", "GENDER_CD": "9", "AGE_CD": "3",
        "TP_BUZ_NO": "W01", "TP_BUZ_NM": "서양 음식", "amt": 999999, "cnt": 1,
    })
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def synthetic_raw_dir(tmp_path_factory):
    """원본 8종과 같은 형식의 합성 원본 (시드 42). 만드는 데 10초쯤 걸려서 테스트 전체에서 한 번만 만듭니다.

    여러 테스트가 같은 폴더를 읽기만 하고, 파이프라인은 각자 임시 폴더에 Bronze부터 새로 만듭니다.
    """
    return write_synthetic_raw_files(tmp_path_factory.mktemp("synthetic") / "raw", seed=42)
