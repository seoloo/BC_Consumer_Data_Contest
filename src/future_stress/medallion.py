"""메달리온 아키텍처: Bronze → Silver → Gold 세 계층으로 데이터를 쌓습니다.

왜 계층을 나누나요?
    원래 노트북은 원본을 읽자마자 정제 · 집계 · 분석을 한 번에 하고, 중간 결과를
    data/processed에 이름만 다른 CSV 30여 개로 남겼습니다. 어떤 CSV가 어느 단계의
    결과인지, 원본이 바뀌면 무엇을 다시 만들어야 하는지 알기 어려웠습니다.

    계층을 나누면
    - 각 계층은 '바로 앞 계층만' 읽습니다 → 문제가 생긴 계층을 바로 찾고 그 계층부터 다시 만듭니다.
    - Bronze에 원본을 그대로 남깁니다 → 정제 규칙이 바뀌어도 원본에서 다시 시작할 수 있습니다.
    - 계층 사이에서 건수 · 금액을 대사합니다 → "정제하다가 데이터가 사라지지 않았나"를 숫자로 확인합니다.

    계층    저장 위치        형식      담는 것
    Bronze  data/bronze/    원본 그대로  원본 파일 + 적재 영수증(_manifest.json: 크기 · 지문 · 행 수 · 적재 시각)
    Silver  data/silver/    Parquet    정제 · 표준화된 데이터 (원본과 같은 단위, 집계 전)
    Gold    data/gold/      Parquet    분석 결과 (Stress, 4유형, 검증, 전략)

    Parquet을 쓰는 이유: 열 단위로 압축해 CSV보다 작고 빠르며, 숫자 · 문자 같은 데이터 타입이
    함께 저장되어 다시 읽을 때 '업종코드가 숫자로 바뀌는' 식의 문제가 생기지 않습니다.

앞으로의 계획 (docs/diagrams/07_medallion.png)
    Bronze는 SeaweedFS(S3 호환 저장소)로 옮겼습니다 (object_store.py, pipeline --object-store).
    Silver · Gold는 Phase 3에 PostgreSQL 스키마 + dbt 모델로 옮깁니다.
"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .age_groups import ADULT_AGE_GROUPS, AGE_GROUP_ORDER, BC_AGE_CODE_TO_GROUP, BC_GENDER_CODE_TO_NAME
from .card_spending import (
    analysis_months,
    build_age_spending_structure,
    build_region_industry_profile,
    card_file_end_month,
    clean_card_spending,
    load_card_files,
    merge_gyeonggi_districts_into_cities,
)
from .diagnosis import MARKET_TYPE_STRATEGY, add_market_type, select_analysis_targets, size_cutoff
from .io_utils import read_parquet, save_parquet
from .population import (
    POPULATION_YEARS,
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
from .strategy import build_defense_strategy, build_representative_case_table, pick_representative_cases, run_rebalancing
from .stress import build_region_result
from .validation import (
    build_growth_comparison_table,
    build_stress_case_table,
    run_size_sensitivity,
    run_statistical_tests,
    split_by_growth,
    validate_region,
)

# ===========================================================================
# 원본 목록
# ===========================================================================
# 원본 이름 → (Bronze 안의 폴더, data/raw 안의 파일 이름 또는 패턴)
# 원본 파일명이 바뀌면 여기만 고치면 됩니다.
RAW_SOURCES = {
    # 배치마다 한 파일씩 도착 (bc_card_<시작월>_<끝월>.csv). 같은 달이 겹치면 늦게 온 파일이 이김 (load_card_files)
    "card": ("card_spending", "bc_card_*.csv"),
    "resident_population": ("resident_population", "population_2026*.csv"),
    "seoul_future": ("future_population", "seoul_future_population_2022_2042.csv"),
    "busan_future": ("future_population", "busan_future_population_2015_2040.xlsx"),
    "gyeonggi_future": ("future_population", "gyeonggi_future_population_2022_2042.xlsx"),
    "seoul_living": ("living_population", "seoul_living_population_2025.csv"),
    "busan_living": ("living_population", "busan_living_population_age.xlsx"),
    "gyeonggi_flow": ("floating_population", "gyeonggi_flow_202601_202603"),   # CSV가 든 폴더
}

REGION_LABELS = {"서울특별시": "서울", "부산광역시": "부산", "경기도": "경기"}
REGION_CASE_KEYS = ["시군구", "업종코드", "업종명"]

# 발표 결과(results/)와 같은 이름 · 형식으로 output/에 내보낼 Gold 표
PUBLISHED_TABLES = [
    "growth_vs_nongrowth_validation",
    "statistical_validation",
    "size_threshold_sensitivity",
    "stress_test_14_cases_table",
    "representative_3_cases_table",
    "final_3region_robustness",
]


class DataQualityError(RuntimeError):
    """계층 사이의 대사 검사가 실패했을 때 파이프라인을 멈추기 위한 예외."""


# ===========================================================================
# Bronze · 원본을 그대로 보관
# ===========================================================================

def find_raw_files(raw_dir, name):
    """data/raw 안에서 원본 하나(파일, 패턴, 폴더)에 해당하는 파일 목록을 찾습니다."""
    raw_dir = Path(raw_dir)
    if "*" in name:
        return sorted(raw_dir.glob(name))
    path = raw_dir / name
    if path.is_dir():
        return sorted(path.rglob("*.csv"))
    return [path] if path.exists() else []


def latest_card_batch(raw_dir):
    """원본 폴더에 있는 BC카드 파일의 가장 최근 배치 월 (파일 이름의 끝월). 파일이 없으면 None."""
    months = [card_file_end_month(path) for path in find_raw_files(raw_dir, RAW_SOURCES["card"][1])]
    return max(months) if months else None


def check_raw_files(raw_dir):
    """필요한 원본이 모두 있는지 시작 전에 확인하고, 빠진 것을 한 번에 알려줍니다."""
    missing = [name for _, name in RAW_SOURCES.values() if not find_raw_files(raw_dir, name)]
    if missing:
        raise FileNotFoundError(f"{raw_dir}에 다음 원본이 없습니다: {', '.join(missing)} (data/README.md 참고)")


def file_fingerprint(path):
    """파일 내용의 지문(SHA-256)을 계산합니다.

    내용이 한 글자만 달라도 지문이 바뀌므로, '지난번과 같은 원본인가'를 확인하는 데 씁니다.
    큰 파일도 메모리를 적게 쓰도록 1MB씩 나눠 읽습니다.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path):
    """CSV의 데이터 행 수(머리글 제외). 엑셀은 행 수를 세지 않고 None을 기록합니다."""
    if path.suffix.lower() != ".csv":
        return None
    with open(path, "rb") as file:
        return max(sum(1 for _ in file) - 1, 0)


def build_bronze(raw_dir=None, bronze_dir=None):
    """[Bronze] 원본을 수정 없이 복사하고 적재 영수증(_manifest.json)을 남깁니다.

    멱등성(여러 번 실행해도 결과가 같음)
        이미 같은 지문의 파일이 있으면 복사하지 않고 '변경 없음'으로 기록합니다.
        원본이 바뀌었을 때만 덮어쓰므로, 영수증을 보면 언제 무엇이 바뀌었는지 알 수 있습니다.

    Returns:
        영수증 내용 (파일마다 계층 경로, 크기, 지문, 행 수, 상태)
    """
    raw_dir = Path(raw_dir or config.RAW_DATA_DIR)
    bronze_dir = Path(bronze_dir or config.BRONZE_DIR)
    check_raw_files(raw_dir)

    entries = []
    for source_key, (folder, name) in RAW_SOURCES.items():
        for source_path in find_raw_files(raw_dir, name):
            # 폴더 원본(경기 유동인구)은 폴더 구조를 그대로 유지합니다.
            relative = source_path.relative_to(raw_dir)
            target_path = bronze_dir / folder / relative
            fingerprint = file_fingerprint(source_path)
            if target_path.exists() and file_fingerprint(target_path) == fingerprint:
                status = "변경 없음"
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                status = "새로 적재"
            entries.append({
                "source": source_key,
                "bronze_path": target_path.relative_to(bronze_dir).as_posix(),
                "bytes": source_path.stat().st_size,
                "sha256": fingerprint,
                "rows": count_csv_rows(source_path),
                "status": status,
            })

    manifest = {"ingested_at": datetime.now().isoformat(timespec="seconds"), "files": entries}
    bronze_dir.mkdir(parents=True, exist_ok=True)
    (bronze_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def bronze_path(bronze_dir, source_key):
    """Bronze 안에서 원본 하나의 경로를 돌려줍니다 (패턴 원본은 파일 목록)."""
    folder, name = RAW_SOURCES[source_key]
    files = find_raw_files(Path(bronze_dir) / folder, name)
    if "*" in name:
        return files
    return Path(bronze_dir) / folder / name


# ===========================================================================
# Silver · 정제 · 표준화 (집계 전)
# ===========================================================================

def build_silver(bronze_dir=None, silver_dir=None):
    """[Silver] Bronze 원본을 정제 · 표준화해 Parquet으로 저장합니다.

    Silver 표의 원칙
        - 원본과 같은 단위(행 하나 = 원본 행 하나 또는 시군구 × 연령대)로 둡니다. 분석용 집계는 Gold에서.
        - 연령대 · 지역 · 업종 이름은 표준 기준표(age_groups, regions)를 따릅니다.
        - 지역마다 형식이 달랐던 원본도 같은 열 구조로 맞춥니다.

    Returns:
        {표 이름: DataFrame}
    """
    bronze_dir = Path(bronze_dir or config.BRONZE_DIR)
    silver_dir = Path(silver_dir or config.SILVER_DIR)

    future_by_province = {
        "서울특별시": load_seoul_future_population(bronze_path(bronze_dir, "seoul_future")),
        "부산광역시": load_kosis_future_population(bronze_path(bronze_dir, "busan_future"), "부산광역시"),
        "경기도": load_kosis_future_population(bronze_path(bronze_dir, "gyeonggi_future"), "경기도"),
    }
    # 3개 시도를 시도 열이 있는 한 표로 합칩니다.
    # Parquet은 열 이름이 문자여야 해서 2026 같은 숫자 연도 열을 '2026년 인구'로 바꿉니다.
    future_population = pd.concat(
        [table.assign(시도=province) for province, table in future_by_province.items()], ignore_index=True
    ).rename(columns={year: f"{year}년 인구" for year in POPULATION_YEARS})

    tables = {
        # Silver에는 도착한 모든 달을 쌓고, 분석 기간(최근 6개월)은 Gold에서 고릅니다.
        "card_spending": clean_card_spending(load_card_files(bronze_path(bronze_dir, "card"))),
        "future_population": future_population,
        "resident_population": load_resident_population(bronze_path(bronze_dir, "resident_population")),
        "seoul_living_share": load_seoul_living_population_shares(bronze_path(bronze_dir, "seoul_living")),
        "busan_living_exposure": load_busan_living_exposure(bronze_path(bronze_dir, "busan_living")),
        "gyeonggi_flow_share": load_gyeonggi_floating_population_shares(bronze_path(bronze_dir, "gyeonggi_flow")),
    }
    for name, table in tables.items():
        save_parquet(table, silver_dir / f"{name}.parquet")
    return tables


def read_silver(silver_dir=None):
    """Silver 계층을 디스크에서 다시 읽습니다. Gold는 메모리가 아니라 저장된 Silver만 봅니다."""
    silver_dir = Path(silver_dir or config.SILVER_DIR)
    return {path.stem: read_parquet(path) for path in sorted(silver_dir.glob("*.parquet"))}


# ===========================================================================
# Gold · 분석 결과
# ===========================================================================

def analysis_window_table(months, silver_card):
    """분석 기간 한 줄 (Gold). 화면 · 비교 · 대사가 '몇 월부터 몇 월까지로 계산했는지'를 같은 값으로 보게 합니다."""
    available = sorted(int(month) for month in silver_card["기준년월"].unique())
    return pd.DataFrame([{
        "시작월": months[0], "끝월": months[-1], "개월수": len(months),
        "결제가있는달수": sum(month in available for month in months),
        "Silver전체기간": f"{available[0]} ~ {available[-1]} ({len(available)}개월)",
    }])


def future_population_of(silver, province):
    """Silver의 통합 장래인구에서 한 시도만 꺼냅니다."""
    future = silver["future_population"]
    return future[future["시도"] == province].drop(columns="시도")


def build_gold(silver_dir=None, gold_dir=None):
    """[Gold] Silver를 읽어 STEP 2~5, 검증, 전략 결과를 만들고 Parquet으로 저장합니다.

    흐름도(docs/diagrams/03_pipeline.png)의 단계 이름을 주석 [STEP n]으로 표시했습니다.

    Returns:
        {표 이름: DataFrame}
    """
    silver = read_silver(silver_dir)
    gold_dir = Path(gold_dir or config.GOLD_DIR)
    # [분석 기간] Silver의 마지막 달에서 거꾸로 6개월. 소비구조 · 성장 · Stress는 모두 이 기간의 결제로만 계산합니다.
    months = analysis_months(silver["card_spending"])
    card = silver["card_spending"][silver["card_spending"]["기준년월"].isin(months)]
    gold = {"analysis_window": analysis_window_table(months, silver["card_spending"])}

    # [STEP 1] 연령별 소비구조 · 프로필
    # 전국(시군구 단위): 서울 · 부산 분석과 '전국 상위 25%' 기준에 사용
    national_structure = build_age_spending_structure(card)
    national_profile = build_region_industry_profile(card, national_structure, months)
    # 경기는 장래인구가 시 단위라서 일반구를 시로 합친 뒤 따로 만듭니다.
    gyeonggi_card = merge_gyeonggi_districts_into_cities(card[card["시도"] == "경기도"])
    gyeonggi_structure = build_age_spending_structure(gyeonggi_card)
    gyeonggi_profile = build_region_industry_profile(gyeonggi_card, gyeonggi_structure, months)
    gold["age_spending_structure"] = national_structure
    gold["region_industry_profile"] = national_profile
    gold["gyeonggi_city_age_spending_structure"] = gyeonggi_structure

    # [STEP 4] Future Stress (지역별)
    region_inputs = {
        "서울특별시": (national_profile, national_structure),
        "부산광역시": (national_profile, national_structure),
        "경기도": (gyeonggi_profile, gyeonggi_structure),
    }
    region_results, region_age_stress = {}, {}
    for province, (profile, structure) in region_inputs.items():
        region_results[province], region_age_stress[province] = build_region_result(
            profile, structure, future_population_of(silver, province), province
        )
    gold["future_stress"] = pd.concat(region_results.values(), ignore_index=True)
    gold["age_stress"] = pd.concat(region_age_stress.values(), ignore_index=True)

    # [STEP 2 · 3] 발표 기준 검증: 서울 + 전국 상위 25% → 성장군 vs 비성장군
    seoul_targets = select_analysis_targets(region_results["서울특별시"], size_cutoff(national_profile))
    seoul_growth, seoul_non_growth = split_by_growth(seoul_targets)
    gold["growth_vs_nongrowth_validation"] = build_growth_comparison_table(seoul_growth, seoul_non_growth)
    gold["statistical_validation"] = run_statistical_tests(seoul_growth, seoul_non_growth)
    gold["size_threshold_sensitivity"] = run_size_sensitivity(region_results["서울특별시"], national_profile)
    gold["stress_test_14_cases_table"] = build_stress_case_table(seoul_growth)

    # [STEP 5] 지역별 검증 (지역 내부 상위 25%) + 4유형 분류
    region_summaries, local_targets = [], {}
    for province, result in region_results.items():
        summary, targets = validate_region(result, REGION_LABELS[province])
        region_summaries.append(summary)
        local_targets[province] = add_market_type(targets)
    gold["region_validation"] = pd.DataFrame(region_summaries)
    gold["market_type"] = pd.concat(local_targets.values(), ignore_index=True)
    # 4유형을 항상 같은 순서로 모두 보여 줍니다. 한 건도 없는 유형도 0으로 남겨야 '없음'이 결과로 보입니다
    # (예전에는 나온 유형만 줄로 만들어, 합성 데이터처럼 지속성장형이 없으면 줄이 사라졌습니다. dbt 모델과 같게 맞춤).
    gold["market_type_counts"] = (
        pd.DataFrame({REGION_LABELS[p]: t["유형"].value_counts() for p, t in local_targets.items()})
        .reindex(list(MARKET_TYPE_STRATEGY)).fillna(0).astype(int).rename_axis("유형").reset_index()
    )

    # [전략] 서울 착시성장 사례의 방어형 고객 + 대표 사례
    defense_strategy = build_defense_strategy(seoul_targets, region_age_stress["서울특별시"])
    gold["seoul_defense_strategy"] = defense_strategy
    gold["representative_3_cases_table"] = build_representative_case_table(
        pick_representative_cases(seoul_growth), defense_strategy
    )

    # [검증] 외부유입 보정 (서울 생활인구 · 부산 생활인구 · 경기 유동인구)
    resident = silver["resident_population"]
    all_months = [str(month) for month in months]   # 주민등록인구는 분석 기간 중 있는 달만 평균
    robustness_rows = []

    seoul_living = silver["seoul_living_share"]
    seoul_comparison = reweight_stress_by_external_population(
        national_structure[national_structure["시도"] == "서울특별시"],
        seoul_living, "생활인구비중",
        calculate_resident_age_shares(resident, "서울특별시", all_months, AGE_GROUP_ORDER),
        future_population_of(silver, "서울특별시"), AGE_GROUP_ORDER,
    )
    seoul_comparison = local_targets["서울특별시"][REGION_CASE_KEYS].merge(seoul_comparison, on=REGION_CASE_KEYS)
    robustness_rows.append(summarize_robustness(
        seoul_comparison, "서울", f"서울 {seoul_living['시군구'].nunique()}개 자치구, 생활인구 기반 민감도 검증"
    ))

    busan_adjusted = adjust_stress_by_resident_exposure(region_age_stress["부산광역시"], silver["busan_living_exposure"])
    busan_comparison = build_busan_comparison(local_targets["부산광역시"], busan_adjusted)
    robustness_rows.append(summarize_robustness(
        busan_comparison, "부산", f"부산 Q75 {len(busan_comparison)}건, 생활인구 주거노출비율 기반 검증"
    ))

    flow_shares = silver["gyeonggi_flow_share"]
    gyeonggi_comparison = reweight_stress_by_external_population(
        gyeonggi_structure,
        renormalize_shares(flow_shares, "유동인구비중", ADULT_AGE_GROUPS), "유동인구비중",
        calculate_resident_age_shares(resident, "경기도", config.GYEONGGI_FLOW_MONTHS, ADULT_AGE_GROUPS,
                                      regions=flow_shares["시군구"].unique()),
        future_population_of(silver, "경기도"), ADULT_AGE_GROUPS,
    )
    gyeonggi_comparison = local_targets["경기도"][REGION_CASE_KEYS].merge(gyeonggi_comparison, on=REGION_CASE_KEYS)
    robustness_rows.append(summarize_robustness(
        gyeonggi_comparison, "경기",
        f"유동인구 제공지역 중 Q75와 매칭된 {gyeonggi_comparison['시군구'].nunique()}개 시군",
    ))
    gold["final_3region_robustness"] = pd.DataFrame(robustness_rows)

    # [전략] 착시성장형 고객 구성 재조정 시뮬레이션 (3개 지역)
    age_pool = pd.concat(
        [stress.assign(광역지역=REGION_LABELS[p], 지역명=stress["시군구"]) for p, stress in region_age_stress.items()],
        ignore_index=True,
    )
    illusion_cases = pd.concat(
        [t[t["유형"] == "착시성장형"].assign(광역지역=REGION_LABELS[p], 지역명=lambda d: d["시군구"])
         for p, t in local_targets.items()],
        ignore_index=True,
    )[["광역지역", "지역명", "업종코드", "업종명"]].drop_duplicates()
    gold["illusion_rebalancing"] = run_rebalancing(age_pool, illusion_cases)

    for name, table in gold.items():
        save_parquet(table, gold_dir / f"{name}.parquet")
    return gold


# ===========================================================================
# 계층 사이 대사 (데이터 품질 검사)
# ===========================================================================

def check_row(check, layer, expected, actual, passed, note, blocking=True):
    """검사 결과 한 줄. blocking=False인 검사는 실패해도 '경고'로만 남기고 계속 진행합니다."""
    return {
        "검사": check, "계층": layer, "기대값": expected, "실제값": actual,
        "결과": "통과" if passed else ("실패" if blocking else "경고"), "설명": note,
    }


def run_quality_checks(bronze_dir=None, silver=None, gold=None):
    """Bronze → Silver → Gold 사이에서 건수 · 금액이 맞는지 대사합니다.

    왜 대사를 하나요?
        정제 단계에서 '개인 결제만 남기기' 같은 필터를 쓰면 행과 금액이 줄어듭니다.
        줄어든 만큼이 정확히 '빼기로 한 데이터'인지 확인해야, 실수로 데이터를 잃지 않았다고 말할 수 있습니다.
        금융권 데이터에서 원장 합계와 마트 합계를 맞춰 보는 대사 업무와 같은 원리입니다.

    Returns:
        검사 | 계층 | 기대값 | 실제값 | 결과(통과/실패/경고) | 설명
    """
    bronze_dir = Path(bronze_dir or config.BRONZE_DIR)
    silver = silver or read_silver()
    gold = gold or {path.stem: read_parquet(path) for path in config.GOLD_DIR.glob("*.parquet")}
    rows = []

    # 1~2. Bronze → Silver: 개인 결제 필터로 빠진 만큼만 줄었는가
    raw_card = load_card_files(bronze_path(bronze_dir, "card"))
    is_personal = (
        raw_card["GENDER_CD"].astype(str).str.strip().isin(BC_GENDER_CODE_TO_NAME)
        & raw_card["AGE_CD"].astype(str).str.strip().isin(BC_AGE_CODE_TO_GROUP)
    )
    silver_card = silver["card_spending"]
    excluded_rows = int((~is_personal).sum())
    rows.append(check_row(
        "카드 행 수 대사", "Bronze → Silver",
        f"{len(raw_card):,} - 제외 {excluded_rows:,} = {len(raw_card) - excluded_rows:,}", f"{len(silver_card):,}",
        len(raw_card) - excluded_rows == len(silver_card),
        "원본 행 = Silver 행 + 개인이 아닌 코드(성별 3 · x 등)로 제외한 행",
    ))
    raw_amount, excluded_amount = int(raw_card["amt"].sum()), int(raw_card.loc[~is_personal, "amt"].sum())
    silver_amount = int(silver_card["이용금액"].sum())
    rows.append(check_row(
        "카드 금액 대사", "Bronze → Silver",
        f"{raw_amount - excluded_amount:,}", f"{silver_amount:,}",
        raw_amount - excluded_amount == silver_amount,
        f"원본 금액 {raw_amount:,}원 중 제외 {excluded_amount:,}원 ({excluded_amount / raw_amount:.1%})",
    ))

    # 3. Silver 허용값: 표준 기준표에 없는 이름이 들어오지 않았는가
    unknown_ages = sorted(set(silver_card["연령대"]) - set(AGE_GROUP_ORDER))
    rows.append(check_row(
        "연령대 허용값", "Silver", "6개 표준 연령대만", ", ".join(unknown_ages) or "모두 표준",
        not unknown_ages, "age_groups.AGE_GROUP_ORDER 기준",
    ))
    unknown_future_ages = sorted(set(silver["future_population"]["연령대"].dropna()) - set(AGE_GROUP_ORDER))
    rows.append(check_row(
        "장래인구 연령대 허용값", "Silver", "6개 표준 연령대만", ", ".join(unknown_future_ages) or "모두 표준",
        not unknown_future_ages, "20대미만 → 20대이하 같은 별칭이 모두 표준화됐는지",
    ))

    # 4~5. Silver → Gold: 집계 과정에서 금액이 새거나 늘지 않았는가 (Gold는 분석 기간의 결제만 씀)
    window = gold["analysis_window"].iloc[0]
    window_card = silver_card[silver_card["기준년월"].between(int(window["시작월"]), int(window["끝월"]))]
    window_amount = int(window_card["이용금액"].sum())
    gold_amount = int(gold["age_spending_structure"]["이용금액"].sum())
    rows.append(check_row(
        "전국 소비구조 금액 대사", "Silver → Gold", f"{window_amount:,}", f"{gold_amount:,}",
        window_amount == gold_amount,
        f"연령별 소비구조의 이용금액 합계 = 분석 기간({int(window['시작월'])} ~ {int(window['끝월'])}) Silver 카드 금액 합계",
    ))
    gyeonggi_silver = int(window_card.loc[window_card["시도"] == "경기도", "이용금액"].sum())
    gyeonggi_gold = int(gold["gyeonggi_city_age_spending_structure"]["이용금액"].sum())
    rows.append(check_row(
        "경기 시 단위 통합 대사", "Silver → Gold", f"{gyeonggi_silver:,}", f"{gyeonggi_gold:,}",
        gyeonggi_silver == gyeonggi_gold, "일반구를 시로 합친 뒤에도 경기 금액 합계가 같은지",
    ))

    # 6. 장래인구 매칭: Stress를 계산할 인구증감률이 빠진 연령 행이 있는가 (경고)
    age_stress = gold["age_stress"]
    for province, label in REGION_LABELS.items():
        province_rows = age_stress[age_stress["시도"] == province]
        unmatched = int(province_rows["2040 증감률"].isna().sum())
        rows.append(check_row(
            f"{label} 장래인구 매칭", "Gold", "증감률 결측 0행", f"{unmatched:,} / {len(province_rows):,}행",
            unmatched == 0,
            "BC카드 시군구 · 연령대에 맞는 장래인구가 없으면 그 연령대는 Stress에서 빠짐",
            blocking=False,
        ))

    # 7. 6개월 완전성 (참고용)
    profile = gold["region_industry_profile"]
    complete = int((profile["6개월완전"] == True).sum())  # noqa: E712
    rows.append(check_row(
        "6개월 완전관측 비율", "Gold", "참고", f"{complete:,} / {len(profile):,}건 ({complete / len(profile):.1%})",
        True, "6개월이 다 있지 않은 지역 × 업종은 성장 판정에서 제외",
    ))
    return pd.DataFrame(rows)
