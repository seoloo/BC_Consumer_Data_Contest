"""전략 도출: 위험한 상권이 '다음에 잡아야 할 고객'을 찾습니다.

두 가지 접근
    1. 방어형 고객 찾기          build_defense_strategy()
       → 착시성장 사례마다, 늘릴 여력이 있고 미래 인구도 유리한 연령대를 하나 고릅니다.
    2. 고객 구성 재조정 시뮬레이션  optimize_mix_for_max_mitigation(), optimize_mix_for_min_change()
       → 연령대 비중을 조금씩 옮겼을 때 Stress가 얼마나 줄어드는지 최적화로 계산합니다.

자주 나오는 용어
    확장여력       같은 업종의 다른 지역에서 이 연령대 비중의 75분위수 - 지금 비중 (%p)
                  "다른 곳에서는 이 연령대가 이만큼은 오는데, 여기는 아직 덜 온다"는 뜻입니다.
                  현실적으로 끌어올 수 있는 상한을 같은 업종의 실제 관측값으로 잡기 위해서입니다.
    인구상대우위   이 연령대의 미래 인구증감률 - 현재 핵심 연령대의 인구증감률 (%p)
                  양수면 핵심 고객보다 미래 인구 전망이 좋다는 뜻입니다.
    방어개선잠재력  확장여력 × 인구상대우위 / 100
                  그 연령대를 확장여력만큼 늘렸을 때 Stress가 개선되는 크기입니다.

원래 위치: notebooks/03_bc_data.ipynb 셀 70~134, 172~179, 257~273
"""

import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize

from . import config
from .diagnosis import is_strictly_growing
from .stress import stress_column

CASE_KEYS = ["시군구", "업종코드", "업종명"]


# ===========================================================================
# 1. 방어형 고객 찾기
# ===========================================================================

def find_risk_cases(analysis_targets, base_year=2035, long_term_year=2040):
    """전략이 필요한 사례: 현재 성장 중인데 base_year와 long_term_year 모두 Stress가 음수."""
    is_risk = (
        is_strictly_growing(analysis_targets)
        & (analysis_targets[stress_column(long_term_year)] < 0)
        & (analysis_targets[stress_column(base_year)] < 0)
    )
    return analysis_targets[is_risk]


def classify_candidate_type(candidates, base_year=2035):
    """후보 연령대의 성격을 나눕니다.

    성장·방어형  그 연령대 인구 자체가 늘어남 → 가장 좋은 방어 후보
    상대안정형   인구는 줄지만 핵심 고객보다는 덜 줄어듦 → 차선의 방어 후보
    시장확장형   핵심 고객보다 더 줄어듦 → 방어 효과는 없지만 지금 매출을 넓히는 용도
    """
    return np.select(
        [candidates[f"{base_year} 증감률"] > 0, candidates["인구상대우위"] > 0],
        ["성장·방어형", "상대안정형"],
        default="시장확장형",
    )


def build_defense_strategy(analysis_targets, age_stress, base_year=2035, long_term_year=2040):
    """착시성장 사례별 방어형 · 확장형 고객과 장기(2040) 효과를 계산합니다.

    Args:
        analysis_targets: 한 지역의 분석 대상 (Stress 포함).
        age_stress: 같은 지역의 연령대별 상세 표 (이용금액비중, 연도별 증감률 포함).

    Returns:
        사례 한 건당 한 행: 현재핵심연령대, 방어형고객, 방어형유형, 확장형고객,
        방어전략상태, 전환후_2040순인구효과, 2040위험완화율 등
    """
    base_rate, long_rate = f"{base_year} 증감률", f"{long_term_year} 증감률"
    base_stress, long_stress = stress_column(base_year), stress_column(long_term_year)

    risk_cases = find_risk_cases(analysis_targets, base_year, long_term_year)[CASE_KEYS + ["연령대"]]
    risk_cases = risk_cases.rename(columns={"연령대": "현재핵심연령대"})

    # 분석 대상(규모 상위 + 6개월 완전)의 연령별 구조만 사용해 벤치마크를 만듭니다.
    target_ages = age_stress.merge(analysis_targets[CASE_KEYS], on=CASE_KEYS, how="inner")
    benchmark = (
        target_ages.groupby(["업종코드", "업종명", "연령대"])["이용금액비중"]
        .quantile(config.BENCHMARK_QUANTILE)
        .reset_index(name="동일업종_상위25%비중")
    )
    # 시군구 × 연령대별 미래 인구증감률 (핵심 연령대와 후보 연령대를 비교할 때 사용)
    population_rates = age_stress[["시군구", "연령대", base_rate, long_rate]].drop_duplicates(["시군구", "연령대"])

    # 1) 후보 풀: 위험 사례의 모든 연령대
    pool = (
        target_ages.merge(risk_cases, on=CASE_KEYS, how="inner")
        .merge(benchmark, on=["업종코드", "업종명", "연령대"], how="left")
        .merge(
            population_rates[["시군구", "연령대", base_rate]].rename(
                columns={"연령대": "현재핵심연령대", base_rate: "핵심연령_증감률"}
            ),
            on=["시군구", "현재핵심연령대"],
            how="left",
        )
    )
    pool["확장여력"] = (pool["동일업종_상위25%비중"] - pool["이용금액비중"]).round(1)
    pool["인구상대우위"] = (pool[base_rate] - pool["핵심연령_증감률"]).round(1)

    # 2) 핵심 연령대가 아니고, 늘릴 여력이 있는 연령대만 후보로 남깁니다.
    candidates = pool[(pool["연령대"] != pool["현재핵심연령대"]) & (pool["확장여력"] > 0)].copy()
    candidates["후보유형"] = classify_candidate_type(candidates, base_year)
    candidates["방어개선잠재력"] = (candidates["확장여력"] * candidates["인구상대우위"].clip(lower=0) / 100).round(2)

    # 3) 사례마다 방어 효과가 가장 큰 후보 1개, 매출 확장 여력이 가장 큰 후보 1개
    defense_pool = candidates[candidates["후보유형"].isin(["성장·방어형", "상대안정형"])]
    best_defense = defense_pool.loc[defense_pool.groupby(["시군구", "업종코드"])["방어개선잠재력"].idxmax()]
    best_defense = best_defense[CASE_KEYS + ["연령대", "후보유형", "확장여력", "인구상대우위", "방어개선잠재력"]].rename(
        columns={"연령대": "방어형고객", "후보유형": "방어형유형", "확장여력": "방어형확장여력"}
    )
    expansion_pool = candidates[candidates["후보유형"] == "시장확장형"]
    best_expansion = expansion_pool.loc[expansion_pool.groupby(["시군구", "업종코드"])["확장여력"].idxmax()]
    best_expansion = best_expansion[CASE_KEYS + ["연령대", "확장여력"]].rename(
        columns={"연령대": "확장형고객", "확장여력": "확장형확장여력"}
    )

    strategy = (
        risk_cases
        .merge(best_defense, on=CASE_KEYS, how="left")
        .merge(best_expansion, on=CASE_KEYS, how="left")
        .merge(analysis_targets[CASE_KEYS + [base_stress, long_stress]], on=CASE_KEYS, how="left")
    )
    return add_long_term_check(strategy, population_rates, long_rate, long_stress)


def add_long_term_check(strategy, population_rates, long_rate, long_stress):
    """2035 기준으로 고른 방어형 고객이 2040에도 유효한지 확인합니다.

    2035에는 핵심 고객보다 인구 전망이 좋아도, 2040에는 역전될 수 있습니다.
    그래서 2040 인구증감률로 상대우위를 다시 계산하고, 전환 후 Stress를 추정합니다.
    """
    result = (
        strategy
        .merge(
            population_rates[["시군구", "연령대", long_rate]].rename(
                columns={"연령대": "현재핵심연령대", long_rate: "핵심고객_2040증감률"}),
            on=["시군구", "현재핵심연령대"], how="left")
        .merge(
            population_rates[["시군구", "연령대", long_rate]].rename(
                columns={"연령대": "방어형고객", long_rate: "방어형고객_2040증감률"}),
            on=["시군구", "방어형고객"], how="left")
    )
    result["2040방어상대우위"] = (result["방어형고객_2040증감률"] - result["핵심고객_2040증감률"]).round(1)
    result["방어전략상태"] = np.select(
        [result["방어형고객"].isna(), result["2040방어상대우위"] > 0],
        ["방어형 후보 없음", "장기유효"],
        default="장기재검토",
    )
    # 확장여력만큼 방어형 고객을 늘렸을 때의 2040 Stress 개선폭과 위험완화율
    result["2040_최대개선효과"] = (result["방어형확장여력"] * result["2040방어상대우위"] / 100).round(2)
    result["전환후_2040순인구효과"] = (result[long_stress] + result["2040_최대개선효과"]).round(2)
    result["2040위험완화율"] = (
        (result["전환후_2040순인구효과"] - result[long_stress]) / result[long_stress].abs() * 100
    ).round(1)
    return result


def pick_representative_cases(growth_cases, count=3, year=2040):
    """발표용 대표 사례를 고릅니다.

    위험이 큰 순서로 보면서, 지역과 업종이 겹치지 않는 사례만 고릅니다.
    같은 구나 같은 업종만 연달아 나오면 사례가 다양한 상황을 보여주지 못하기 때문입니다.
    """
    selected, used_industries, used_regions = [], set(), set()
    for _, row in growth_cases.sort_values(stress_column(year)).iterrows():
        if row["업종명"] in used_industries or row["시군구"] in used_regions:
            continue
        selected.append(row)
        used_industries.add(row["업종명"])
        used_regions.add(row["시군구"])
        if len(selected) == count:
            break
    return pd.DataFrame(selected)


def describe_case(defense_status, defense_type):
    """대표 사례의 진단 문구를 정합니다."""
    if pd.isna(defense_status):
        # 2035 Stress가 음수가 아니라 방어 전략 계산 대상에서 빠진 사례
        return "전략 대상 아님"
    if defense_status == "방어형 후보 없음":
        return "구조적 취약형"
    if defense_type == "성장·방어형":
        return "성장고객 전환형"
    if defense_type == "상대안정형":
        return "상대안정 고객 전환형"
    return "전환전략 검토형"


def build_representative_case_table(representative_cases, defense_strategy, year=2040):
    """대표 사례 표 (results/representative_3_cases_table.csv와 같은 형식)."""
    table = representative_cases[["시군구", "업종명", "연령대", stress_column(year)]].rename(
        columns={"연령대": "현재핵심연령대"}
    ).merge(
        defense_strategy[["시군구", "업종명", "방어형고객", "방어형유형", "방어전략상태",
                          "전환후_2040순인구효과", "2040위험완화율"]],
        on=["시군구", "업종명"], how="left",
    )
    table["진단"] = [describe_case(s, t) for s, t in zip(table["방어전략상태"], table["방어형유형"])]
    return pd.DataFrame({
        "지역": table["시군구"],
        "업종": table["업종명"],
        "현재 핵심고객": table["현재핵심연령대"],
        "진단": table["진단"],
        "방어형 고객": table["방어형고객"].fillna("후보 없음"),
        "전환 전": table[stress_column(year)].round(2),
        "전환 후": table["전환후_2040순인구효과"].round(2).astype(object).where(table["전환후_2040순인구효과"].notna(), "-"),
        "위험완화율(%)": table["2040위험완화율"].round(1).astype(object).where(table["2040위험완화율"].notna(), "-"),
    })


# ===========================================================================
# 2. 고객 구성 재조정 시뮬레이션 (최적화)
# ===========================================================================

def build_age_benchmark_range(age_pool):
    """광역지역 × 업종 × 연령대별 이용금액비중의 25 · 75분위수를 구합니다.

    재조정할 때 비중을 이 범위 안에서만 움직이게 해서,
    '현실에서 관측된 적 없는 고객 구성'을 추천하지 않도록 합니다.
    """
    return (
        age_pool.groupby(["광역지역", "업종코드", "업종명", "연령대"])["이용금액비중"]
        .quantile([0.25, 0.75])
        .unstack()
        .reset_index()
        .rename(columns={0.25: "동일업종_Q25", 0.75: "동일업종_Q75"})
    )


def stress_of_mix(age_share, population_change):
    """연령 비중(%)과 인구증감률(%)로 Stress를 계산합니다. stress 모듈의 공식과 같습니다."""
    return float(np.sum(age_share * population_change / 100))


def optimize_mix_for_max_mitigation(current_share, population_change, lower, upper, max_shift_pp=None):
    """[선형계획] 고객 비중을 최대 max_shift_pp만 옮겨서 Stress를 가장 많이 줄입니다.

    문제 정의
        변수      x = 새 연령 비중, d = |x - 현재 비중|
        목표      Σ x × 인구증감률 을 최대화 (= Stress를 0 쪽으로)
        제약      Σ x = 100,  lower ≤ x ≤ upper,  Σ d ≤ 2 × max_shift_pp
    이동량에 2를 곱하는 이유: 한 연령대에서 5%p를 빼서 다른 연령대에 5%p를 더하면
    절대 변화의 합은 10이 되므로, '옮긴 양'은 절대 변화 합의 절반입니다.
    절댓값 |x - 현재|는 선형식이 아니라서 d라는 보조 변수와 두 개의 부등식으로 바꿔 씁니다.

    Returns:
        새 비중 배열 (실패하면 None)
    """
    max_shift_pp = max_shift_pp or config.MAX_CUSTOMER_SHIFT_PP
    age_count = len(current_share)
    objective = np.concatenate([-population_change / 100, np.zeros(age_count)])   # linprog는 최소화라 부호 반전

    inequality_rows, inequality_limits = [], []
    for i in range(age_count):
        upper_row = np.zeros(2 * age_count)    #  x_i - d_i ≤ 현재_i
        upper_row[i], upper_row[age_count + i] = 1, -1
        lower_row = np.zeros(2 * age_count)    # -x_i - d_i ≤ -현재_i
        lower_row[i], lower_row[age_count + i] = -1, -1
        inequality_rows += [upper_row, lower_row]
        inequality_limits += [current_share[i], -current_share[i]]
    shift_row = np.zeros(2 * age_count)
    shift_row[age_count:] = 1                   # Σ d ≤ 2 × 최대 이동량
    inequality_rows.append(shift_row)
    inequality_limits.append(2 * max_shift_pp)

    equality_row = np.zeros((1, 2 * age_count))
    equality_row[0, :age_count] = 1             # Σ x = 100

    result = linprog(
        objective,
        A_ub=np.array(inequality_rows), b_ub=np.array(inequality_limits),
        A_eq=equality_row, b_eq=[100],
        bounds=list(zip(lower, upper)) + [(0, None)] * age_count,
        method="highs",
    )
    return result.x[:age_count] if result.success else None


def optimize_mix_for_min_change(current_share, population_change, lower, upper, target_mitigation_pct=None):
    """[비선형 최적화 · SLSQP] 목표 위험완화를 달성하는 '가장 작은 변화'를 찾습니다.

    선형계획은 효과가 가장 큰 한 연령대에 몰아주는 답을 내기 쉽습니다.
    현실의 고객 구성은 한 번에 한 연령대로 쏠리기 어려우므로,
    변화량의 제곱합을 최소화해서 여러 연령대에 나눠 움직이는 답을 찾습니다.

    제약
        Σ x = 100
        새 Stress ≥ 목표 Stress (현재 Stress에서 target_mitigation_pct%만큼 0 쪽으로)
        새 연령 집중도(HHI) ≤ 현재 HHI (특정 연령 의존이 더 심해지지 않게)
    """
    target_mitigation_pct = target_mitigation_pct or config.TARGET_MITIGATION_PERCENT
    current_stress = stress_of_mix(current_share, population_change)
    current_hhi = np.sum((current_share / 100) ** 2)
    target_stress = current_stress + abs(current_stress) * target_mitigation_pct / 100

    result = minimize(
        lambda x: np.sum((x - current_share) ** 2),
        x0=current_share,
        method="SLSQP",
        bounds=list(zip(lower, upper)),
        constraints=[
            {"type": "eq", "fun": lambda x: np.sum(x) - 100},
            {"type": "ineq", "fun": lambda x: stress_of_mix(x, population_change) - target_stress},
            {"type": "ineq", "fun": lambda x: current_hhi - np.sum((x / 100) ** 2)},
        ],
        options={"maxiter": 2000, "ftol": 1e-9},
    )
    # SLSQP는 답을 찾고도 마지막 탐색 단계의 수치 오차 때문에 success=False를 돌려주는 경우가 있습니다.
    # (원래 노트북은 이때 결과를 버렸습니다.) 그래서 success 대신 제약을 직접 확인해 판단합니다.
    new_share = result.x
    tolerance = 1e-6
    satisfies_constraints = (
        abs(np.sum(new_share) - 100) <= tolerance
        and stress_of_mix(new_share, population_change) >= target_stress - tolerance
        and np.sum((new_share / 100) ** 2) <= current_hhi + tolerance
        and np.all(new_share >= np.asarray(lower) - tolerance)
        and np.all(new_share <= np.asarray(upper) + tolerance)
    )
    return new_share if satisfies_constraints else None


def prepare_case_mix(age_pool, benchmark_range, region, area, industry_code, year=2040):
    """한 사례의 현재 연령 비중, 인구증감률, 비중 조정 범위를 배열로 준비합니다."""
    rows = age_pool[
        (age_pool["광역지역"] == region) & (age_pool["지역명"] == area) & (age_pool["업종코드"] == industry_code)
    ][["연령대", "이용금액비중", f"{year} 증감률"]].merge(
        benchmark_range[(benchmark_range["광역지역"] == region) & (benchmark_range["업종코드"] == industry_code)][
            ["연령대", "동일업종_Q25", "동일업종_Q75"]
        ],
        on="연령대", how="left",
    )
    if rows.empty:
        return None
    # 반올림 때문에 비중 합이 정확히 100이 아닐 수 있어 100으로 다시 맞춥니다.
    current = (rows["이용금액비중"] / rows["이용금액비중"].sum() * 100).to_numpy()
    return {
        "ages": rows["연령대"].astype(str).to_numpy(),
        "current": current,
        "change": rows[f"{year} 증감률"].to_numpy(),
        # 지금 값이 이미 범위 밖이면 지금 값까지는 허용합니다 (억지로 범위 안으로 끌고 오지 않음).
        "lower": np.minimum(current, rows["동일업종_Q25"].to_numpy()),
        "upper": np.maximum(current, rows["동일업종_Q75"].to_numpy()),
    }


def run_rebalancing(age_pool, cases, max_shift_pp=None, target_mitigation_pct=None):
    """착시성장 사례 전체에 두 가지 재조정 시뮬레이션을 적용합니다.

    Args:
        age_pool: 3개 지역 연령별 상세 표 (광역지역, 지역명, 업종코드, 연령대, 이용금액비중, 2040 증감률).
        cases: 광역지역 | 지역명 | 업종코드 | 업종명 (보통 착시성장형 사례).

    Returns:
        사례 한 건당 한 행: 최대감소/증가 연령, 이동량, 전환 전후 Stress, 위험완화율, HHI 변화
    """
    benchmark_range = build_age_benchmark_range(age_pool)
    rows = []
    for _, case in cases.iterrows():
        mix = prepare_case_mix(age_pool, benchmark_range, case["광역지역"], case["지역명"], case["업종코드"])
        if mix is None:
            continue
        before = stress_of_mix(mix["current"], mix["change"])
        row = {"광역지역": case["광역지역"], "지역명": case["지역명"], "업종명": case["업종명"], "2040_전환전": round(before, 2)}

        linear = optimize_mix_for_max_mitigation(mix["current"], mix["change"], mix["lower"], mix["upper"], max_shift_pp)
        if linear is not None:
            change = linear - mix["current"]
            after = stress_of_mix(linear, mix["change"])
            row.update({
                "최대증가연령": mix["ages"][np.argmax(change)],
                "최대감소연령": mix["ages"][np.argmin(change)],
                "이동량(%p)": round(np.abs(change).sum() / 2, 2),
                "2040_전환후": round(after, 2),
                "위험완화율(%)": round((after - before) / abs(before) * 100, 1),
            })

        diversified = optimize_mix_for_min_change(
            mix["current"], mix["change"], mix["lower"], mix["upper"], target_mitigation_pct
        )
        if diversified is not None:
            change = diversified - mix["current"]
            row.update({
                "다변화_증가연령": ", ".join(mix["ages"][change > 0.05]),
                "다변화_이동량(%p)": round(np.abs(change).sum() / 2, 2),
                "HHI전": round(np.sum((mix["current"] / 100) ** 2), 4),
                "HHI후": round(np.sum((diversified / 100) ** 2), 4),
            })
        rows.append(row)
    return pd.DataFrame(rows)
