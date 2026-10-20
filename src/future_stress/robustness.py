"""검증: 외부유입(생활 · 유동인구)을 반영해도 진단이 유지되는지 확인합니다.

왜 필요한가요?
    장래인구는 '그 지역에 사는 사람'의 변화입니다. 그런데 상권에는 출퇴근 · 방문으로
    다른 지역 사람도 와서 소비합니다. 거주인구만으로 계산한 Stress가 과장되지 않았는지
    생활 · 유동인구로 보정해 보고, 위험/안정 판정과 위험 순위가 그대로인지 확인합니다.

지역별로 쓸 수 있는 데이터가 달라서 보정 방법이 두 가지입니다.

    서울 · 경기  재가중 방식   reweight_stress_by_external_population()
        보정계수 = (생활/유동인구 연령 비중) / (주민등록인구 연령 비중)
        → 소비비중에 곱한 뒤 합이 1이 되도록 다시 나눔 → Stress 재계산
        "실제로 그 지역에 와 있는 연령 구성"에 맞게 소비비중을 조정하는 방식입니다.

    부산         거주노출 방식  adjust_stress_by_resident_exposure()
        보정 Stress = Σ 소비비중 × 인구증감률 × 거주노출비율
        생활인구 중 '주거인구' 비율만큼만 인구변화의 영향을 받는다고 보는 방식입니다.

    두 방식의 결과 수치는 서로 직접 비교하지 않고, 각 지역 안에서 '보정 전 vs 후'만 비교합니다.

원래 위치: notebooks/01_population.ipynb 셀 104~158, notebooks/03_bc_data.ipynb 셀 250~254
"""

import pandas as pd
from scipy.stats import spearmanr

from .stress import stress_column


def classify_risk(stress):
    """Stress 부호로 위험/안정을 나눕니다. 0 이상이면 안정입니다."""
    return (stress >= 0).map({True: "안정", False: "위험"})


def renormalize_shares(shares, share_column, age_groups):
    """일부 연령대만 남기고 비중의 합이 다시 100이 되도록 맞춥니다.

    예: 경기 유동인구는 10세 미만 자료가 없어 20대 이상만 비교합니다.
        20대 이상 비중의 합이 85%라면, 각 비중을 85로 나눠 100% 기준으로 바꿉니다.
    """
    kept = shares[shares["연령대"].isin(age_groups)].copy()
    kept[share_column] = kept[share_column] / kept.groupby("시군구")[share_column].transform("sum") * 100
    kept[share_column] = kept[share_column].round(2)   # 원본과 같은 반올림
    return kept


def reweight_stress_by_external_population(
    age_structure, external_shares, external_share_column, resident_shares, future_population, age_groups, year=2040
):
    """[서울 · 경기 방식] 생활/유동인구 연령구성으로 소비비중을 재가중해 Stress를 다시 계산합니다.

    Args:
        age_structure: 한 시도의 연령별 소비구조 (시군구 | 업종코드 | 업종명 | 연령대 | 이용금액).
        external_shares: 생활/유동인구 비중 (시군구 | 연령대 | <external_share_column>).
        external_share_column: '생활인구비중' 또는 '유동인구비중'.
        resident_shares: 주민등록인구 비중 (시군구 | 연령대 | 주민등록인구비중).
        future_population: 장래인구 (시군구 | 연령대 | 2040 증감률).
        age_groups: 비교에 사용할 연령대 (서울 6개, 경기 20대 이상 5개).
        year: 비교할 Stress 연도.

    Returns:
        시군구 | 업종코드 | 업종명 | 기존Stress | 보정Stress | Stress변화 | 기존분류 | 보정분류 | 분류일치
    """
    case_keys = ["시군구", "업종코드", "업종명"]

    # 1) 비교할 연령대 안에서 소비비중을 다시 계산합니다 (비율, 합 = 1).
    structure = (
        age_structure[age_structure["연령대"].isin(age_groups)]
        .groupby(case_keys + ["연령대"], as_index=False)["이용금액"].sum()
    )
    structure["소비비중"] = structure["이용금액"] / structure.groupby(case_keys)["이용금액"].transform("sum")

    # 2) 보정계수: 외부유입까지 포함한 실제 연령 구성이 거주인구보다 얼마나 많거나 적은가
    coefficient = external_shares.merge(resident_shares, on=["시군구", "연령대"], how="inner")
    coefficient["보정계수"] = (coefficient[external_share_column] / coefficient["주민등록인구비중"]).round(3)

    # 보정 자료가 있는 지역만 비교합니다. (경기 유동인구는 31개 시군 중 일부만 제공)
    # 이 필터가 없으면 자료가 없는 지역의 보정 Stress가 0으로 계산되어 결과가 왜곡됩니다.
    structure = structure[structure["시군구"].isin(coefficient["시군구"])]

    merged = (
        structure
        .merge(coefficient[["시군구", "연령대", "보정계수"]], on=["시군구", "연령대"], how="left")
        .merge(future_population[["시군구", "연령대", f"{year} 증감률"]], on=["시군구", "연령대"], how="left")
    )

    # 3) 소비비중 × 보정계수 → 지역 × 업종 안에서 합이 1이 되도록 다시 나눔
    raw_weight = merged["소비비중"] * merged["보정계수"]
    merged["보정소비비중"] = raw_weight / raw_weight.groupby([merged[k] for k in case_keys]).transform("sum")

    # 4) 기존 / 보정 Stress
    merged["기존Stress_연령"] = merged["소비비중"] * merged[f"{year} 증감률"]
    merged["보정Stress_연령"] = merged["보정소비비중"] * merged[f"{year} 증감률"]
    comparison = merged.groupby(case_keys, as_index=False).agg(
        기존Stress=("기존Stress_연령", "sum"),
        보정Stress=("보정Stress_연령", "sum"),
    )
    return add_classification_columns(comparison)


def adjust_stress_by_resident_exposure(age_stress, resident_exposure, years=(2035, 2040)):
    """[부산 방식] 거주노출비율을 곱해 '생활인구 보정 Stress'를 계산합니다.

    Args:
        age_stress: stress.build_region_result()가 돌려준 연령대별 상세 표 (부산).
        resident_exposure: population.load_busan_living_exposure() 결과.

    Returns:
        시도 | 시군구 | 업종코드 | 업종명 | 2035 생활인구보정효과 | 2040 생활인구보정효과
    """
    merged = age_stress.merge(resident_exposure, on=["시군구", "연령대"], how="left")
    share = merged["이용금액비중"] / 100
    adjusted_columns = []
    for year in years:
        column = f"{year} 생활인구보정효과"
        merged[column] = share * merged[f"{year} 증감률"] * merged["거주노출비율"]
        adjusted_columns.append(column)
    return merged.groupby(["시도", "시군구", "업종코드", "업종명"], as_index=False)[adjusted_columns].sum()


def add_classification_columns(comparison, before_column="기존Stress", after_column="보정Stress"):
    """보정 전후의 위험/안정 분류와 일치 여부를 추가합니다."""
    result = comparison.copy()
    result["Stress변화"] = result[after_column] - result[before_column]
    result["기존분류"] = classify_risk(result[before_column])
    result["보정분류"] = classify_risk(result[after_column])
    result["분류일치"] = result["기존분류"] == result["보정분류"]
    return result


def summarize_robustness(comparison, region_name, note="", before_column="기존Stress", after_column="보정Stress"):
    """보정 전후 결과를 한 줄로 요약합니다.

    분류일치율   위험/안정 판정이 그대로인 사례의 비율. 높을수록 진단이 외부유입에 흔들리지 않음.
    Spearman ρ  보정 전후 위험 순위의 상관. 1에 가까울수록 '어디가 더 위험한가'의 순서가 유지됨.
                값의 크기가 아니라 순위를 비교하므로, 보정 방식이 달라도 해석이 같습니다.

    Returns:
        results/final_3region_robustness.csv의 한 행과 같은 형식의 dict
    """
    classified = add_classification_columns(comparison, before_column, after_column)
    rho, _ = spearmanr(classified[before_column], classified[after_column])
    return {
        "지역": region_name,
        "검증사례수": len(classified),
        "분류일치율": round(classified["분류일치"].mean() * 100, 1),
        "변경건수": int((~classified["분류일치"]).sum()),
        "Spearman_rho": round(rho, 3),
        "비고": note,
    }


def build_busan_comparison(busan_targets, busan_adjusted, year=2040):
    """부산 분석 대상에 보정 결과를 붙여 '보정 전 vs 후' 비교표를 만듭니다."""
    merged = busan_targets.merge(busan_adjusted, on=["시도", "시군구", "업종코드", "업종명"], how="left")
    return pd.DataFrame({
        "시군구": merged["시군구"],
        "업종코드": merged["업종코드"],
        "업종명": merged["업종명"],
        "기존Stress": merged[stress_column(year)],
        "보정Stress": merged[f"{year} 생활인구보정효과"],
    })
