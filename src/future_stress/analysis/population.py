"""인구 데이터 읽기 · 정리 모듈.

다루는 데이터 네 종류
    1. 장래인구 추계 (서울 · 부산 · 경기)   → Future Stress의 "2040 인구증감률"
    2. 주민등록인구 (행안부, 월별)          → 생활/유동인구 보정의 기준값
    3. 생활인구 (서울 · 부산)               → 외부유입 보정 (robustness 모듈에서 사용)
    4. 유동인구 (경기)                      → 외부유입 보정

모든 함수는 마지막에 같은 모양의 표를 돌려주도록 맞췄습니다.
    장래인구:  시군구 | 연령대 | 2026 | 2030 | 2035 | 2040 | 2030 증감률 | ...
    인구비중:  시군구 | 연령대 | (주민등록/생활/유동)인구비중
지역마다 원본 형식이 달라도, 이 모듈을 통과하면 다음 단계는 지역을 구분할 필요가 없습니다.

원래 위치: contest/notebooks/01_population.ipynb 셀 6~55, 81~141, 252
"""

import csv
import re
from pathlib import Path

import pandas as pd

from .. import config
from .age_groups import (
    AGE_GROUP_ORDER,
    age_group_from_label,
    standardize_age_group_name,
)
from ..io_utils import read_csv_with_encoding_fallback, parse_number_with_commas
from .regions import SEOUL_DISTRICT_CODE_TO_NAME, fix_region_name

# ===========================================================================
# 1. 장래인구 추계
# ===========================================================================

# 서울 장래인구 파일에서 사용할 5세 구간 이름.
# 파일에는 5세 구간('0~4세')과 1세 단위('0세', '1세', ...), '합계' 행이 함께 들어 있어서,
# 그대로 더하면 같은 사람이 두 번 세어집니다. 5세 구간만 골라 쓰기 위한 허용 목록입니다.
#
# 주의 · 90세 이상 누락
#   실제 파일의 마지막 구간은 '90~94세', '95세 이상'인데, 원래 노트북의 목록에는 파일에 없는
#   '90세 이상'이 들어 있었습니다. 그래서 서울의 90세 이상 인구는 계산에서 빠졌습니다.
#   공모전 결과표를 그대로 재현하기 위해 목록을 유지하고 docs/refactoring_notes.md에 기록했습니다.
SEOUL_FIVE_YEAR_AGE_LABELS = [
    "0~4세", "5~9세", "10~14세", "15~19세", "20~24세", "25~29세", "30~34세",
    "35~39세", "40~44세", "45~49세", "50~54세", "55~59세", "60~64세", "65~69세",
    "70~74세", "75~79세", "80~84세", "85~89세", "90세 이상",
]

# 장래인구에서 실제로 쓰는 연도. 기준연도(2026)와 비교연도(2030·2035·2040).
POPULATION_YEARS = [config.POPULATION_BASE_YEAR] + config.POPULATION_TARGET_YEARS


def add_population_change_rates(future_population):
    """기준연도(2026) 대비 각 연도의 인구증감률(%)을 추가합니다.

    증감률 = (그 해 인구 - 2026년 인구) / 2026년 인구 × 100
    양수면 인구가 늘고, 음수면 줄어든다는 뜻입니다.
    """
    result = future_population.copy()
    base = result[config.POPULATION_BASE_YEAR]
    for year in config.POPULATION_TARGET_YEARS:
        result[f"{year} 증감률"] = ((result[year] - base) / base * 100).round(1)
    return result


def load_seoul_future_population(path):
    """서울 장래인구 CSV를 '시군구 × 연령대' 표로 바꿉니다.

    pandas.read_csv 대신 csv 모듈로 읽는 이유:
        파일 중간(약 9,048번째 줄)에 닫히지 않은 따옴표가 있어 pandas.read_csv가
        ParserError("EOF inside string")로 멈춥니다. 파이썬 기본 csv.reader는 이런 줄을
        더 너그럽게 처리하므로, 줄 단위로 읽은 뒤 첫 줄을 열 이름으로 사용합니다.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    raw = pd.DataFrame(rows[1:], columns=[name.strip() for name in rows[0]])

    is_five_year_row = (
        (raw["성별"] == "계")                                   # 남녀 합계만
        & raw["연령별"].isin(SEOUL_FIVE_YEAR_AGE_LABELS)        # 5세 구간만
        & (raw["자치구별"] != "합계")                           # 서울 전체 합계 행 제외
    )
    five_year = raw[is_five_year_row].copy()
    five_year["연령대"] = five_year["연령별"].map(age_group_from_label)

    # 연도 열 이름이 '2026 년' 형식이라 숫자 연도로 바꿔 다른 지역과 맞춥니다.
    for year in POPULATION_YEARS:
        five_year[year] = pd.to_numeric(five_year[f"{year} 년"], errors="coerce").fillna(0)

    future = (
        five_year.rename(columns={"자치구별": "시군구"})
        .groupby(["시군구", "연령대"], as_index=False)[POPULATION_YEARS]
        .sum()
    )
    return add_population_change_rates(future)


def load_kosis_future_population(path, province_total_name):
    """부산 · 경기처럼 KOSIS 엑셀 형식으로 받은 장래인구를 '시군구 × 연령대' 표로 바꿉니다.

    엑셀 형식의 특징과 처리
        - 병합된 셀 때문에 '시군구별', '성별'이 첫 행에만 있고 아래는 비어 있음
          → ffill()로 위의 값을 아래로 채웁니다.
        - '연령별(2)'에 '소계'와 세부 행이 함께 있음 → 5세 구간 '소계' 행만 사용
        - 시도 전체 합계 행(예: '부산광역시')과 연령 '계' 행은 중복 집계라 제외

    Args:
        path: 엑셀 파일 경로.
        province_total_name: 제외할 시도 합계 행의 이름 (예: "부산광역시", "경기도").
    """
    raw = pd.read_excel(path, sheet_name=0, header=0)
    raw["시군구별"] = raw["시군구별"].ffill()
    raw["성별"] = raw["성별"].ffill()

    is_five_year_subtotal = (
        (raw["성별"] == "계")
        & (raw["연령별(2)"] == "소계")
        & (raw["시군구별"] != province_total_name)
    )
    five_year = raw[is_five_year_subtotal].copy()
    five_year["연령구간"] = five_year["연령별(1)"].astype(str).str.replace(" ", "", regex=False)
    five_year = five_year[five_year["연령구간"] != "계"].copy()
    five_year["연령대"] = five_year["연령구간"].map(age_group_from_label)

    for year in POPULATION_YEARS:
        five_year[year] = pd.to_numeric(five_year[year], errors="coerce")

    future = (
        five_year.rename(columns={"시군구별": "시군구"})
        .groupby(["시군구", "연령대"], as_index=False)[POPULATION_YEARS]
        .sum()
    )
    return add_population_change_rates(future)


# ===========================================================================
# 2. 주민등록인구 (행정안전부 월별 연령별 인구)
# ===========================================================================

# 10세 단위 원본 열 → 분석 연령대
RESIDENT_AGE_COLUMNS = {
    "20대이하": ["0~9세", "10~19세"],
    "20대": ["20~29세"],
    "30대": ["30~39세"],
    "40대": ["40~49세"],
    "50대": ["50~59세"],
    "60대이상": ["60~69세", "70~79세", "80~89세", "90~99세", "100세 이상"],
}


def load_resident_population(file_paths):
    """월별 주민등록인구 파일 여러 개를 하나의 표로 합칩니다.

    결과 열: 기준년월 | 시도 | 시군구 | 20대이하 | 20대 | ... | 60대이상 (인구수)

    파일마다 다른 점과 처리
        - 열 이름 앞에 '2026년01월_' 같은 월 정보가 붙어 있음 → 떼어 내서 모든 달의 열 이름을 통일
        - 기준년월이 데이터 안에 없음 → 파일명(population_202601.csv)에서 6자리 숫자를 읽음
        - 숫자에 쉼표가 있음 → parse_number_with_commas()로 변환
        - '서울특별시 종로구 (1111000000)'처럼 끝에 행정코드가 붙음 → 지우고 시도/시군구로 분리
    """
    monthly_tables = []
    for path in sorted(Path(p) for p in file_paths):
        raw = read_csv_with_encoding_fallback(path)
        raw.columns = [re.sub(r"^\d{4}년\d{2}월_", "", str(name)) for name in raw.columns]

        table = pd.DataFrame(index=raw.index)
        table["기준년월"] = re.search(r"\d{6}", path.stem).group()
        table["행정구역"] = raw["행정구역"].str.replace(r"\s*\(\d+\)$", "", regex=True)
        for age_group, source_columns in RESIDENT_AGE_COLUMNS.items():
            table[age_group] = sum(parse_number_with_commas(raw[f"계_{column}"]) for column in source_columns)
        monthly_tables.append(table)

    population = pd.concat(monthly_tables, ignore_index=True)
    region_words = population["행정구역"].str.split()
    population["시도"] = region_words.str[0]
    population["시군구"] = region_words.str[1:].str.join(" ")

    # 세종시는 하위 시군구가 없어 시군구가 빈칸입니다. 시도 이름을 그대로 시군구로 씁니다.
    is_sejong = (population["시도"] == "세종특별자치시") & (population["시군구"] == "")
    population.loc[is_sejong, "시군구"] = "세종특별자치시"

    # 시군구가 빈칸인 나머지 행은 '서울특별시' 같은 시도 전체 합계라서 제외합니다.
    population = population[population["시군구"] != ""]
    return population[["기준년월", "시도", "시군구"] + AGE_GROUP_ORDER].reset_index(drop=True)


def calculate_resident_age_shares(resident_population, province, months, age_groups, regions=None):
    """주민등록인구의 연령대별 비중(%)을 계산하고 여러 달을 평균합니다.

    Args:
        resident_population: load_resident_population() 결과.
        province: 시도 이름 (예: "서울특별시").
        months: 평균에 사용할 기준년월 목록 (예: ["202601", "202602", "202603"]).
        age_groups: 비중의 분모에 넣을 연령대. 경기처럼 20대 이상만 비교할 때는
            20대이하를 빼고 넘깁니다. 분모가 달라지면 비중이 달라지므로 비교 대상과 맞춰야 합니다.
        regions: 특정 시군구만 쓰고 싶을 때의 목록 (None이면 전체).

    Returns:
        시군구 | 연령대 | 주민등록인구비중
    """
    rows = resident_population[
        (resident_population["시도"] == province)
        & resident_population["기준년월"].astype(str).isin([str(month) for month in months])
    ]
    if regions is not None:
        rows = rows[rows["시군구"].isin(regions)]

    monthly = rows.groupby(["기준년월", "시군구"], as_index=False)[age_groups].sum()
    monthly_total = monthly[age_groups].sum(axis=1)
    for age_group in age_groups:
        monthly[age_group] = monthly[age_group] / monthly_total * 100

    average_share = monthly.groupby("시군구", as_index=False)[age_groups].mean()
    average_share[age_groups] = average_share[age_groups].round(2)   # 원본과 같은 반올림
    return average_share.melt(id_vars="시군구", var_name="연령대", value_name="주민등록인구비중")


# ===========================================================================
# 3. 생활인구 · 유동인구 (외부유입 보정용)
# ===========================================================================

def load_seoul_living_population_shares(path):
    """서울 생활인구(2025)를 자치구별 연령대 비중(%)으로 바꿉니다.

    주의 · 60대이상의 범위
        서울 생활인구 원본은 60~74세까지만 연령 열이 있어, 여기서 60대이상은 '60~74세'입니다.
        주민등록인구의 60대이상(60세 이상 전체)과 범위가 다르다는 점을
        docs/refactoring_notes.md에 기록해 두었습니다. 공모전 결과표 재현을 위해 그대로 둡니다.

    Returns:
        시군구 | 연령대 | 생활인구비중
    """
    raw = read_csv_with_encoding_fallback(path)

    def sum_columns(age_ranges):
        # 남녀 열을 모두 더합니다. 예: male_f20t24_lvpop_co + female_f20t24_lvpop_co
        return sum(
            raw[f"{sex}_f{age_range}_lvpop_co"]
            for sex in ("male", "female")
            for age_range in age_ranges
        )

    living = pd.DataFrame({
        "시군구": raw["adstrd_code_se"].map(SEOUL_DISTRICT_CODE_TO_NAME),
        "20대이하": sum_columns(["0t9", "10t14", "15t19"]),
        "20대": sum_columns(["20t24", "25t29"]),
        "30대": sum_columns(["30t34", "35t39"]),
        "40대": sum_columns(["40t44", "45t49"]),
        "50대": sum_columns(["50t54", "55t59"]),
        "60대이상": sum_columns(["60t64", "65t69", "70t74"]),   # 60~74세만 있음 (위 주의 참고)
    })

    # 2025년 모든 날짜 · 시간대의 값을 더해 자치구별 연령 구성비를 구합니다.
    by_district = living.groupby("시군구", as_index=False)[AGE_GROUP_ORDER].sum()
    total = by_district[AGE_GROUP_ORDER].sum(axis=1)
    for age_group in AGE_GROUP_ORDER:
        by_district[age_group] = (by_district[age_group] / total * 100).round(2)
    return by_district.melt(id_vars="시군구", var_name="연령대", value_name="생활인구비중")


def load_busan_living_exposure(path, year_prefix="2025"):
    """부산 생활인구로 '거주노출비율'을 계산합니다.

    거주노출비율 = 주거인구 / (주거 + 직장 + 방문인구)
        그 지역에서 소비하는 사람 중 실제로 그 지역에 사는 사람의 비율입니다.
        장래인구 추계는 '사는 사람'의 변화만 예측하므로, 이 비율이 낮을수록
        (직장인 · 방문객이 많을수록) 인구감소의 영향을 덜 받는다고 보고 보정합니다.

    Returns:
        시군구 | 연령대 | 거주노출비율
    """
    raw = pd.read_excel(path)
    raw.columns = raw.columns.astype(str).str.strip()
    living = raw[raw["기준년월"].astype(str).str.startswith(year_prefix)].copy()

    # 행정동명 '중구 중앙동' → 구 이름 '중구'
    living["시군구"] = living["행정동명"].astype(str).str.split().str[0]
    living["연령대"] = standardize_age_group_name(living["나이대"])

    population_columns = ["평균주거인구수", "평균직장인구수", "평균방문인구수"]
    # 1) 같은 달 안에서 행정동들을 구 단위로 더하고, 2) 2025년 12개월을 평균합니다.
    monthly = living.groupby(["기준년월", "시군구", "연령대"], as_index=False)[population_columns].sum()
    yearly = monthly.groupby(["시군구", "연령대"], as_index=False)[population_columns].mean()

    total_living = yearly[population_columns].sum(axis=1)
    yearly["거주노출비율"] = yearly["평균주거인구수"] / total_living
    return yearly[["시군구", "연령대", "거주노출비율"]]


# 경기 유동인구 원본의 성별 · 5세 구간 열 → 분석 연령대
# (원본에 10세 미만 열이 없어, 경기 비교에서는 20대 이상만 사용합니다)
GYEONGGI_FLOW_AGE_COLUMNS = {
    "20대이하": ["10", "15"],
    "20대": ["20", "25"],
    "30대": ["30", "35"],
    "40대": ["40", "45"],
    "50대": ["50", "55"],
    "60대이상": ["60", "65", "70"],
}


def load_gyeonggi_floating_population_shares(folder):
    """경기 유동인구 CSV 묶음(시군 × 월별 파일)을 시군별 연령대 비중(%)으로 바꿉니다.

    처리 순서
        1. 폴더 안의 모든 CSV를 읽고 파일명에서 기준년월(202601 등)을 꺼냄
        2. 'CTY_NM'의 첫 단어로 시 단위 이름을 만들고 오타(연천시 → 연천군)를 고침
        3. 시군 × 월로 합산 → 월별 연령 비중 → 3개월 평균

    Returns:
        시군구 | 연령대 | 유동인구비중
    """
    monthly_tables = []
    for path in sorted(Path(folder).rglob("*.csv")):
        raw = read_csv_with_encoding_fallback(path)
        table = pd.DataFrame(index=raw.index)
        table["기준년월"] = re.search(r"20\d{4}", path.stem).group()
        table["시군구"] = raw["CTY_NM"].astype(str).str.split().str[0].map(fix_region_name)
        for age_group, age_starts in GYEONGGI_FLOW_AGE_COLUMNS.items():
            columns = [f"{sex}_{start}_CNT" for sex in ("M", "F") for start in age_starts]
            table[age_group] = raw[columns].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
        monthly_tables.append(table)

    flow = pd.concat(monthly_tables, ignore_index=True)
    monthly = flow.groupby(["기준년월", "시군구"], as_index=False)[AGE_GROUP_ORDER].sum()
    monthly_total = monthly[AGE_GROUP_ORDER].sum(axis=1)
    for age_group in AGE_GROUP_ORDER:
        monthly[age_group] = monthly[age_group] / monthly_total * 100

    average_share = monthly.groupby("시군구", as_index=False)[AGE_GROUP_ORDER].mean()
    average_share[AGE_GROUP_ORDER] = average_share[AGE_GROUP_ORDER].round(2)
    return average_share.melt(id_vars="시군구", var_name="연령대", value_name="유동인구비중")
