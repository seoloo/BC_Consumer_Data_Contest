"""새 달 원본이 왔을 때 (월 배치) 테스트.

1. 분석 기간 = 마지막 달에서 거꾸로 6개월 (해가 바뀌어도)
2. BC카드 원본 여러 파일 합치기 · 같은 달은 늦게 온 파일이 이김
3. 합성 '다음 달' 원본으로 파이프라인 전체: 기간이 옮겨 가고, Gold는 그 기간의 결제만 씀
"""

import shutil

import pandas as pd
import pytest

from future_stress import config
from future_stress.analysis.card_spending import analysis_months, card_file_end_month, load_card_files
from future_stress.medallion import latest_card_batch
from future_stress.pipeline import run_pipeline
from future_stress.ingest.synthetic import write_synthetic_next_month

COLUMNS = ["STRD_YYMM", "SIDO_NM", "CCG_NM", "GENDER_CD", "AGE_CD", "TP_BUZ_NO", "TP_BUZ_NM", "amt", "cnt"]


def card_file(folder, name, rows):
    path = folder / name
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def test_months_ending_crosses_year_boundary():
    assert config.months_ending(202606) == config.ANALYSIS_MONTHS            # 원본은 그대로 1 ~ 6월
    assert config.months_ending(202602, 3) == [202512, 202601, 202602]
    assert config.months_ending(202607) == [202602, 202603, 202604, 202605, 202606, 202607]


def test_analysis_months_follow_last_month_in_data():
    card = pd.DataFrame({"기준년월": [202601, 202604, 202607]})               # 중간 달이 비어 있어도
    assert analysis_months(card) == [202602, 202603, 202604, 202605, 202606, 202607]


def test_later_file_replaces_overlapping_month(tmp_path):
    """제공처가 6월 값을 고쳐 7월 묶음에 다시 보내면, 6월은 두 번 더해지지 않고 7월 묶음의 값으로 바뀌어야 합니다."""
    first = card_file(tmp_path, "bc_card_202601_202606.csv", [
        [202605, "서울특별시", "성동구", "1", "3", "8001", "편의점", 100, 20],
        [202606, "서울특별시", "성동구", "1", "3", "8001", "편의점", 200, 20],
    ])
    second = card_file(tmp_path, "bc_card_202606_202607.csv", [
        [202606, "서울특별시", "성동구", "1", "3", "8001", "편의점", 250, 20],
        [202607, "서울특별시", "성동구", "1", "3", "8001", "편의점", 300, 20],
    ])
    merged = load_card_files([second, first])                                   # 넘기는 순서와 상관없이
    assert merged.groupby("STRD_YYMM")["amt"].sum().to_dict() == {202605: 100, 202606: 250, 202607: 300}
    assert card_file_end_month(second) == 202607
    assert latest_card_batch(tmp_path) == 202607


def test_synthetic_next_month_follows_provider_rules(tmp_path):
    path = write_synthetic_next_month(tmp_path, 202607)
    table = pd.read_csv(path)
    assert path.name == "bc_card_202607_202607.csv"
    assert set(table["STRD_YYMM"]) == {202607}
    assert table["cnt"].min() >= config.MIN_CARD_PAYMENT_COUNT                 # 원본처럼 10건 이하 칸 없음
    assert write_synthetic_next_month(tmp_path, 202607).read_bytes() == path.read_bytes()   # 같은 달은 같은 파일


@pytest.fixture(scope="module")
def next_month_run(tmp_path_factory, synthetic_raw_dir):
    """합성 6개월 원본 + 7월 원본 하나로 파이프라인 전체를 돌립니다 (원래 합성 폴더는 건드리지 않음)."""
    root = tmp_path_factory.mktemp("next_month")
    raw_dir = shutil.copytree(synthetic_raw_dir, root / "raw")
    write_synthetic_next_month(raw_dir, 202607)
    tables = run_pipeline(raw_dir, root / "output", root / "data")
    return {"tables": tables, "data": root / "data"}


def test_window_moves_and_gold_uses_only_window(next_month_run):
    window = next_month_run["tables"]["analysis_window"].iloc[0]
    assert (window["시작월"], window["끝월"], window["개월수"]) == (202602, 202607, 6)

    silver = pd.read_parquet(next_month_run["data"] / "silver" / "card_spending.parquet")
    assert sorted(silver["기준년월"].unique()) == list(range(202601, 202608))  # Silver에는 7개월 모두 쌓임
    in_window = silver[silver["기준년월"].between(202602, 202607)]["이용금액"].sum()
    gold = next_month_run["tables"]["age_spending_structure"]["이용금액"].sum()
    assert gold == in_window and gold < silver["이용금액"].sum()               # Gold는 1월을 빼고 계산

    report = next_month_run["tables"]["quality_report"]
    assert "실패" not in set(report["결과"])
