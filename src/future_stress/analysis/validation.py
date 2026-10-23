"""검증: 성장군과 비성장군의 Stress 차이가 우연이 아닌지 확인합니다.

검증 질문
    "현재 성장하는 상권이 오히려 미래 소비기반 위험이 더 크다"는 결론이
    1. 통계적으로 의미 있는가?       → Fisher 정확검정, Mann-Whitney U 검정
    2. 규모 기준을 바꿔도 유지되는가? → 상위 20 · 25 · 30% 민감도
    3. 다른 지역에서도 비슷한가?      → 서울 · 부산 · 경기 지역별 비교

원래 노트북과 달라진 점
    원래는 검정표의 숫자(14/0, 74/26)와 결과표의 p-value를 손으로 입력했습니다.
    여기서는 모두 데이터에서 직접 계산하므로, 데이터가 바뀌면 결과도 함께 바뀝니다.

원래 위치: contest/notebooks/03_bc_data.ipynb 셀 192~209, 230~233
"""

import pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu

from .. import config
from .diagnosis import is_strictly_growing, select_analysis_targets, size_cutoff
from .stress import stress_column

STRESS_2035 = stress_column(2035)
STRESS_2040 = stress_column(2040)


def split_by_growth(cases):
    """사례를 성장군과 비성장군으로 나눕니다."""
    growing = is_strictly_growing(cases)
    return cases[growing].copy(), cases[~growing].copy()


def count_risk(cases):
    """위험 지표 두 가지를 셉니다.

    2035 위험      2035 Stress < 0 (미래 소비기반이 이미 약해지는 사례)
    2040 추가악화  2040 Stress < 2035 Stress (시간이 갈수록 더 나빠지는 사례)
    """
    return {
        "risk_2035": int((cases[STRESS_2035] < 0).sum()),
        "worse_by_2040": int((cases[STRESS_2040] < cases[STRESS_2035]).sum()),
    }


def summarize_group(cases, group_name):
    """한 그룹의 위험 비율과 Stress 중앙값을 요약합니다.

    중앙값을 쓰는 이유: Stress에는 극단값이 있어 평균은 몇 건에 끌려가지만,
    중앙값은 '전형적인 사례'의 값을 보여줍니다.
    """
    case_count = len(cases)
    risk = count_risk(cases)

    def percent(count):
        return round(count / case_count * 100, 1) if case_count else None

    return {
        "구분": group_name,
        "사례수": case_count,
        "2035 위험비율(%)": percent(risk["risk_2035"]),
        "2035 스트레스 중앙값": round(cases[STRESS_2035].median(), 2) if case_count else None,
        "2040 추가악화비율(%)": percent(risk["worse_by_2040"]),
        "2040 스트레스 중앙값": round(cases[STRESS_2040].median(), 2) if case_count else None,
    }


def build_growth_comparison_table(growth_cases, non_growth_cases):
    """성장군 vs 비성장군 비교표 (contest/results/growth_vs_nongrowth_validation.csv와 같은 형식)."""
    return pd.DataFrame([
        summarize_group(growth_cases, "현재 성장"),
        summarize_group(non_growth_cases, "비성장"),
    ])


def run_statistical_tests(growth_cases, non_growth_cases):
    """성장군이 비성장군보다 위험한지 통계 검정합니다.

    Fisher 정확검정 (2035 위험 비율)
        2×2 표 [성장: 위험/안정] × [비성장: 위험/안정]에서 성장군의 위험 비율이 더 큰지 검정합니다.
        표본이 14건처럼 작을 때도 정확한 p-value를 주기 때문에 카이제곱 검정 대신 사용했습니다.

    Mann-Whitney U 검정 (Stress 값 분포)
        두 그룹의 Stress 값 자체를 비교합니다. Stress가 정규분포라는 보장이 없어서
        평균을 비교하는 t-검정 대신 순위 기반 검정을 사용했습니다.
        alternative="less": "성장군의 Stress가 더 작다(= 더 위험하다)"를 검정합니다.

    Returns:
        검정 | p-value  (contest/results/statistical_validation.csv와 같은 형식)
    """
    growth_risk = count_risk(growth_cases)["risk_2035"]
    non_growth_risk = count_risk(non_growth_cases)["risk_2035"]
    contingency_table = [
        [growth_risk, len(growth_cases) - growth_risk],
        [non_growth_risk, len(non_growth_cases) - non_growth_risk],
    ]
    _, fisher_p = fisher_exact(contingency_table, alternative="greater")
    _, mann_whitney_p_2035 = mannwhitneyu(growth_cases[STRESS_2035], non_growth_cases[STRESS_2035], alternative="less")
    _, mann_whitney_p_2040 = mannwhitneyu(growth_cases[STRESS_2040], non_growth_cases[STRESS_2040], alternative="less")

    return pd.DataFrame({
        "검정": [
            "2035 위험비율 Fisher exact",
            "2035 스트레스 Mann-Whitney U",
            "2040 스트레스 Mann-Whitney U",
        ],
        "p-value": [round(fisher_p, 4), round(mann_whitney_p_2035, 4), round(mann_whitney_p_2040, 4)],
    })


def run_size_sensitivity(region_result, cutoff_profile, top_percents=None):
    """규모 기준을 바꿔도 '성장 사례는 모두 위험'이라는 결론이 유지되는지 확인합니다.

    Args:
        region_result: 한 지역의 지역 × 업종 결과 (예: 서울).
        cutoff_profile: 규모 기준을 계산할 표. 발표자료는 전국 프로필을 사용했습니다.
        top_percents: 비교할 상위 % 목록 (기본 20, 25, 30).

    Returns:
        contest/results/size_threshold_sensitivity.csv와 같은 형식의 표
    """
    top_percents = top_percents or config.SIZE_SENSITIVITY_TOP_PERCENTS
    rows = []
    for top_percent in top_percents:
        targets = select_analysis_targets(region_result, size_cutoff(cutoff_profile, top_percent))
        growth_cases, _ = split_by_growth(targets)
        case_count = len(growth_cases)
        risk = count_risk(growth_cases)
        rows.append({
            "규모기준": f"상위 {top_percent}%",
            "현재성장사례": case_count,
            "2035 위험사례": risk["risk_2035"],
            "2035 위험비율(%)": round(risk["risk_2035"] / case_count * 100, 1) if case_count else None,
            "2040 추가악화": risk["worse_by_2040"],
            "2040 추가악화비율(%)": round(risk["worse_by_2040"] / case_count * 100, 1) if case_count else None,
        })
    return pd.DataFrame(rows)


def validate_region(region_result, region_name):
    """한 지역 안에서 상위 25% 기준을 새로 잡고 성장군 vs 비성장군을 비교합니다.

    지역마다 상권 규모가 달라서(서울 > 부산), 전국 기준을 쓰면 작은 지역은 사례가 거의 남지 않습니다.
    그래서 지역별 비교에서는 '그 지역 안에서의 상위 25%'를 기준으로 씁니다.

    Returns:
        (summary, analysis_targets)
        summary:          지역 요약 한 줄 (사례 수, 위험 비율, 중앙값, p-value)
        analysis_targets: 그 지역의 분석 대상 표 (4유형 분류에 사용)
    """
    targets = select_analysis_targets(region_result, size_cutoff(region_result))
    growth_cases, non_growth_cases = split_by_growth(targets)
    tests = run_statistical_tests(growth_cases, non_growth_cases)["p-value"].tolist()

    def risk_percent(cases):
        return round(count_risk(cases)["risk_2035"] / len(cases) * 100, 1) if len(cases) else None

    summary = {
        "지역": region_name,
        "전체 사례": len(targets),
        "성장군 n": len(growth_cases),
        "비성장군 n": len(non_growth_cases),
        "성장군 2035 위험비율(%)": risk_percent(growth_cases),
        "비성장군 2035 위험비율(%)": risk_percent(non_growth_cases),
        "성장군 2035 중앙값": round(growth_cases[STRESS_2035].median(), 2),
        "비성장군 2035 중앙값": round(non_growth_cases[STRESS_2035].median(), 2),
        "성장군 2040 중앙값": round(growth_cases[STRESS_2040].median(), 2),
        "비성장군 2040 중앙값": round(non_growth_cases[STRESS_2040].median(), 2),
        "Fisher p": tests[0],
        "2035 MW p": tests[1],
        "2040 MW p": tests[2],
    }
    return summary, targets


def build_stress_case_table(growth_cases):
    """현재 성장 사례 표 (contest/results/stress_test_14_cases_table.csv와 같은 형식)."""
    table = growth_cases.copy()
    table["2040 추가악화폭"] = (table[STRESS_2040] - table[STRESS_2035]).round(2)
    table[STRESS_2035] = table[STRESS_2035].round(2)
    table[STRESS_2040] = table[STRESS_2040].round(2)
    return (
        table[["시군구", "업종명", "연령대", "월평균증감률", "1월대비6월증감률", STRESS_2035, STRESS_2040, "2040 추가악화폭"]]
        .rename(columns={
            "연령대": "현재 핵심연령대",
            "월평균증감률": "월평균 성장률",
            "1월대비6월증감률": "1→6월 증감률",
            STRESS_2035: "2035 스트레스",
            STRESS_2040: "2040 스트레스",
        })
        .sort_values("2040 스트레스")
        .reset_index(drop=True)
    )
