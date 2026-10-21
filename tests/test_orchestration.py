"""Airflow 월 배치 작업 함수 테스트 (Airflow 없이).

DAG 자체가 제대로 읽히는지는 Airflow 컨테이너 안에서 `airflow dags list-import-errors`로 확인하고,
여기서는 DAG가 기대는 판단(배치 월 계산, 새 원본이 있나)을 확인합니다.
"""

from datetime import datetime, timezone

from future_stress.orchestration import batch_month_for_run, batch_month_of, has_new_batch, raw_batch_month


def test_batch_month_of_date():
    assert batch_month_of(datetime(2026, 6, 1)) == 202606
    assert batch_month_of(datetime(2026, 12, 31)) == 202612


def test_batch_month_for_run_is_previous_month_in_korea():
    """한국 시간 7월 1일 0시 = UTC 6월 30일 15시. UTC 날짜로 읽으면 6월 → 지난달 5월로 틀리게 나옵니다."""
    run_time_utc = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    assert batch_month_for_run(run_time_utc) == 202606
    assert batch_month_for_run(datetime(2026, 1, 1)) == 202512          # 1월 실행 → 지난해 12월


def test_raw_batch_month_reads_end_month_from_file_name(tmp_path):
    assert raw_batch_month(tmp_path) is None                         # 원본이 아직 없음
    (tmp_path / "bc_card_202601_202606.csv").write_text("x", encoding="utf-8")
    assert raw_batch_month(tmp_path) == 202606                        # 6개월이 한 번에 온 묶음 → 끝월
    (tmp_path / "bc_card_202607_202607.csv").write_text("x", encoding="utf-8")
    assert raw_batch_month(tmp_path) == 202607                        # 다음 달 원본이 오면 가장 최근 달


def test_only_the_arrived_batch_is_processed(synthetic_raw_dir):
    """합성 원본도 공모전처럼 6개월 묶음 하나 → 6월만 처리하고 1 ~ 5월은 건너뜀."""
    processed = [month for month in range(202601, 202607) if has_new_batch(month, synthetic_raw_dir)]
    assert processed == [202606]
