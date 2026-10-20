"""전체 분석을 메달리온 계층 순서(Bronze → Silver → Gold)로 실행합니다.

실행 방법 (저장소 루트에서)
    .venv/Scripts/python -m future_stress.pipeline              # 계층별 저장 + output/에 결과 CSV
    .venv/Scripts/python -m future_stress.pipeline --compare    # 실행 후 results/의 발표 수치와 비교

실행 순서
    1. Bronze   data/raw의 원본을 그대로 복사하고 적재 영수증을 남김     medallion.build_bronze
    2. Silver   정제 · 표준화한 표를 Parquet으로 저장                   medallion.build_silver
    3. Gold     Silver만 읽어 Stress · 4유형 · 검증 · 전략 계산          medallion.build_gold
    4. 대사     계층 사이 건수 · 금액이 맞는지 검사, 실패하면 멈춤        medallion.run_quality_checks
    5. 내보내기  발표 결과와 같은 형식의 CSV를 output/에 저장

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
    run_quality_checks,
)

# 발표 결과 외에 output/에 함께 내보내는 Gold 표 (사람이 엑셀로 열어 보기 위한 용도)
EXTRA_OUTPUT_TABLES = ["region_validation", "market_type_counts", "seoul_defense_strategy", "illusion_rebalancing"]


def layer_dirs(data_dir=None):
    """data_dir 아래의 bronze · silver · gold 폴더. 기본값은 config에 정한 data/ 폴더입니다."""
    if data_dir is None:
        return config.BRONZE_DIR, config.SILVER_DIR, config.GOLD_DIR
    data_dir = Path(data_dir)
    return data_dir / "bronze", data_dir / "silver", data_dir / "gold"


def run_pipeline(raw_dir=None, output_dir=None, data_dir=None):
    """원본에서 최종 결과표까지 메달리온 계층 순서로 실행합니다.

    Args:
        raw_dir: 원본 폴더 (기본 data/raw).
        output_dir: 발표 형식 CSV를 저장할 폴더 (기본 output/).
        data_dir: bronze · silver · gold를 만들 폴더 (기본 data/). 테스트에서는 임시 폴더를 넘깁니다.

    Returns:
        {표 이름: DataFrame} · Gold 표 전체와 'quality_report'
    """
    output_dir = Path(output_dir or config.OUTPUT_DIR)
    bronze_dir, silver_dir, gold_dir = layer_dirs(data_dir)

    build_bronze(raw_dir, bronze_dir)
    silver = build_silver(bronze_dir, silver_dir)
    gold = build_gold(silver_dir, gold_dir)

    quality_report = run_quality_checks(bronze_dir, silver, gold)
    save_csv(quality_report, gold_dir / "_quality_report.csv")
    save_csv(quality_report, output_dir / "quality_report.csv")
    failed = quality_report[quality_report["결과"] == "실패"]
    if not failed.empty:
        # 대사가 맞지 않으면 결과를 내보내지 않고 멈춥니다. 틀린 숫자가 발표 결과처럼 쓰이는 것을 막기 위해서입니다.
        raise DataQualityError("계층 사이 대사 실패:\n" + failed.to_string(index=False))

    for name in PUBLISHED_TABLES + EXTRA_OUTPUT_TABLES:
        save_csv(gold[name], output_dir / f"{name}.csv")
    return {**gold, "quality_report": quality_report}


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
    parser = argparse.ArgumentParser(description="미래 소비기반 스트레스 테스트 파이프라인 (Bronze → Silver → Gold)")
    parser.add_argument("--raw-dir", default=config.RAW_DATA_DIR, help="원본 데이터 폴더 (기본: data/raw)")
    parser.add_argument("--output-dir", default=config.OUTPUT_DIR, help="결과 CSV 저장 폴더 (기본: output)")
    parser.add_argument("--data-dir", default=None, help="bronze · silver · gold를 만들 폴더 (기본: data)")
    parser.add_argument("--compare", action="store_true", help="실행 후 results/의 발표 수치와 비교")
    arguments = parser.parse_args()

    tables = run_pipeline(arguments.raw_dir, arguments.output_dir, arguments.data_dir)
    bronze_dir, silver_dir, gold_dir = layer_dirs(arguments.data_dir)
    print(f"Bronze: {bronze_dir}\nSilver: {silver_dir}\nGold:   {gold_dir}")
    print("\n[계층 사이 대사]")
    print(tables["quality_report"][["검사", "계층", "결과", "실제값"]].to_string(index=False))
    if arguments.compare:
        print("\n[발표 결과와 비교]")
        print(compare_with_published(arguments.output_dir).to_string(index=False))


if __name__ == "__main__":
    main()
