"""PostgreSQL raw 적재 테스트.

파일 → 표 변환은 DB 없이 확인하고, 실제 적재(멱등 · 되돌리기)는 PostgreSQL이 떠 있을 때만 확인합니다.
실제 적재 테스트는 매번 새 스키마(raw_test_xxxx)를 만들어 쓰고 끝나면 지워서, 원본이 든 raw 스키마를 건드리지 않습니다.
"""

import secrets

import psycopg
import pytest

from future_stress.medallion import build_bronze
from future_stress.storage.warehouse import (
    CARD_TABLE,
    FUTURE_TABLE,
    Warehouse,
    card_spending_frame,
    future_population_frame,
    load_raw,
    raw_sources,
)


@pytest.fixture(scope="module")
def bronze_dir(synthetic_raw_dir, tmp_path_factory):
    folder = tmp_path_factory.mktemp("warehouse") / "bronze"
    build_bronze(synthetic_raw_dir, folder)
    return folder


def test_card_frame_keeps_raw_codes(bronze_dir):
    """개인이 아닌 결제와 'x' 코드까지 그대로 들어가야 합니다 (거르는 일은 dbt Silver)."""
    frame = card_spending_frame(bronze_dir)
    assert list(frame.columns) == [name for name, _ in CARD_TABLE.columns]
    assert {"3", "x"} <= set(frame["gender_cd"]) and "x" in set(frame["age_cd"])
    assert "편 의 점" in set(frame["tp_buz_nm"])                      # 업종명 공백도 그대로
    assert frame["amt"].dtype == "Int64"


def test_future_frame_keeps_raw_labels(bronze_dir):
    frame = future_population_frame(bronze_dir)
    assert list(frame.columns) == [name for name, _ in FUTURE_TABLE.columns]
    assert set(frame["province"]) == {"서울특별시", "부산광역시", "경기도"}

    seoul = frame[frame["province"] == "서울특별시"]
    assert {"합계", "0~4세", "0세", "95세 이상"} <= set(seoul["age_label"])   # 5세 · 1세 · 합계 행 모두
    assert seoul["age_detail"].isna().all()

    # KOSIS 엑셀: 병합 셀을 채워서 1세 단위 행도 어느 5세 구간인지 알 수 있어야 함
    gyeonggi = frame[frame["province"] == "경기도"]
    one_year = gyeonggi[gyeonggi["age_detail"] == "0세"]
    assert set(one_year["age_label"]) == {"0 - 4세"}
    assert gyeonggi["region"].notna().all() and gyeonggi["sex"].notna().all()


# ===========================================================================
# 실제 PostgreSQL (docker compose up -d 일 때만)
# ===========================================================================

@pytest.fixture
def test_warehouse():
    schema = f"raw_test_{secrets.token_hex(4)}"
    try:
        warehouse = Warehouse.from_environment(schema=schema)
        with warehouse.connect():
            pass
    except Exception as error:  # noqa: BLE001  (비밀번호 없음 · 연결 안 됨 모두 '건너뜀'으로)
        pytest.skip(f"PostgreSQL에 연결할 수 없음: {type(error).__name__}")
    yield warehouse
    with warehouse.connect() as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def table_count(warehouse, table):
    with warehouse.connect() as connection:
        return connection.execute(f"SELECT count(*) FROM {warehouse.schema}.{table}").fetchone()[0]


@pytest.mark.integration
def test_load_twice_then_reload_when_table_changed(test_warehouse, bronze_dir):
    first = load_raw(bronze_dir, test_warehouse)
    second = load_raw(bronze_dir, test_warehouse)
    assert set(first["상태"]) == {"신규"} and set(second["상태"]) == {"변경 없음"}
    expected_rows = int(first.loc[first["표"].str.endswith("card_spending"), "행 수"].iloc[0])

    # 누가 표에서 행을 지우면, 원본 지문이 같아도 행 수가 달라 다시 적재해야 합니다.
    with test_warehouse.connect() as connection:
        connection.execute(f"DELETE FROM {test_warehouse.schema}.card_spending WHERE ctid IN "
                           f"(SELECT ctid FROM {test_warehouse.schema}.card_spending LIMIT 10)")
    third = load_raw(bronze_dir, test_warehouse)
    assert third.loc[third["표"].str.endswith("card_spending"), "상태"].iloc[0] == "변경"
    assert table_count(test_warehouse, "card_spending") == expected_rows


@pytest.mark.integration
def test_failed_load_keeps_previous_table(test_warehouse, bronze_dir):
    """적재 도중 실패하면 트랜잭션이 되돌려져 이전 표가 그대로 남아야 합니다.

    표를 지우고(DROP) 새로 만든 '뒤' COPY에서 실패하게 해야, 지운 것까지 되돌려지는지 확인할 수 있습니다.
    """
    table, build_frame, fingerprint = raw_sources(bronze_dir)[0]
    test_warehouse.load(table, build_frame, fingerprint)
    before = table_count(test_warehouse, table.name)

    def broken_frame():
        frame = build_frame()
        frame["strd_yymm"] = frame["strd_yymm"].astype(str)
        frame.loc[frame.index[-1], "strd_yymm"] = "잘못된값"       # integer 열에 글자 → COPY 실패
        return frame

    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        test_warehouse.load(table, broken_frame, "다른 지문")       # 지문이 달라 다시 적재를 시도함
    assert table_count(test_warehouse, table.name) == before


# ===========================================================================
# dbt Silver ↔ 파이썬 Silver 비교 함수 (DB 없이)
# ===========================================================================

def test_compare_table_finds_differences():
    """같으면 '일치', 한 칸만 달라도 · 한쪽에만 있는 줄이 있어도 '불일치'를 내야 합니다."""
    import pandas as pd

    from future_stress.storage.warehouse import compare_table

    dbt = pd.DataFrame({"district": ["종로구", "중구"], "age_group": ["20대", "20대"], "amount": [100, 200]})
    python = dbt.copy()
    assert compare_table(dbt, python, ["district", "age_group"], ["amount"])["결과"] == "일치"

    python.loc[1, "amount"] = 201
    result = compare_table(dbt, python, ["district", "age_group"], ["amount"])
    assert (result["결과"], result["다른 칸"]) == ("불일치", 1)

    extra = pd.concat([dbt, pd.DataFrame({"district": ["용산구"], "age_group": ["30대"], "amount": [5]})])
    result = compare_table(extra, dbt, ["district", "age_group"], ["amount"])
    assert (result["결과"], result["한쪽에만"]) == ("불일치", 1)
