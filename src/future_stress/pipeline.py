"""전체 분석을 메달리온 계층 순서(Bronze → Silver → Gold)로 실행합니다.

실행 방법 (저장소 루트에서)
    .venv/Scripts/python -m future_stress.pipeline              # 계층별 저장 + output/에 결과 CSV
    .venv/Scripts/python -m future_stress.pipeline --compare    # 실행 후 contest/results/의 공모전 결과표와 비교
    .venv/Scripts/python -m future_stress.pipeline --synthetic  # 원본 없이 합성 데이터로 실행 (data/synthetic/)
    .venv/Scripts/python -m future_stress.pipeline --object-store  # Bronze를 SeaweedFS에 올리고, 거기서 받아 Silver부터
    .venv/Scripts/python -m future_stress.pipeline --warehouse     # Bronze 원본을 PostgreSQL raw 스키마에도 적재

실행 순서
    1. Bronze   data/raw의 원본을 그대로 복사하고 적재 영수증을 남김     medallion.build_bronze
       (--object-store) 객체 저장소에 올리고 다시 받아 지문 확인          object_store.upload_bronze / download_bronze
       (--warehouse)    PostgreSQL raw 스키마에 적재하고 행 수 · 합계 대사  warehouse.load_raw
    2. Silver   정제 · 표준화한 표를 Parquet으로 저장                   medallion.build_silver
    3. Gold     Silver만 읽어 Stress · 4유형 · 검증 · 전략 계산          medallion.build_gold
    4. 대사     계층 사이 건수 · 금액이 맞는지 검사, 실패하면 멈춤        medallion.run_quality_checks
    5. 내보내기  공모전 결과표와 같은 형식의 CSV를 output/에 저장

흐름도: docs/diagrams/07_medallion.png (계층), docs/diagrams/03_pipeline.png (분석 단계)
"""

import argparse
from pathlib import Path

import pandas as pd

from . import config
from .io_utils import read_csv_with_encoding_fallback, save_csv
from .medallion import (
    PUBLISHED_TABLES,
    DataQualityError,
    build_bronze,
    build_gold,
    build_silver,
    check_raw_files,  # noqa: F401  (예전처럼 pipeline에서도 import할 수 있게 유지)
    check_row,
    latest_card_batch,
    run_quality_checks,
)
from .storage.object_store import DEFAULT_BUCKET, SYNTHETIC_BUCKET, ObjectStore, download_bronze, upload_bronze
from .storage.warehouse import RAW_SCHEMA, SYNTHETIC_RAW_SCHEMA, Warehouse, load_raw
from .ingest.synthetic import write_synthetic_raw_files

# 공모전 결과표 외에 output/에 함께 내보내는 Gold 표 (사람이 엑셀로 열어 보기 위한 용도)
EXTRA_OUTPUT_TABLES = ["region_validation", "market_type_counts", "seoul_defense_strategy", "illusion_rebalancing"]


def layer_dirs(data_dir=None):
    """data_dir 아래의 bronze · silver · gold 폴더. 기본값은 config에 정한 data/ 폴더입니다."""
    if data_dir is None:
        return config.BRONZE_DIR, config.SILVER_DIR, config.GOLD_DIR
    data_dir = Path(data_dir)
    return data_dir / "bronze", data_dir / "silver", data_dir / "gold"


def run_pipeline(raw_dir=None, output_dir=None, data_dir=None, object_store=None, batch_month=None, warehouse=None):
    """원본에서 최종 결과표까지 메달리온 계층 순서로 실행합니다.

    Args:
        raw_dir: 원본 폴더 (기본 data/raw).
        output_dir: 발표 형식 CSV를 저장할 폴더 (기본 output/).
        data_dir: bronze · silver · gold를 만들 폴더 (기본 data/). 테스트에서는 임시 폴더를 넘깁니다.
        object_store: ObjectStore를 넘기면 Bronze를 객체 저장소에 올리고, 저장소에서 다시 받은 파일로 Silver를 만듭니다.
            None이면 지금처럼 로컬 폴더만 씁니다 (Docker 없이도 돌아가게).
        batch_month: 객체 저장소의 배치 월 폴더 (기본: 원본 폴더의 가장 최근 BC카드 파일 끝월).
        warehouse: Warehouse를 넘기면 Bronze 원본을 PostgreSQL raw 스키마에도 적재합니다 (Phase 3에서 dbt가 읽을 곳).

    Returns:
        {표 이름: DataFrame} · Gold 표 전체와 'quality_report'
    """
    output_dir = Path(output_dir or config.OUTPUT_DIR)
    bronze_dir, silver_dir, gold_dir = layer_dirs(data_dir)

    build_bronze(raw_dir, bronze_dir)
    batch_month = batch_month or latest_card_batch(raw_dir or config.RAW_DATA_DIR)
    store_checks = []
    if object_store is not None:
        upload_report = upload_bronze(bronze_dir, object_store, batch_month)
        # Silver는 로컬 복사본이 아니라 저장소에서 받은 Bronze를 읽습니다. 저장소가 실제 원본 보관소가 되게 하기 위해서입니다.
        # 받은 파일의 지문이 영수증과 다르면 download_bronze가 DataQualityError로 멈춥니다.
        bronze_dir, file_count = download_bronze(object_store, bronze_dir.parent / "bronze_cache", batch_month)
        status_counts = upload_report["상태"].value_counts()
        store_checks.append(check_row(
            "객체 저장소 왕복 지문", "Bronze → 저장소 → Silver", f"{file_count:,}개 영수증과 같음", f"{file_count:,}개 같음",
            True, "올림: " + " · ".join(f"{status} {count}" for status, count in status_counts.items()),
        ))
    if warehouse is not None:
        # 적재 뒤 DB의 행 수 · 합계가 원본과 다르면 load_raw가 DataQualityError로 되돌리고 멈춥니다.
        for result in load_raw(bronze_dir, warehouse).to_dict("records"):
            store_checks.append(check_row(
                f"raw 적재 대사 ({result['표']})", "Bronze → PostgreSQL", "원본과 행 수 · 합계 같음",
                f"{result['행 수']:,}행", True, f"{result['상태']} · 합계 {result['합계']:,}",
            ))
    return build_layers_and_export(bronze_dir, silver_dir, gold_dir, output_dir, store_checks)


def build_layers_and_export(bronze_dir, silver_dir, gold_dir, output_dir, extra_checks=()):
    """Bronze에서 Silver · Gold를 만들고, 층 사이 대사를 통과하면 결과 CSV를 내보냅니다.

    run_pipeline의 뒷부분이지만 따로 떼어 둔 이유: Airflow DAG는 Bronze 적재 · 객체 저장소 · raw 적재를
    각각 다른 단계로 돌린 뒤 이 부분만 한 단계로 부릅니다 (실패한 단계만 다시 돌릴 수 있게).

    Args:
        extra_checks: 앞 단계(객체 저장소 왕복 지문, raw 적재 대사)에서 만든 대사 줄. 보고서 맨 앞에 붙입니다.
    """
    output_dir = Path(output_dir)
    silver = build_silver(bronze_dir, silver_dir)
    gold = build_gold(silver_dir, gold_dir)

    quality_report = run_quality_checks(bronze_dir, silver, gold)
    if extra_checks:
        quality_report = pd.concat([pd.DataFrame(list(extra_checks)), quality_report], ignore_index=True)
    save_csv(quality_report, Path(gold_dir) / "_quality_report.csv")
    save_csv(quality_report, output_dir / "quality_report.csv")
    failed = quality_report[quality_report["결과"] == "실패"]
    if not failed.empty:
        # 대사가 맞지 않으면 결과를 내보내지 않고 멈춥니다. 틀린 숫자가 공모전 결과표처럼 쓰이는 것을 막기 위해서입니다.
        raise DataQualityError("계층 사이 대사 실패:\n" + failed.to_string(index=False))

    for name in PUBLISHED_TABLES + EXTRA_OUTPUT_TABLES:
        save_csv(gold[name], output_dir / f"{name}.csv")
    return {**gold, "quality_report": quality_report}


def compare_with_published(output_dir=None, published_dir=None, tolerance=0.01):
    """새로 계산한 결과와 발표자료 결과(contest/results/*.csv)를 비교합니다.

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
    parser = argparse.ArgumentParser(description="미래 소비기반 스트레스 테스트 파이프라인 (Bronze → Silver → Gold)")
    parser.add_argument("--raw-dir", default=config.RAW_DATA_DIR, help="원본 데이터 폴더 (기본: data/raw)")
    parser.add_argument("--output-dir", default=config.OUTPUT_DIR, help="결과 CSV 저장 폴더 (기본: output)")
    parser.add_argument("--data-dir", default=None, help="bronze · silver · gold를 만들 폴더 (기본: data)")
    parser.add_argument("--compare", action="store_true", help="실행 후 contest/results/의 공모전 결과표와 비교")
    parser.add_argument("--synthetic", action="store_true",
                        help="합성 원본을 만들어 data/synthetic/ 아래에서 실행 (원본 데이터가 없을 때)")
    parser.add_argument("--seed", type=int, default=42, help="--synthetic에서 쓸 시드")
    parser.add_argument("--warehouse", action="store_true",
                        help="Bronze 원본을 PostgreSQL raw 스키마에도 적재 (docker compose up -d 필요)")
    parser.add_argument("--object-store", action="store_true",
                        help="Bronze를 객체 저장소(SeaweedFS)에 올리고 거기서 받아 실행 (docker compose up -d 필요)")
    arguments = parser.parse_args()

    if arguments.synthetic:
        # 원본 결과(data/bronze ...)와 섞이지 않도록 raw · 계층 · 결과를 모두 data/synthetic 아래에 만듭니다.
        arguments.raw_dir = write_synthetic_raw_files(config.SYNTHETIC_RAW_DIR, arguments.seed)
        arguments.data_dir = config.SYNTHETIC_DIR
        arguments.output_dir = config.SYNTHETIC_OUTPUT_DIR

    object_store = None
    if arguments.object_store:
        # 합성 데이터는 원본과 파일 이름이 같아서, 같은 버킷에 올리면 원본 객체를 덮어씁니다. 버킷을 나눕니다.
        bucket = SYNTHETIC_BUCKET if arguments.synthetic else DEFAULT_BUCKET
        object_store = ObjectStore.from_environment(bucket=bucket)
    warehouse = None
    if arguments.warehouse:
        # 합성 데이터는 원본과 같은 표에 넣으면 덮어쓰므로 스키마를 나눕니다 (객체 저장소 버킷과 같은 이유).
        warehouse = Warehouse.from_environment(schema=SYNTHETIC_RAW_SCHEMA if arguments.synthetic else RAW_SCHEMA)
    tables = run_pipeline(arguments.raw_dir, arguments.output_dir, arguments.data_dir, object_store, warehouse=warehouse)
    bronze_dir, silver_dir, gold_dir = layer_dirs(arguments.data_dir)
    print(f"Bronze: {bronze_dir}\nSilver: {silver_dir}\nGold:   {gold_dir}")
    print("\n[계층 사이 대사]")
    print(tables["quality_report"][["검사", "계층", "결과", "실제값"]].to_string(index=False))
    if arguments.compare:
        print("\n[공모전 결과표와 비교]")
        print(compare_with_published(arguments.output_dir).to_string(index=False))


if __name__ == "__main__":
    main()
