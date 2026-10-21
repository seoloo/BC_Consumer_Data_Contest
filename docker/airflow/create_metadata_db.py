"""Airflow 기록용 데이터베이스(airflow)가 없으면 만듭니다. Airflow를 띄우기 직전에 한 번 실행됩니다.

왜 따로 만드나요?
    Airflow는 실행 기록 · 상태를 자기 데이터베이스에 저장합니다. 분석 데이터(future_stress)와 섞이지 않도록
    같은 PostgreSQL 서버 안에 데이터베이스를 하나 더 둡니다. PostgreSQL 컨테이너를 하나 더 띄우는 것보다 가볍습니다.
"""

import os

import psycopg

params = {
    "host": os.environ["WAREHOUSE_HOST"], "port": os.environ["WAREHOUSE_PORT"],
    "user": os.environ["POSTGRES_USER"], "password": os.environ["POSTGRES_PASSWORD"],
    "dbname": os.environ["POSTGRES_DB"], "autocommit": True,   # CREATE DATABASE는 트랜잭션 안에서 못 함
}
with psycopg.connect(**params) as connection:
    exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = 'airflow'").fetchone()
    if not exists:
        connection.execute("CREATE DATABASE airflow")
    print("Airflow 기록용 데이터베이스: " + ("이미 있음" if exists else "새로 만듦"))
