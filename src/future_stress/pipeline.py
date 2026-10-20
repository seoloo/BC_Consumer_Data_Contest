"""전체 분석을 순서대로 실행하고 결과 CSV를 저장합니다.

실행 방법 (저장소 루트에서)
    .venv/Scripts/python -m future_stress.pipeline              # 결과를 output/ 에 저장
    .venv/Scripts/python -m future_stress.pipeline --compare    # 저장 후 results/ 의 발표 수치와 비교

필요한 원본 파일 (data/raw/, 저장소에는 올리지 않음 · data/README.md 참고)
    RAW_FILES 딕셔너리에 이름을 모아 두었습니다. 파일명이 다르면 여기만 고치면 됩니다.

흐름도(docs/diagrams/03_pipeline.png)와의 대응
    run_pipeline() 안의 주석 [STEP 1] ~ [전략]이 흐름도의 단계 이름과 같습니다.
"""

import argparse
from pathlib import Path

import pandas as pd

from . import config
from .age_groups import ADULT_AGE_GROUPS, AGE_GROUP_ORDER
from .card_spending import (
    build_age_spending_structure,
    build_region_industry_profile,
    clean_card_spending,
    load_card_spending,
    merge_gyeonggi_districts_into_cities,
)
from .diagnosis import add_market_type, select_analysis_targets, size_cutoff
from .io_utils import read_csv_with_encoding_fallback, save_csv
from .population import (
    calculate_resident_age_shares,
    load_busan_living_exposure,
    load_gyeonggi_floating_population_shares,
    load_kosis_future_population,
    load_resident_population,
    load_seoul_future_population,
    load_seoul_living_population_shares,
)
from .robustness import (
    adjust_stress_by_resident_exposure,
    build_busan_comparison,
    renormalize_shares,
    reweight_stress_by_external_population,
    summarize_robustness,
)
from .strategy import (
    build_defense_strategy,
    build_representative_case_table,
    pick_representative_cases,
    run_rebalancing,
)
from .stress import build_region_result
from .validation import (
    build_growth_comparison_table,
    build_stress_case_table,
    run_size_sensitivity,
    run_statistical_tests,
    split_by_growth,
    validate_region,
)

# 원본 파일 이름 (data/raw/ 기준)
RAW_FILES = {
    "card": "bc_card_202601_202606.csv",
    "resident_population_pattern": "population_2026*.csv",
    "seoul_future": "seoul_future_population_2022_2042.csv",
    "busan_future": "busan_future_population_2015_2040.xlsx",
    "gyeonggi_future": "gyeonggi_future_population_2022_2042.xlsx",
    "seoul_living": "seoul_living_population_2025.csv",
    "busan_living": "busan_living_population_age.xlsx",
    "gyeonggi_flow_folder": "gyeonggi_flow_202601_202603",
}

REGION_LABELS = {"서울특별시": "서울", "부산광역시": "부산", "경기도": "경기"}
REGION_CASE_KEYS = ["시군구", "업종코드", "업종명"]


def check_raw_files(raw_dir):
    """필요한 원본 파일이 모두 있는지 먼저 확인합니다.

    중간까지 실행하다가 파일이 없어 멈추면 원인을 찾기 어렵기 때문에,
    시작하기 전에 빠진 파일 목록을 한 번에 알려줍니다.
    """
    missing = []
    for key, name in RAW_FILES.items():
        if key.endswith("_pattern"):
            if not list(raw_dir.glob(name)):
                missing.append(name)
        elif not (raw_dir / name).exists():
            missing.append(name)
    if missing:
        raise FileNotFoundError(f"{raw_dir}에 다음 원본이 없습니다: {', '.join(missing)} (data/README.md 참고)")


def run_pipeline(raw_dir=None, output_dir=None):
    """원본 데이터에서 최종 결과표까지 전체 분석을 실행합니다.

    Returns:
        {결과 이름: DataFrame}. 같은 이름의 CSV가 output_dir에 저장됩니다.
    """
    raw_dir = Path(raw_dir or config.RAW_DATA_DIR)
    output_dir = Path(output_dir or config.OUTPUT_DIR)
    check_raw_files(raw_dir)
    tables = {}

    # ------------------------------------------------------------------
    # [STEP 1] 정제 · 표준화
    # ------------------------------------------------------------------
    card = clean_card_spending(load_card_spending(raw_dir / RAW_FILES["card"]))

    # 전국(시군구 단위) 소비구조와 프로필: 서울 · 부산 분석과 '전국 상위 25%' 기준에 사용
    national_structure = build_age_spending_structure(card)
    national_profile = build_region_industry_profile(card, national_structure)

    # 경기는 장래인구가 시 단위라서 일반구를 시로 합친 뒤 따로 만듭니다.
    gyeonggi_card = merge_gyeonggi_districts_into_cities(card[card["시도"] == "경기도"])
    gyeonggi_structure = build_age_spending_structure(gyeonggi_card)
    gyeonggi_profile = build_region_industry_profile(gyeonggi_card, gyeonggi_structure)

    future_population = {
        "서울특별시": load_seoul_future_population(raw_dir / RAW_FILES["seoul_future"]),
        "부산광역시": load_kosis_future_population(raw_dir / RAW_FILES["busan_future"], "부산광역시"),
        "경기도": load_kosis_future_population(raw_dir / RAW_FILES["gyeonggi_future"], "경기도"),
    }

    # ------------------------------------------------------------------
    # [STEP 4] Future Stress 계산 (지역별)
    # ------------------------------------------------------------------
    region_inputs = {
        "서울특별시": (national_profile, national_structure),
        "부산광역시": (national_profile, national_structure),
        "경기도": (gyeonggi_profile, gyeonggi_structure),
    }
    region_results, region_age_stress = {}, {}
    for province, (profile, structure) in region_inputs.items():
        region_results[province], region_age_stress[province] = build_region_result(
            profile, structure, future_population[province], province
        )

    # ------------------------------------------------------------------
    # [STEP 2 · 3] 발표 기준 검증: 서울 + 전국 상위 25% → 성장군 vs 비성장군
    # ------------------------------------------------------------------
    seoul_targets = select_analysis_targets(region_results["서울특별시"], size_cutoff(national_profile))
    seoul_growth, seoul_non_growth = split_by_growth(seoul_targets)
    tables["growth_vs_nongrowth_validation"] = build_growth_comparison_table(seoul_growth, seoul_non_growth)
    tables["statistical_validation"] = run_statistical_tests(seoul_growth, seoul_non_growth)
    tables["size_threshold_sensitivity"] = run_size_sensitivity(region_results["서울특별시"], national_profile)
    tables["stress_test_14_cases_table"] = build_stress_case_table(seoul_growth)

    # ------------------------------------------------------------------
    # [STEP 5] 지역별 검증 (지역 내부 상위 25%) + 4유형 분류
    # ------------------------------------------------------------------
    region_summaries, local_targets = [], {}
    for province, result in region_results.items():
        summary, targets = validate_region(result, REGION_LABELS[province])
        region_summaries.append(summary)
        local_targets[province] = add_market_type(targets)
    tables["region_validation"] = pd.DataFrame(region_summaries)
    tables["market_type_counts"] = (
        pd.DataFrame({REGION_LABELS[p]: t["유형"].value_counts() for p, t in local_targets.items()})
        .fillna(0).astype(int).rename_axis("유형").reset_index()
    )

    # ------------------------------------------------------------------
    # [전략] 서울 착시성장 사례의 방어형 고객 + 대표 사례
    # ------------------------------------------------------------------
    defense_strategy = build_defense_strategy(seoul_targets, region_age_stress["서울특별시"])
    tables["seoul_defense_strategy"] = defense_strategy
    tables["representative_3_cases_table"] = build_representative_case_table(
        pick_representative_cases(seoul_growth), defense_strategy
    )

    # ------------------------------------------------------------------
    # [검증] 외부유입 보정 (서울 생활인구 · 부산 생활인구 · 경기 유동인구)
    # ------------------------------------------------------------------
    resident = load_resident_population(sorted(raw_dir.glob(RAW_FILES["resident_population_pattern"])))
    all_months = [str(month) for month in config.ANALYSIS_MONTHS]
    robustness_rows = []

    # 서울: 생활인구 2025 vs 주민등록인구 2026.01~06, 6개 연령대
    seoul_living = load_seoul_living_population_shares(raw_dir / RAW_FILES["seoul_living"])
    seoul_comparison = reweight_stress_by_external_population(
        national_structure[national_structure["시도"] == "서울특별시"],
        seoul_living, "생활인구비중",
        calculate_resident_age_shares(resident, "서울특별시", all_months, AGE_GROUP_ORDER),
        future_population["서울특별시"], AGE_GROUP_ORDER,
    )
    seoul_comparison = local_targets["서울특별시"][REGION_CASE_KEYS].merge(seoul_comparison, on=REGION_CASE_KEYS)
    robustness_rows.append(summarize_robustness(
        seoul_comparison, "서울", f"서울 {seoul_living['시군구'].nunique()}개 자치구, 생활인구 기반 민감도 검증"
    ))

    # 부산: 거주노출비율 방식
    busan_adjusted = adjust_stress_by_resident_exposure(
        region_age_stress["부산광역시"], load_busan_living_exposure(raw_dir / RAW_FILES["busan_living"])
    )
    busan_comparison = build_busan_comparison(local_targets["부산광역시"], busan_adjusted)
    robustness_rows.append(summarize_robustness(
        busan_comparison, "부산", f"부산 Q75 {len(busan_comparison)}건, 생활인구 주거노출비율 기반 검증"
    ))

    # 경기: 유동인구 2026.01~03 vs 주민등록인구 같은 기간, 20대 이상 5개 연령대
    flow_shares = load_gyeonggi_floating_population_shares(raw_dir / RAW_FILES["gyeonggi_flow_folder"])
    gyeonggi_comparison = reweight_stress_by_external_population(
        gyeonggi_structure,
        renormalize_shares(flow_shares, "유동인구비중", ADULT_AGE_GROUPS), "유동인구비중",
        calculate_resident_age_shares(resident, "경기도", all_months[:3], ADULT_AGE_GROUPS,
                                      regions=flow_shares["시군구"].unique()),
        future_population["경기도"], ADULT_AGE_GROUPS,
    )
    gyeonggi_comparison = local_targets["경기도"][REGION_CASE_KEYS].merge(gyeonggi_comparison, on=REGION_CASE_KEYS)
    robustness_rows.append(summarize_robustness(
        gyeonggi_comparison, "경기",
        f"유동인구 제공지역 중 Q75와 매칭된 {gyeonggi_comparison['시군구'].nunique()}개 시군",
    ))
    tables["final_3region_robustness"] = pd.DataFrame(robustness_rows)

    # ------------------------------------------------------------------
    # [전략] 착시성장형 고객 구성 재조정 시뮬레이션 (3개 지역)
    # ------------------------------------------------------------------
    age_pool = pd.concat(
        [stress.assign(광역지역=REGION_LABELS[p], 지역명=stress["시군구"]) for p, stress in region_age_stress.items()],
        ignore_index=True,
    )
    illusion_cases = pd.concat(
        [t[t["유형"] == "착시성장형"].assign(광역지역=REGION_LABELS[p], 지역명=lambda d: d["시군구"])
         for p, t in local_targets.items()],
        ignore_index=True,
    )[["광역지역", "지역명", "업종코드", "업종명"]].drop_duplicates()
    tables["illusion_rebalancing"] = run_rebalancing(age_pool, illusion_cases)

    for name, table in tables.items():
        save_csv(table, output_dir / f"{name}.csv")
    return tables


def compare_with_published(output_dir=None, published_dir=None, tolerance=0.01):
    """새로 계산한 결과와 발표자료 결과(results/*.csv)를 비교합니다.

    리팩토링으로 계산 결과가 바뀌지 않았는지 확인하는 용도입니다.
    숫자는 반올림 차이를 감안해 tolerance 이내면 같다고 봅니다.

    Returns:
        파일 | 결과(일치/불일치/비교불가) | 설명
    """
    output_dir = Path(output_dir or config.OUTPUT_DIR)
    published_dir = Path(published_dir or config.PUBLISHED_RESULTS_DIR)
    rows = []
    for published_path in sorted(published_dir.glob("*.csv")):
        output_path = output_dir / published_path.name
        if not output_path.exists():
            rows.append({"파일": published_path.name, "결과": "비교불가", "설명": "파이프라인에서 만들지 않는 표"})
            continue
        published = read_csv_with_encoding_fallback(published_path)
        produced = read_csv_with_encoding_fallback(output_path)
        if published.shape != produced.shape:
            rows.append({"파일": published_path.name, "결과": "불일치",
                         "설명": f"크기 다름 {published.shape} vs {produced.shape}"})
            continue
        differences = []
        for column in published.columns:
            if column not in produced.columns:
                differences.append(f"'{column}' 열 없음")
                continue
            left = pd.to_numeric(published[column], errors="coerce")
            right = pd.to_numeric(produced[column], errors="coerce")
            both_numeric = left.notna() & right.notna()
            numeric_diff = ((left - right).abs() > tolerance) & both_numeric
            text_diff = ~both_numeric & (published[column].astype(str) != produced[column].astype(str))
            if (numeric_diff | text_diff).any():
                differences.append(column)
        rows.append({
            "파일": published_path.name,
            "결과": "일치" if not differences else "불일치",
            "설명": ", ".join(differences),
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="미래 소비기반 스트레스 테스트 파이프라인")
    parser.add_argument("--raw-dir", default=config.RAW_DATA_DIR, help="원본 데이터 폴더 (기본: data/raw)")
    parser.add_argument("--output-dir", default=config.OUTPUT_DIR, help="결과 저장 폴더 (기본: output)")
    parser.add_argument("--compare", action="store_true", help="실행 후 results/의 발표 수치와 비교")
    arguments = parser.parse_args()

    tables = run_pipeline(arguments.raw_dir, arguments.output_dir)
    print(f"결과 {len(tables)}개를 {arguments.output_dir}에 저장했습니다.")
    if arguments.compare:
        print(compare_with_published(arguments.output_dir).to_string(index=False))


if __name__ == "__main__":
    main()
