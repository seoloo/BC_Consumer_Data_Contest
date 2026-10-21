# Airflow 이미지 (Phase 4-2, 기록: docs/notes/18_airflow.md)
#
# - 이 PC에 이미 있는 공식 이미지(3.1.7, Python 3.12) 위에 이 프로젝트의 의존성을 얹습니다.
#   Airflow 버전이 pip 설치 중에 바뀌지 않도록 apache-airflow도 같은 버전으로 함께 고정합니다.
# - dbt는 Airflow와 의존성이 부딪히지 않도록 별도 가상환경에 둡니다. dbt 컨테이너(ghcr.io/dbt-labs/dbt-postgres:1.9.0)와 같은 1.9.0.
# - 코드(src, dags, dbt)는 이미지에 굽지 않고 docker-compose에서 폴더로 연결해, 고치면 바로 반영됩니다.
FROM apache/airflow:3.1.7-python3.12

COPY requirements-airflow.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir "apache-airflow==3.1.7" -r /tmp/requirements-airflow.txt \
 && python -m venv /home/airflow/dbt-venv \
 && /home/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core==1.9.0" "dbt-postgres==1.9.0"

ENV DBT_EXECUTABLE=/home/airflow/dbt-venv/bin/dbt \
    PYTHONPATH=/opt/project/src
