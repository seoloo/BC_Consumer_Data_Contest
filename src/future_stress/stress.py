"""Future Stress 계산 (흐름도 STEP 4 · 프로젝트의 핵심 지표).

    Future Stress(연도) = Σ ( 연령대별 이용금액 비중 × 그 연령대의 인구증감률 )

읽는 법
    - 지금 매출의 대부분을 만드는 연령대의 인구가 줄어들수록 값이 음수로 커집니다.
    - 음수 = 현재 고객 구성이 미래 인구감소에 노출되어 있음 (취약)
    - 0 이상 = 현재 고객 구성이 미래에도 유지되거나 늘어나는 인구에 기대고 있음 (안정)
    - 매출 예측값이 아니라 "구조적 위험의 상대 비교"용 지표입니다.

계산 예시 (이해를 돕기 위한 가상의 숫자)
    30대 비중 40% × 30대 인구 -25%   = -10.0
    40대 비중 25% × 40대 인구 -20%   =  -5.0
    60대이상 비중 10% × 인구 +30%    =  +3.0
    ... 6개 연령대를 모두 더한 값이 그 지역 × 업종의 Future Stress

노트북에서는 컬럼 이름이 '순인구효과'였습니다. 발표 결과 CSV와 맞추기 위해 같은 이름을 씁니다.

원래 위치: notebooks/03_bc_data.ipynb 셀 62~63, 192, 204, 211~212, 224~225, 232
"""

from . import config
from .card_spending import CASE_KEYS


def stress_column(year):
    """연도별 Stress 열 이름. 예: stress_column(2040) → '2040 순인구효과'"""
    return f"{year} 순인구효과"


def attach_population_change(age_structure, future_population, province):
    """연령별 소비구조에 같은 시군구 · 연령대의 미래 인구증감률을 붙입니다.

    Args:
        age_structure: card_spending.build_age_spending_structure() 결과.
        future_population: population 모듈의 장래인구 표 (시군구 | 연령대 | 2035 증감률 ...).
        province: 시도 이름. 장래인구 파일이 시도별로 따로 있어서 같은 시도만 골라 붙입니다.

    Returns:
        시도의 연령별 소비구조 + '2030/2035/2040 증감률' 열
    """
    change_columns = [f"{year} 증감률" for year in config.POPULATION_TARGET_YEARS]
    province_structure = age_structure[age_structure["시도"] == province]
    return province_structure.merge(
        future_population[["시군구", "연령대"] + change_columns],
        on=["시군구", "연령대"],
        how="left",
    )


def add_age_stress_contributions(age_structure_with_change, years=None):
    """연령대 한 줄마다 Stress 기여도(비중 × 증감률)를 계산합니다.

    이용금액비중은 %(예: 40.0)라서 100으로 나눠 비율(0.4)로 바꾼 뒤 곱합니다.
    그래서 Stress의 단위는 '인구증감률(%)과 같은 단위'가 됩니다.
    """
    years = years or config.STRESS_YEARS
    result = age_structure_with_change.copy()
    share = result["이용금액비중"] / 100
    for year in years:
        result[stress_column(year)] = share * result[f"{year} 증감률"]
    return result


def sum_stress_by_case(age_stress, years=None):
    """연령대별 기여도를 지역 × 업종 단위로 더해 최종 Future Stress를 만듭니다."""
    years = years or config.STRESS_YEARS
    return age_stress.groupby(CASE_KEYS, as_index=False)[[stress_column(y) for y in years]].sum()


def build_region_result(profile, age_structure, future_population, province):
    """한 시도의 '지역 × 업종 프로필 + Future Stress' 표를 만듭니다.

    이후 단계(분석 대상 선정, 4유형 분류, 검증)는 모두 이 표에서 시작합니다.

    Returns:
        (region_result, age_stress)
        region_result: 지역 × 업종 한 건당 한 행 (프로필 + 2035/2040 Stress)
        age_stress:    연령대별 기여도까지 남긴 상세 표 (전략 단계에서 사용)
    """
    age_stress = add_age_stress_contributions(
        attach_population_change(age_structure, future_population, province)
    )
    region_result = profile[profile["시도"] == province].merge(
        sum_stress_by_case(age_stress), on=CASE_KEYS, how="left"
    )
    return region_result, age_stress
