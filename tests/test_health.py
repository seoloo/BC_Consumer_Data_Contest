"""운영 상태 점검(health) 테스트.

판단 함수(judge_*)는 읽어 온 값만 보고 정하므로 서비스 없이 확인하고,
실제 서비스 전체 점검은 docker compose가 떠 있을 때만 돕니다.
"""

from datetime import datetime, timezone

import pytest

from future_stress import health
from future_stress.health import FAIL, OK, WARN


def test_env_lists_only_missing_names():
    assert health.judge_env([]).status == OK
    missing = health.judge_env(["POSTGRES_PASSWORD"])
    assert missing.status == FAIL and "POSTGRES_PASSWORD" in missing.detail and "local_env" in missing.action


def test_object_store_needs_manifest_in_latest_batch():
    keys = ["batch_month=202605/_manifest.json", "batch_month=202606/card_spending/a.csv"]
    assert health.latest_batch(keys) == 202606
    stopped_midway = health.judge_object_store(keys, "bronze")       # 최근 배치에 영수증이 없음 = 올리다 멈춤
    assert stopped_midway.status == FAIL and "202606" in stopped_midway.detail

    keys.append("batch_month=202606/_manifest.json")
    assert health.judge_object_store(keys, "bronze").status == OK
    assert health.judge_object_store([], "bronze").status == FAIL


def test_new_raw_batch_not_yet_stored_is_a_warning():
    assert health.judge_new_batch(202606, 202606).status == OK
    waiting = health.judge_new_batch(202607, 202606)
    assert waiting.status == WARN and "batch_month=202607" in waiting.action
    assert health.judge_new_batch(None, 202606).status == WARN        # 원본이 없는 PC
    assert "판단하지 않음" in health.judge_new_batch(202606, None, store_reachable=False).detail


def test_raw_needs_every_table_logged():
    when = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    rows = [{"table_name": "card_spending", "row_count": 10, "status": "신규", "loaded_at": when}]
    assert health.judge_raw(None, "raw").status == FAIL                # 한 번도 적재하지 않음
    assert health.judge_raw(rows, "raw").status == FAIL                # future_population 기록 없음
    rows.append({"table_name": "future_population", "row_count": 20, "status": "변경 없음", "loaded_at": when})
    loaded = health.judge_raw(rows, "raw")
    assert loaded.status == OK and "2026-10-21 22:00" in loaded.detail  # 한국 시간으로


def test_gold_needs_every_dbt_model_with_rows():
    assert len(health.GOLD_TABLES) == 10                                # dbt/models/gold/gold_*.sql (분석 기간 표 포함)
    counts = {table: 5 for table in health.GOLD_TABLES}
    assert health.judge_gold(counts, "gold").status == OK
    counts[health.GOLD_TABLES[0]] = 0
    empty = health.judge_gold(counts, "gold")
    assert empty.status == FAIL and "비어 있음" in empty.detail and empty.action.endswith("dbt build")
    del counts[health.GOLD_TABLES[0]]
    synthetic = health.judge_gold(counts, "synthetic_gold")
    assert "없음" in synthetic.detail and "--target synthetic" in synthetic.action


def test_airflow_failed_run_names_the_step():
    run = {"run_id": "manual__x", "state": "failed", "logical_date": None}
    failed = health.judge_airflow(run, ["upload"], web_up=True)
    assert failed.status == FAIL and "upload" in failed.detail
    assert health.judge_airflow({**run, "state": "success"}, [], web_up=True).status == OK
    assert health.judge_airflow({**run, "state": "success"}, [], web_up=False).status == WARN   # 꺼져 있으면 자동 실행 안 됨
    assert health.judge_airflow(None, [], web_up=False).status == WARN                          # 한 번도 안 띄움


def test_report_aligns_korean_names_and_shows_actions_only_for_problems():
    checks = [health.Check("gold 표", OK, "9개 표"), health.Check("객체 저장소", FAIL, "연결할 수 없음", "docker compose up -d")]
    lines = health.report(checks).splitlines()
    # 한글을 두 칸으로 세었을 때 내용이 같은 칸에서 시작
    assert (health.display_width(lines[0][:lines[0].index("9개")])
            == health.display_width(lines[1][:lines[1].index("연결")]))
    assert lines[2].strip() == "→ docker compose up -d"
    assert len(lines) == 3


@pytest.mark.integration
def test_synthetic_services_are_healthy():
    checks = health.run_checks("합성")
    if any(check.name in ("객체 저장소", "PostgreSQL") and "연결할 수 없음" in check.detail for check in checks):
        pytest.skip("docker compose 서비스가 떠 있지 않음")
    if any(check.name == "gold 표" and check.status == FAIL for check in checks):
        pytest.skip("합성 dbt build 전")
    assert [check.status for check in checks if check.status == FAIL] == []
