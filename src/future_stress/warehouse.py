"""Bronze 원본을 PostgreSQL의 raw 스키마에 적재합니다. (Phase 3-1)

왜 필요한가요?
    지금까지 Silver · Gold는 파이썬 함수가 만든 Parquet 파일이었습니다. 파일은 이 PC의 파이썬에서만 읽기 쉽고,
    다른 도구(dbt, 대시보드, SQL 조회)에서 쓰기 어렵습니다. Phase 3에서는 Silver · Gold를 dbt(SQL 모델)로 옮기는데,
    그 출발점이 되는 것이 데이터베이스 안의 원본 표(raw 스키마)입니다.

무엇을 파이썬이 하고, 무엇을 dbt가 하나요?
    파이썬(여기): 파일을 표로 읽기만 합니다. 인코딩, 닫히지 않은 따옴표, 병합 셀처럼 '파일 형식' 문제는
                  SQL로 다루기 어려워서 파이썬이 맡습니다. 값과 표기는 손대지 않습니다.
    dbt(3-2부터): 개인 결제만 남기기, 코드 → 이름, 5세 구간 고르기, 연령대 바꾸기 같은 '규칙'을 SQL로 합니다.

raw에 넣는 표 (Stress · 4유형을 만드는 데 필요한 원본 두 가지)
    raw.card_spending       BC카드 결제 CSV 그대로. 개인이 아닌 결제(성별 3 · x)도 모두 넣습니다.
    raw.future_population   서울 · 부산 · 경기 장래인구. 5세 · 1세 · 합계 행과 원본 표기를 그대로 두고,
                            연도 열만 세로로 풀었습니다(연도마다 열이 있으면 SQL에서 다루기 어려움).
    raw._load_log           적재할 때마다 한 줄씩: 표 · 원본 지문 · 행 수 · 합계 · 상태 · 시각

지키는 것
    1. 같은 원본이면 다시 넣지 않습니다 (원본 지문과 행 수가 지난 적재와 같으면 '변경 없음').
    2. 다시 넣을 때는 한 트랜잭션 안에서 표를 지우고 새로 만듭니다. 중간에 실패하면 이전 상태가 그대로 남습니다.
    3. 넣은 뒤 DB의 행 수 · 합계를 원본과 맞춰 봅니다. 다르면 DataQualityError로 되돌리고 멈춥니다.
    4. 합성 데이터는 raw_synthetic 스키마에 넣습니다 (같은 표에 넣으면 원본을 덮어쓰기 때문).

실행 방법 (저장소 루트에서, docker compose up -d 뒤)
    .venv\\Scripts\\python -m future_stress.warehouse load-raw     # data/bronze → raw 스키마
    .venv\\Scripts\\python -m future_stress.warehouse status       # 표마다 행 수와 마지막 적재
    .venv\\Scripts\\python -m future_stress.pipeline --warehouse   # 파이프라인 실행 중에 함께 적재 + 대사 보고서에 기록
"""

import argparse
import csv
import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

from . import config
from .card_spending import load_card_files
from .io_utils import read_csv_with_encoding_fallback, read_env_value, read_parquet
from .local_env import DEFAULT_POSTGRES_DB, DEFAULT_POSTGRES_PORT, DEFAULT_POSTGRES_USER
from .medallion import DataQualityError, bronze_path, file_fingerprint
from .population import POPULATION_YEARS

RAW_SCHEMA = "raw"
SYNTHETIC_RAW_SCHEMA = "raw_synthetic"


@dataclass(frozen=True)
class RawTable:
    """raw 스키마의 표 하나. sum_column은 적재 뒤 원본과 합계를 맞춰 볼 열입니다."""
    name: str
    columns: tuple          # ((열 이름, PostgreSQL 타입), ...)
    sum_column: str
    description: str


CARD_TABLE = RawTable(
    "card_spending",
    (("strd_yymm", "integer"), ("sido_nm", "text"), ("ccg_nm", "text"), ("gender_cd", "text"),
     ("age_cd", "text"), ("tp_buz_no", "text"), ("tp_buz_nm", "text"), ("amt", "bigint"), ("cnt", "bigint"),
     ("source_file", "text")),
    "amt",
    "BC카드 결제 원본 (CSV 그대로, 열 이름만 소문자). 배치마다 온 파일을 합침(같은 달은 늦게 온 파일). 개인이 아닌 결제(성별 3 · x) 포함",
)
FUTURE_TABLE = RawTable(
    "future_population",
    (("source_file", "text"), ("province", "text"), ("region", "text"), ("sex", "text"),
     ("age_label", "text"), ("age_detail", "text"), ("year", "integer"), ("population", "bigint")),
    "population",
    "서울 · 부산 · 경기 장래인구 원본 (표기 그대로, 연도 열만 세로로). age_detail은 KOSIS 엑셀의 연령별(2)",
)

# 장래인구 원본 → 시도. 서울 CSV에는 시도 열이 없어서 어느 파일에서 왔는지로 정합니다.
FUTURE_POPULATION_SOURCES = {"seoul_future": "서울특별시", "busan_future": "부산광역시", "gyeonggi_future": "경기도"}


# ===========================================================================
# 파일 → 표 (값과 표기는 그대로)
# ===========================================================================

def card_spending_frame(bronze_dir):
    """BC카드 CSV(배치마다 한 파일)를 raw.card_spending 모양으로. 모두 문자로 읽은 뒤 숫자 열만 바꿉니다.

    왜 모두 문자로 읽나요? 성별 · 연령 코드에 'x'가 섞여 있어, 숫자로 읽으면 열 타입이 흔들리기 때문입니다 (07 참고).
    같은 달이 두 파일에 있으면 늦게 온 파일의 그 달만 씁니다 (card_spending.load_card_files, 파이썬 Silver와 같은 규칙).
    source_file: 행마다 어느 파일에서 왔는지 남겨, 나중에 값이 이상하면 원본 파일까지 거슬러 갈 수 있게 합니다.
    """
    def read_text_columns(path):
        return read_csv_with_encoding_fallback(path, dtype=str).assign(source_file=Path(path).name)

    raw = load_card_files(bronze_path(bronze_dir, "card"), read=read_text_columns)
    frame = raw.rename(columns=str.lower)[[name for name, _ in CARD_TABLE.columns]].copy()
    for column in ("strd_yymm", "amt", "cnt"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("Int64")
    return frame


def seoul_future_frame(path):
    """서울 장래인구 CSV → 세로 표. 닫히지 않은 따옴표 때문에 pandas 대신 csv 모듈로 읽습니다 (population.py 참고)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    wide = pd.DataFrame(rows[1:], columns=[name.strip() for name in rows[0]])
    year_columns = [name for name in wide.columns if name.endswith(" 년")]
    long = wide.melt(id_vars=["자치구별", "성별", "연령별"], value_vars=year_columns, var_name="연도", value_name="인구")
    return pd.DataFrame({
        "region": long["자치구별"], "sex": long["성별"], "age_label": long["연령별"], "age_detail": None,
        "year": long["연도"].str.replace(" 년", "", regex=False).astype(int),
        "population": pd.to_numeric(long["인구"], errors="coerce"),
    })


def kosis_future_frame(path):
    """부산 · 경기 장래인구 엑셀(KOSIS 형식) → 세로 표.

    병합 셀이라 시군구 · 성별 · 연령별(1)은 블록 첫 행에만 값이 있습니다. 엑셀에서 보이는 그대로 위의 값을 아래로 채웁니다.
    연령별(2)는 '소계'(5세 구간 합) 또는 '0세' 같은 1세 단위 값입니다.
    """
    wide = pd.read_excel(path, sheet_name=0, header=0)
    wide[["시군구별", "성별", "연령별(1)"]] = wide[["시군구별", "성별", "연령별(1)"]].ffill()
    year_columns = [name for name in wide.columns if str(name).isdigit()]
    long = wide.melt(id_vars=["시군구별", "성별", "연령별(1)", "연령별(2)"], value_vars=year_columns,
                     var_name="연도", value_name="인구")
    return pd.DataFrame({
        "region": long["시군구별"], "sex": long["성별"], "age_label": long["연령별(1)"], "age_detail": long["연령별(2)"],
        "year": long["연도"].astype(int), "population": pd.to_numeric(long["인구"], errors="coerce"),
    })


def future_population_frame(bronze_dir):
    """서울 · 부산 · 경기 장래인구를 raw.future_population 모양으로 합칩니다."""
    frames = []
    for source_key, province in FUTURE_POPULATION_SOURCES.items():
        path = bronze_path(bronze_dir, source_key)
        frame = seoul_future_frame(path) if path.suffix == ".csv" else kosis_future_frame(path)
        frame.insert(0, "province", province)
        frame.insert(0, "source_file", path.name)
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    combined["population"] = combined["population"].round().astype("Int64")
    return combined[[name for name, _ in FUTURE_TABLE.columns]]


def combined_fingerprint(paths):
    """여러 원본 파일의 지문을 하나로. 파일 하나만 바뀌어도 값이 바뀝니다."""
    return hashlib.sha256("\n".join(sorted(file_fingerprint(path) for path in paths)).encode()).hexdigest()


def raw_sources(bronze_dir):
    """적재할 표 · 그 표를 만드는 함수 · 원본 지문."""
    future_paths = [bronze_path(bronze_dir, key) for key in FUTURE_POPULATION_SOURCES]
    return [
        (CARD_TABLE, lambda: card_spending_frame(bronze_dir), combined_fingerprint(bronze_path(bronze_dir, "card"))),
        (FUTURE_TABLE, lambda: future_population_frame(bronze_dir), combined_fingerprint(future_paths)),
    ]


# ===========================================================================
# PostgreSQL에 넣기
# ===========================================================================

class Warehouse:
    """PostgreSQL 연결 창구.

    연결을 만드는 함수를 밖에서 받습니다(의존성 주입). 스키마 이름도 받아서, 원본은 raw, 합성 데이터는 raw_synthetic에 넣습니다.
    """

    def __init__(self, connect, schema=RAW_SCHEMA):
        self.connect = connect
        self.schema = schema

    @classmethod
    def from_environment(cls, env_file=None, schema=RAW_SCHEMA, dbname=None):
        """.env의 POSTGRES_* 값으로 로컬 PostgreSQL(docker compose의 warehouse)에 연결합니다.

        dbname: 같은 서버의 다른 데이터베이스 (예: Airflow 기록용 'airflow'). 없으면 POSTGRES_DB.
        """
        def optional(name, default):
            try:
                return read_env_value(name, env_file)
            except ValueError:
                return default

        # 이 PC에서는 127.0.0.1:55532, 컨테이너 안(Airflow)에서는 서비스 이름 warehouse:5432로 접속합니다.
        # WAREHOUSE_HOST · WAREHOUSE_PORT는 docker-compose.yml이 컨테이너에만 넣어 주는 값입니다.
        params = {
            "host": os.getenv("WAREHOUSE_HOST", "127.0.0.1"),
            "port": os.getenv("WAREHOUSE_PORT") or optional("POSTGRES_PORT", DEFAULT_POSTGRES_PORT),
            "dbname": dbname or optional("POSTGRES_DB", DEFAULT_POSTGRES_DB),
            "user": optional("POSTGRES_USER", DEFAULT_POSTGRES_USER),
            "password": read_env_value("POSTGRES_PASSWORD", env_file),
            "connect_timeout": 5,
        }
        return cls(lambda: psycopg.connect(**params), schema)

    def load(self, table, build_frame, source_fingerprint):
        """표 하나를 적재합니다. 원본이 지난번과 같으면 건너뜁니다.

        Returns:
            {'표', '상태'(신규/변경/변경 없음), '행 수', '합계'}
        """
        qualified = f"{self.schema}.{table.name}"
        # with 블록이 정상으로 끝나면 commit, 예외가 나면 rollback 됩니다. 그래서 대사가 틀리면 이전 표가 그대로 남습니다.
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.schema}._load_log (
                    table_name text, source_sha256 text, row_count bigint, sum_value numeric,
                    status text, loaded_at timestamptz DEFAULT now())""")
            cursor.execute(f"SELECT source_sha256, row_count, sum_value FROM {self.schema}._load_log "
                           "WHERE table_name = %s ORDER BY loaded_at DESC LIMIT 1", (table.name,))
            last = cursor.fetchone()
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (qualified,))
            table_exists = cursor.fetchone()[0]

            if last and table_exists and last[0] == source_fingerprint:
                current_count, current_sum = self._count_and_sum(cursor, qualified, table.sum_column)
                if (current_count, current_sum) == (last[1], last[2]):
                    self._log(cursor, table.name, source_fingerprint, current_count, current_sum, "변경 없음")
                    return {"표": qualified, "상태": "변경 없음", "행 수": current_count, "합계": current_sum}

            frame = build_frame()
            column_sql = ", ".join(f"{name} {kind}" for name, kind in table.columns)
            cursor.execute(f"DROP TABLE IF EXISTS {qualified}")
            cursor.execute(f"CREATE TABLE {qualified} ({column_sql})")
            # COMMENT 문은 값 자리(%s)를 받지 않아서, 따옴표 처리를 psycopg에 맡기는 sql.Literal로 넣습니다.
            cursor.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(sql.SQL(qualified), sql.Literal(table.description)))
            self._copy(cursor, qualified, frame)

            # 대사: DB에 들어간 행 수 · 합계가 원본 표와 같은가
            loaded_count, loaded_sum = self._count_and_sum(cursor, qualified, table.sum_column)
            expected_count, expected_sum = len(frame), int(frame[table.sum_column].sum())
            if (loaded_count, loaded_sum) != (expected_count, expected_sum):
                raise DataQualityError(
                    f"{qualified} 적재 대사 실패: 원본 {expected_count:,}행 · 합계 {expected_sum:,} / "
                    f"DB {loaded_count:,}행 · 합계 {loaded_sum:,} (이전 표로 되돌림)")
            status = "신규" if last is None else "변경"
            self._log(cursor, table.name, source_fingerprint, loaded_count, loaded_sum, status)
            return {"표": qualified, "상태": status, "행 수": loaded_count, "합계": loaded_sum}

    @staticmethod
    def _count_and_sum(cursor, qualified, sum_column):
        cursor.execute(f"SELECT count(*), coalesce(sum({sum_column}), 0) FROM {qualified}")
        count, total = cursor.fetchone()
        return int(count), int(total)

    @staticmethod
    def _copy(cursor, qualified, frame):
        """COPY로 한 번에 넣습니다. 한 행씩 INSERT하면 수십만 행에서 수십 배 느립니다.

        CSV로 바꿔 보내는데, 빈 칸(따옴표 없는 빈 값)은 PostgreSQL이 NULL로 읽습니다.
        """
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False, header=False)
        columns = ", ".join(frame.columns)
        with cursor.copy(f"COPY {qualified} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
            copy.write(buffer.getvalue())

    def _log(self, cursor, table_name, fingerprint, row_count, sum_value, status):
        cursor.execute(f"INSERT INTO {self.schema}._load_log (table_name, source_sha256, row_count, sum_value, status) "
                       "VALUES (%s, %s, %s, %s, %s)", (table_name, fingerprint, row_count, sum_value, status))

    def status(self):
        """표마다 지금 행 수와 마지막 적재 기록."""
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{self.schema}._load_log",))
            if not cursor.fetchone()[0]:
                return pd.DataFrame(columns=["표", "상태", "행 수", "합계", "적재 시각"])
            cursor.execute(f"""
                SELECT DISTINCT ON (table_name) table_name, status, row_count, sum_value, loaded_at
                FROM {self.schema}._load_log ORDER BY table_name, loaded_at DESC""")
            rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=["표", "상태", "행 수", "합계", "적재 시각"])


def load_raw(bronze_dir, warehouse):
    """Bronze의 원본을 raw 스키마에 적재합니다. Returns: 표 | 상태 | 행 수 | 합계"""
    return pd.DataFrame([warehouse.load(table, build, fingerprint)
                         for table, build, fingerprint in raw_sources(bronze_dir)])


# ===========================================================================
# dbt Silver와 파이썬 Silver 비교 (Phase 3-2)
# ===========================================================================

# 파이썬 Silver 열 이름 → dbt Silver 열 이름. dbt는 SQL에서 다루기 쉬운 영어 열 이름을 씁니다.
SILVER_COLUMN_MAPS = {
    "card_spending": {
        "dbt_table": "silver_card_spending",
        "keys": {"기준년월": "base_month", "시도": "province", "시군구": "district", "성별": "sex",
                 "연령대": "age_group", "업종코드": "industry_code", "업종명": "industry_name"},
        "values": {"이용금액": "amount", "이용건수": "payment_count"},
    },
    "future_population": {
        "dbt_table": "silver_future_population",
        "keys": {"시도": "province", "시군구": "district", "연령대": "age_group"},
        "values": {**{f"{year}년 인구": f"population_{year}" for year in POPULATION_YEARS},
                   **{f"{year} 증감률": f"change_rate_{year}" for year in config.POPULATION_TARGET_YEARS}},
    },
}


def read_table(warehouse, qualified):
    """DB 표 전체를 DataFrame으로 읽습니다."""
    with warehouse.connect() as connection, connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {qualified}")
        columns = [column.name for column in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)


def compare_table(dbt_table, python_table, keys, values):
    """두 표를 열쇠 열로 맞춰 값 열을 한 칸씩 비교합니다.

    같은 열쇠가 여러 줄이면 합계로 묶어 비교합니다(행이 겹쳐도 비교가 부풀지 않게).
    Returns: {'행 수 (dbt / 파이썬)', '비교한 칸', '다른 칸', '한쪽에만', '결과'}
    """
    def prepare(table):
        table = table.copy()
        for column in values:
            table[column] = pd.to_numeric(table[column], errors="coerce").astype(float)
        for column in keys:
            table[column] = table[column].astype(str)
        return table.groupby(keys, as_index=False)[values].sum(min_count=1)

    left, right = prepare(dbt_table), prepare(python_table)
    merged = left.merge(right, on=keys, how="outer", suffixes=("_dbt", "_python"), indicator=True)
    both = merged[merged["_merge"] == "both"]
    different = 0
    for column in values:
        a, b = both[f"{column}_dbt"], both[f"{column}_python"]
        different += int((((a - b).abs() > 1e-6) | (a.isna() != b.isna())).sum())
    one_side = int((merged["_merge"] != "both").sum())
    return {
        "행 수 (dbt / 파이썬)": f"{len(dbt_table):,} / {len(python_table):,}",
        "비교한 칸": len(both) * len(values), "다른 칸": different, "한쪽에만": one_side,
        "결과": "일치" if different == 0 and one_side == 0 and len(dbt_table) == len(python_table) else "불일치",
    }


# Gold: 파이썬 Gold 표 → dbt Gold 모델. 열쇠 열이 같아야 같은 줄로 보고, 값 열은 숫자로 한 칸씩 비교합니다.
# 글자 값(핵심 연령대, 유형)은 열쇠에 넣어, 다르면 '한쪽에만'으로 드러나게 합니다.
_CASE_KEYS = {"시도": "province", "시군구": "district", "업종코드": "industry_code", "업종명": "industry_name"}
_STRUCTURE_VALUES = {"이용금액": "amount", "이용건수": "payment_count", "업종총이용금액": "industry_total_amount",
                     "이용금액비중": "amount_share"}
_PROFILE_VALUES = {"이용금액비중": "main_age_share", "업종총이용금액": "industry_total_amount",
                   "연령집중도": "age_concentration", "데이터보유개월수": "months_with_data",
                   "6개월완전": "is_complete_6_months", "월평균증감률": "avg_monthly_change",
                   "1월대비6월증감률": "change_first_to_last_month", "상승개월수": "rising_months"}
_STRESS_VALUES = {f"{year} 순인구효과": f"stress_{year}" for year in config.STRESS_YEARS}

GOLD_COLUMN_MAPS = {
    # 분석 기간이 같아야 아래 표들이 같은 결제로 계산된 것 (최근 6개월, 새 달이 오면 옮겨 감)
    "analysis_window": {
        "dbt_table": "gold_analysis_window",
        "keys": {"시작월": "start_month", "끝월": "end_month"},
        "values": {"개월수": "month_count", "결제가있는달수": "months_with_payments"},
    },
    "age_spending_structure": {
        "dbt_table": "gold_age_spending_structure",
        "keys": {**_CASE_KEYS, "연령대": "age_group"}, "values": _STRUCTURE_VALUES,
    },
    "gyeonggi_city_age_spending_structure": {
        "dbt_table": "gold_gyeonggi_city_age_spending_structure",
        "keys": {**_CASE_KEYS, "연령대": "age_group"}, "values": _STRUCTURE_VALUES,
    },
    "region_industry_profile": {
        "dbt_table": "gold_region_industry_profile",
        "keys": {**_CASE_KEYS, "연령대": "main_age_group"}, "values": _PROFILE_VALUES,
    },
    "age_stress": {
        "dbt_table": "gold_age_stress",
        "keys": {**_CASE_KEYS, "연령대": "age_group"},
        "values": {**_STRUCTURE_VALUES,
                   **{f"{year} 증감률": f"change_rate_{year}" for year in config.POPULATION_TARGET_YEARS},
                   **_STRESS_VALUES},
    },
    "future_stress": {
        "dbt_table": "gold_future_stress",
        "keys": {**_CASE_KEYS, "연령대": "main_age_group"}, "values": {**_PROFILE_VALUES, **_STRESS_VALUES},
    },
    "market_type": {
        "dbt_table": "gold_market_type",
        "keys": {**_CASE_KEYS, "연령대": "main_age_group", "유형": "market_type"},
        "values": {**_PROFILE_VALUES, **_STRESS_VALUES},
    },
    "market_type_counts": {
        "dbt_table": "gold_market_type_counts",
        "keys": {"유형": "market_type"}, "values": {"서울": "seoul", "부산": "busan", "경기": "gyeonggi"},
    },
}


def compare_layer(warehouse, python_dir, schema, column_maps):
    """dbt가 만든 표(PostgreSQL)와 파이썬이 만든 표(Parquet)를 표마다 비교합니다."""
    rows = []
    for python_name, mapping in column_maps.items():
        python_table = read_parquet(Path(python_dir) / f"{python_name}.parquet")
        python_table = python_table.rename(columns={**mapping["keys"], **mapping["values"]})
        dbt_table = read_table(warehouse, f"{schema}.{mapping['dbt_table']}")
        rows.append({"표": f"{schema}.{mapping['dbt_table']}",
                     **compare_table(dbt_table, python_table, list(mapping["keys"].values()),
                                     list(mapping["values"].values()))})
    return pd.DataFrame(rows)


def compare_silver(warehouse, silver_dir=None, silver_schema="silver"):
    """dbt Silver와 파이썬 Silver가 같은지. 같다면 Silver 규칙을 dbt로 옮겨도 결과가 바뀌지 않았다는 뜻입니다."""
    return compare_layer(warehouse, silver_dir or config.SILVER_DIR, silver_schema, SILVER_COLUMN_MAPS)


def compare_gold(warehouse, gold_dir=None, gold_schema="gold"):
    """dbt Gold와 파이썬 Gold가 같은지. 발표 결과(통계 검정 등)는 이 Gold 표들로 계산하므로,
    모두 같다면 Gold 계산을 SQL로 옮겨도 발표 결과가 바뀌지 않는다는 뜻입니다."""
    return compare_layer(warehouse, gold_dir or config.GOLD_DIR, gold_schema, GOLD_COLUMN_MAPS)


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL raw 스키마 적재 · dbt 결과 비교 도구")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load-raw", help="Bronze 원본을 raw 스키마에 적재")
    load.add_argument("--bronze-dir", default=config.BRONZE_DIR)
    commands.add_parser("status", help="표마다 행 수와 마지막 적재")
    compare = commands.add_parser("compare-silver", help="dbt Silver와 파이썬 Silver(data/silver) 비교")
    compare.add_argument("--silver-dir", default=config.SILVER_DIR)
    compare.add_argument("--silver-schema", default="silver", help="합성 데이터는 synthetic_silver")
    compare_g = commands.add_parser("compare-gold", help="dbt Gold와 파이썬 Gold(data/gold) 비교")
    compare_g.add_argument("--gold-dir", default=config.GOLD_DIR)
    compare_g.add_argument("--gold-schema", default="gold", help="합성 데이터는 synthetic_gold")
    arguments = parser.parse_args()

    try:
        warehouse = Warehouse.from_environment()
        if arguments.command == "load-raw":
            print(load_raw(arguments.bronze_dir, warehouse).to_string(index=False))
        elif arguments.command in ("compare-silver", "compare-gold"):
            if arguments.command == "compare-silver":
                report = compare_silver(warehouse, arguments.silver_dir, arguments.silver_schema)
            else:
                report = compare_gold(warehouse, arguments.gold_dir, arguments.gold_schema)
            print(report.to_string(index=False))
            # 하나라도 불일치면 실패 코드(1)로 끝냅니다. 출력만 하면 CI(GitHub Actions)가 불일치를 '성공'으로 봅니다.
            if (report["결과"] != "일치").any():
                raise SystemExit("[불일치] dbt 결과와 파이썬 결과가 다른 표가 있습니다.")
        else:
            print(warehouse.status().to_string(index=False))
    except ValueError as error:
        raise SystemExit(f"[중단] {error}")
    except psycopg.OperationalError:
        # Docker를 켜지 않았거나 컨테이너가 아직 준비되지 않은 경우. 연결 정보(비밀번호 포함)가 든 원래 메시지는 출력하지 않습니다.
        raise SystemExit("[중단] PostgreSQL에 연결할 수 없습니다. 'docker compose up -d'로 띄운 뒤 다시 실행해 주세요.") from None


if __name__ == "__main__":
    main()
