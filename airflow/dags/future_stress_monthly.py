"""월 배치 DAG · 원본 도착 → Bronze → 객체 저장소 → raw → dbt · 파이썬 → 비교 (Phase 4-2)

DAG(작업 흐름)는 '무엇을 어떤 순서로'만 적습니다. 실제 일은 src/future_stress/ops/orchestration.py의 함수가 합니다.
기록: docs/notes/18_airflow.md

    has_new_batch ─▶ build_bronze ─▶ upload ─▶ download ─▶ load_raw ─┬▶ dbt_build ─────┬▶ compare
                                                                      └▶ python_layers ─┘
    (dbt와 파이썬은 서로 다른 곳에 쓰므로 동시에 돌고, 둘 다 끝나야 비교합니다)

- 매달 1일 0시(한국 시간)에 '지난달' 배치를 처리합니다 (7월 1일 실행 → 배치 월 202606).
- 손으로 돌릴 때는 batch_month 값을 직접 줄 수 있습니다 (예: 202606).
- 이 달 원본이 없으면 has_new_batch가 False → 뒤 단계는 '건너뜀'(skipped)으로 끝납니다. 실패가 아닙니다.
- 다시 돌려도 결과가 같습니다 (지문이 같으면 '변경 없음').
"""

import os
from datetime import datetime, timedelta

from airflow.sdk import Param, dag, get_current_context, task

from future_stress.ops import orchestration

DBT_EXECUTABLE = os.getenv("DBT_EXECUTABLE", "dbt")


def current_batch_month():
    """손으로 준 batch_month가 있으면 그 값, 없으면 실행 시각(한국 시간)의 지난달."""
    context = get_current_context()
    given = context["params"].get("batch_month")
    if given:
        return int(given)
    return orchestration.batch_month_for_run(context["data_interval_start"])


@dag(
    dag_id="future_stress_monthly",
    description="미래 소비기반 스트레스 테스트 · 월 배치",
    schedule="@monthly",
    start_date=datetime(2026, 1, 1),
    catchup=False,                 # 켤 때 지난달들을 한꺼번에 돌리지 않음. 지난달은 backfill로 골라서 돌림
    max_active_runs=1,             # 같은 data/ 폴더를 쓰므로 한 번에 하나만
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},   # 일시적인 연결 오류는 한 번 더
    params={"batch_month": Param(None, type=["null", "integer"], description="처리할 배치 월 (예: 202606). 비우면 실행 구간의 달")},
    tags=["future_stress", "monthly"],
)
def future_stress_monthly():

    @task.short_circuit
    def has_new_batch():
        batch_month = current_batch_month()
        found = orchestration.raw_batch_month()
        print(f"이번 배치 월 {batch_month}, 원본 폴더의 배치 월 {found}")
        return orchestration.has_new_batch(batch_month)

    @task
    def build_bronze():
        return orchestration.step_build_bronze()

    @task
    def upload():
        return orchestration.step_upload(current_batch_month())

    @task
    def download():
        return orchestration.step_download(current_batch_month())

    @task
    def load_raw():
        return orchestration.step_load_raw()

    @task
    def dbt_build():
        return orchestration.step_dbt_build(DBT_EXECUTABLE)

    @task
    def python_layers(upload_summary, raw_summary):
        return orchestration.step_python_layers(current_batch_month(), upload_summary, raw_summary)

    @task
    def compare():
        return orchestration.step_compare()

    uploaded = upload()
    downloaded = download()
    raw_loaded = load_raw()
    has_new_batch() >> build_bronze() >> uploaded >> downloaded >> raw_loaded
    dbt_done = dbt_build()
    raw_loaded >> dbt_done
    python_done = python_layers(uploaded, raw_loaded)
    [dbt_done, python_done] >> compare()


future_stress_monthly()
