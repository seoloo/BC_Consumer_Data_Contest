"""BC카드 결제 데이터 처리 (흐름도 STEP 1 ~ STEP 3의 재료).

이 모듈이 만드는 세 가지 표
    1. 정제된 결제 데이터        clean_card_spending()
       → 개인 결제만 남기고 코드 → 이름으로 바꾼 월별 데이터
    2. 연령별 소비구조           build_age_spending_structure()
       → 지역 × 업종 안에서 연령대별 이용금액 비중 (Future Stress의 '비중' 재료)
    3. 지역 × 업종 프로필        build_region_industry_profile()
       → 핵심 연령대, 연령 집중도, 현재 성장 지표를 한 행에 모은 표

원래 위치: notebooks/03_bc_data.ipynb 셀 0~51, 220~223
"""

import warnings

import numpy as np

from . import config
from .age_groups import BC_AGE_CODE_TO_GROUP, BC_GENDER_CODE_TO_NAME
from .io_utils import read_csv_with_encoding_fallback
from .regions import to_parent_city

# 분석의 기본 단위인 "지역 × 업종" 한 건을 구분하는 열.
# 여러 표를 merge할 때 매번 같은 리스트를 써야 해서 상수로 만들었습니다.
CASE_KEYS = ["시도", "시군구", "업종코드", "업종명"]

# 원천 영문 컬럼 → 분석용 한글 컬럼
BC_COLUMN_NAMES = {
    "STRD_YYMM": "기준년월",
    "SIDO_NM": "시도",
    "CCG_NM": "시군구",
    "TP_BUZ_NO": "업종코드",
    "TP_BUZ_NM": "업종명",
    "amt": "이용금액",
    "cnt": "이용건수",
}


def load_card_spending(path):
    """BC카드 원천 CSV를 읽습니다.

    성별 · 연령 코드를 문자열로 읽는 이유:
        원천에 숫자가 아닌 코드('x')가 섞여 있어, 숫자로 읽으면 열 전체의 타입이
        파일마다 달라질 수 있습니다. 문자열로 고정해 '1', '2' 비교가 항상 같게 동작하게 합니다.
    """
    return read_csv_with_encoding_fallback(path, dtype={"GENDER_CD": str, "AGE_CD": str})


def clean_card_spending(raw_card_spending):
    """원천 결제 데이터를 분석용으로 정제합니다. (흐름도 STEP 1)

    처리 내용
        1. 개인 결제만 남깁니다: 성별 코드 1·2, 연령 코드 1~6
           원본에는 성별 코드 '3'과 'x'가 약 34% 섞여 있습니다(연령 코드 'x' 포함).
           남녀 · 연령대를 알 수 없는 결제는 연령별 소비구조를 계산할 수 없어 제외합니다.
        2. 코드를 사람이 읽을 수 있는 이름으로 바꿉니다 (AGE_CD 3 → 30대)
        3. 컬럼명을 한글로 바꾸고 필요한 열만 남깁니다
        4. 지역명 앞뒤 공백, 업종명 안의 공백을 지웁니다
           (같은 업종인데 '일반 한식'과 '일반한식'이 따로 집계되는 문제 방지)
    """
    gender_code = raw_card_spending["GENDER_CD"].astype(str).str.strip()
    age_code = raw_card_spending["AGE_CD"].astype(str).str.strip()
    is_personal_payment = gender_code.isin(BC_GENDER_CODE_TO_NAME) & age_code.isin(BC_AGE_CODE_TO_GROUP)

    personal = raw_card_spending[is_personal_payment].copy()
    personal["연령대"] = age_code[is_personal_payment].map(BC_AGE_CODE_TO_GROUP)
    personal["성별"] = gender_code[is_personal_payment].map(BC_GENDER_CODE_TO_NAME)
    personal = personal.rename(columns=BC_COLUMN_NAMES)

    cleaned = personal[
        ["기준년월", "시도", "시군구", "성별", "연령대", "업종코드", "업종명", "이용금액", "이용건수"]
    ].copy()
    cleaned["기준년월"] = cleaned["기준년월"].astype(int)
    cleaned["시도"] = cleaned["시도"].str.strip()
    cleaned["시군구"] = cleaned["시군구"].str.strip()
    cleaned["업종명"] = cleaned["업종명"].str.replace(r"\s+", "", regex=True)
    return cleaned.reset_index(drop=True)


def merge_gyeonggi_districts_into_cities(card_spending):
    """경기도의 일반구를 상위 시로 합칩니다 (예: 수원시 장안구 → 수원시).

    왜 필요한가요?
        경기 장래인구 · 유동인구는 시 단위로만 제공되므로, BC카드도 같은 단위로
        맞춰야 연령대별 인구증감률을 붙일 수 있습니다.
        이름만 바꾸고 합계는 build_age_spending_structure()의 groupby가 계산합니다.
    """
    result = card_spending.copy()
    is_gyeonggi = result["시도"] == "경기도"
    result.loc[is_gyeonggi, "시군구"] = result.loc[is_gyeonggi, "시군구"].map(to_parent_city)
    return result


def build_age_spending_structure(card_spending):
    """지역 × 업종 안에서 연령대별 이용금액 비중을 계산합니다.

    결과 열
        이용금액, 이용건수    6개월 합계
        업종총이용금액        같은 지역 × 업종의 전체 연령 합계
        이용금액비중          이 연령대가 차지하는 비중 (%)

    이 '이용금액비중'이 Future Stress 공식의 "연령별 이용금액 비중"입니다.

    반올림을 남겨 둔 이유:
        원래 노트북은 비중을 소수 첫째 자리로 반올림한 뒤 그 값으로 Stress를
        계산했습니다. 발표 수치와 똑같은 결과를 내기 위해 같은 반올림을 유지합니다.
    """
    structure = (
        card_spending
        .groupby(CASE_KEYS + ["연령대"], as_index=False)[["이용금액", "이용건수"]]
        .sum()
    )
    structure["업종총이용금액"] = (
        structure.groupby(["시도", "시군구", "업종코드"])["이용금액"].transform("sum")
    )
    structure["이용금액비중"] = (structure["이용금액"] / structure["업종총이용금액"] * 100).round(1)
    return structure


def find_main_customer_age(age_structure):
    """지역 × 업종마다 이용금액 비중이 가장 큰 연령대(= 현재 핵심 고객)를 찾습니다."""
    main_row_index = age_structure.groupby(["시도", "시군구", "업종코드"])["이용금액비중"].idxmax()
    return age_structure.loc[
        main_row_index, CASE_KEYS + ["연령대", "이용금액비중", "업종총이용금액"]
    ].reset_index(drop=True)


def calculate_age_concentration(age_structure):
    """연령 집중도(HHI)를 계산합니다.

    HHI = Σ (연령대 비중)²
        한 연령대에 몰릴수록 1에 가깝고, 6개 연령대에 고르게 퍼질수록 1/6에 가깝습니다.
        특정 연령에 의존하는 정도를 숫자 하나로 비교하려고 사용합니다.
    """
    squared_share = (age_structure["이용금액비중"] / 100) ** 2
    return (
        age_structure.assign(비중제곱=squared_share)
        .groupby(CASE_KEYS, as_index=False)["비중제곱"]
        .sum()
        .rename(columns={"비중제곱": "연령집중도"})
    )


def calculate_monthly_growth(card_spending, months=None):
    """지역 × 업종별 현재 성장 지표를 계산합니다. (흐름도 STEP 3의 재료)

    결과 열
        데이터보유개월수    6개월 중 결제가 있었던 달 수
        6개월완전          6개월 모두 결제가 있었는지
        1월대비6월증감률    (6월 - 1월) / 1월 × 100
        월평균증감률        5번의 전월 대비 증감률 평균
        상승개월수          전월보다 이용금액이 늘어난 달 수 (0~5)

    6개월이 다 있지 않으면 성장 지표를 NaN으로 둡니다.
        중간 달이 빠지면 증감률이 실제와 다르게 계산되므로, 판정에서 아예 제외하기 위해서입니다.
    """
    months = months or config.ANALYSIS_MONTHS

    monthly_amount = (
        card_spending
        .groupby(CASE_KEYS + ["기준년월"], as_index=False)["이용금액"]
        .sum()
        .pivot_table(index=CASE_KEYS, columns="기준년월", values="이용금액")
        .reindex(columns=months)   # 어떤 달이 통째로 없더라도 6개 열을 유지
    )

    growth = monthly_amount.reset_index()[CASE_KEYS].copy()
    amounts = monthly_amount.to_numpy(dtype=float)

    growth["데이터보유개월수"] = np.isfinite(amounts).sum(axis=1)
    growth["6개월완전"] = growth["데이터보유개월수"] == len(months)

    # 빈 달(NaN)이 있는 행은 계산 중 경고가 나지만, 아래에서 어차피 NaN 처리하므로 경고를 끕니다.
    with np.errstate(divide="ignore", invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        # 전월 대비 증감률 (%): 2월/1월, 3월/2월, ... 6월/5월 → 5개 값
        month_over_month_change = (amounts[:, 1:] / amounts[:, :-1] - 1) * 100
        # 반올림 후 0과 비교하는 원래 방식을 유지합니다 (0.04%는 0.0이 되어 '성장 아님').
        growth["월평균증감률"] = np.round(np.nanmean(month_over_month_change, axis=1), 1)
        growth["1월대비6월증감률"] = np.round((amounts[:, -1] - amounts[:, 0]) / amounts[:, 0] * 100, 1)
    growth["상승개월수"] = (month_over_month_change > 0).sum(axis=1).astype(float)

    growth_columns = ["월평균증감률", "상승개월수", "1월대비6월증감률"]
    growth.loc[~growth["6개월완전"], growth_columns] = np.nan
    return growth


def build_region_industry_profile(card_spending, age_structure):
    """지역 × 업종 한 건마다 분석에 필요한 정보를 한 행으로 모읍니다.

    합치는 정보
        핵심 연령대와 비중, 업종총이용금액  ← find_main_customer_age
        연령집중도                          ← calculate_age_concentration
        현재 성장 지표                      ← calculate_monthly_growth
    """
    return (
        find_main_customer_age(age_structure)
        .merge(calculate_age_concentration(age_structure), on=CASE_KEYS, how="left")
        .merge(calculate_monthly_growth(card_spending), on=CASE_KEYS, how="left")
    )
