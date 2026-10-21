"""대시보드 테스트.

1. 화면에 보여 줄 모양으로 고르는 함수 (작은 가짜 gold 표로, DB 없이)
2. 화면 전체가 오류 없이 그려지는지 (Streamlit AppTest, 가짜 GoldReader를 넣어서)
3. 실제 PostgreSQL의 합성 gold를 읽기 전용으로 읽는지 (docker compose up + 합성 dbt build 일 때만)
"""

from pathlib import Path

import pandas as pd
import psycopg
import pytest

from future_stress import config, dashboard_data as data

APP_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
AGES = ["20대이하", "20대", "30대", "40대", "50대", "60대이상"]


def fake_gold():
    """서울 성동구 · 서양음식(성장 · 취약 = 착시성장형), 부산 중구 · 편의점(비성장 · 안정 = 회복기회형)."""
    shares = {"성동구": [5, 20, 40, 20, 10, 5], "중구": [10, 10, 10, 20, 20, 30]}
    rates = {"성동구": [-30, -20, -10, 0, 0, 10], "중구": [-10, -10, 0, 0, 10, 20]}
    cases = [("서울특별시", "성동구", 8001, "서양음식"), ("부산광역시", "중구", 8002, "편의점")]
    age_rows = []
    for province, district, code, name in cases:
        for age, share, rate in zip(AGES, shares[district], rates[district]):
            age_rows.append({"province": province, "district": district, "industry_code": code,
                             "industry_name": name, "age_group": age, "amount": share * 1e8,
                             "amount_share": float(share), "change_rate_2035": rate / 2, "change_rate_2040": float(rate),
                             "stress_2035": share / 100 * rate / 2, "stress_2040": share / 100 * rate})
    age_stress = pd.DataFrame(age_rows)
    totals = age_stress.groupby(["province", "district", "industry_code", "industry_name"], as_index=False)[
        ["stress_2035", "stress_2040"]].sum().sort_values("industry_code").reset_index(drop=True)   # 성동구, 중구 순
    future_stress = totals.assign(main_age_group=["30대", "60대이상"], main_age_share=[40.0, 30.0],
                                  industry_total_amount=[100e8, 100e8])
    market_type = future_stress.assign(change_first_to_last_month=[12.0, -3.0], avg_monthly_change=[2.0, -0.5],
                                       rising_months=[4.0, 1.0], is_growing=[True, False],
                                       is_stable_2040=[False, True], market_type=["착시성장형", "회복기회형"])
    counts = pd.DataFrame({"market_type": ["착시성장형", "지속성장형", "구조취약형", "회복기회형"],
                           "seoul": [1, 0, 0, 0], "busan": [0, 0, 0, 1], "gyeonggi": [0, 0, 0, 0]})
    return {"gold_future_stress": future_stress, "gold_age_stress": age_stress,
            "gold_market_type": market_type, "gold_market_type_counts": counts}


# ===========================================================================
# 1. 고르는 함수
# ===========================================================================

def test_ranking_puts_most_vulnerable_first_and_filters_region():
    gold = fake_gold()
    ranking = data.stress_ranking(gold["gold_future_stress"], 2040)
    assert ranking["case_name"].tolist() == ["서울 성동구 · 서양음식", "부산 중구 · 편의점"]
    assert ranking["stress"].iloc[0] < 0 < ranking["stress"].iloc[1]
    only_busan = data.stress_ranking(gold["gold_future_stress"], 2040, region="부산")
    assert only_busan["district"].tolist() == ["중구"]
    with pytest.raises(ValueError):
        data.stress_ranking(gold["gold_future_stress"], 2030)        # Stress는 2035 · 2040만


def test_type_counts_show_every_type_and_match_dbt_counts():
    gold = fake_gold()
    counts = data.type_counts(gold["gold_market_type"])
    assert counts["유형"].tolist() == ["착시성장형", "지속성장형", "구조취약형", "회복기회형"]   # 0건인 유형도 줄이 있음
    assert counts.set_index("유형").loc["지속성장형", "합계"] == 0
    assert data.counts_match(gold["gold_market_type"], gold["gold_market_type_counts"])

    wrong = gold["gold_market_type_counts"].assign(seoul=[0, 1, 0, 0])
    assert not data.counts_match(gold["gold_market_type"], wrong)


def test_age_contributions_add_up_to_future_stress():
    gold = fake_gold()
    breakdown = data.age_breakdown(gold["gold_age_stress"], "서울특별시", "성동구", 8001, 2040)
    assert breakdown["age_group"].tolist() == AGES                    # 연령대 순서 고정
    stress = gold["gold_future_stress"].set_index("district").loc["성동구", "stress_2040"]
    assert data.contributions_add_up(breakdown, stress)
    assert not data.contributions_add_up(breakdown, stress + 0.01)


def test_scatter_splits_type_into_future_and_present():
    points = data.scatter_frame(fake_gold()["gold_market_type"])
    first = points.iloc[0]
    assert (first["market_type"], first["future"], first["present"]) == ("착시성장형", "취약 (Stress < 0)", "성장")


def test_reader_refuses_tables_outside_gold_list():
    reader = data.GoldReader(connect=None, dataset="합성")
    assert reader.schemas["gold"] == "synthetic_gold"
    with pytest.raises(ValueError):
        reader.read("card_spending")
    with pytest.raises(ValueError):
        data.GoldReader(connect=None, dataset="운영")


# ===========================================================================
# 2. 화면 전체 (Streamlit AppTest)
# ===========================================================================

class FakeReader:
    def __init__(self, dataset):
        self.dataset = dataset

    def read(self, table):
        return fake_gold()[table]

    def load_log(self):
        return pd.DataFrame({"table_name": ["card_spending"], "row_count": [10], "status": ["변경 없음"],
                             "loaded_at": pd.to_datetime(["2026-10-21 12:00"]).tz_localize("UTC")})


@pytest.fixture
def app(monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setattr(data.GoldReader, "from_environment", classmethod(lambda cls, dataset="원본": FakeReader(dataset)))
    app = testing.AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()
    yield app
    import streamlit as st
    st.cache_data.clear()


def test_app_renders_every_tab_without_error(app):
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["개요", "지역 · 업종 순위", "4유형 지도", "한 건 자세히"]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["분석 대상 (지역별 상위 25%)"] == "2건"
    assert metrics["착시성장형 (지금 성장 · 미래 취약)"] == "1건"
    assert any("gold_market_type_counts와 같습니다" in caption.value for caption in app.caption)
    assert any("Future Stress 2040" in caption.value and "같습니다" in caption.value for caption in app.caption)


def test_app_switches_to_synthetic_and_year(app):
    app.sidebar.radio[0].set_value("합성").run()
    app.sidebar.radio[1].set_value(config.STRESS_YEARS[0]).run()
    assert not app.exception
    assert any("synthetic_gold" in caption.value for caption in app.sidebar.caption)
    assert f"Future Stress {config.STRESS_YEARS[0]}" in [metric.label for metric in app.metric]


def test_app_shows_guidance_when_database_is_down(monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")

    def unreachable(cls, dataset="원본"):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(data.GoldReader, "from_environment", classmethod(unreachable))
    app = testing.AppTest.from_file(str(APP_PATH), default_timeout=30)
    app.run()
    assert not app.exception
    assert "docker compose up -d" in app.error[0].value
    assert len(app.tabs) == 0                                         # 안내만 보여 주고 멈춤


# ===========================================================================
# 3. 실제 PostgreSQL (합성 gold)
# ===========================================================================

@pytest.fixture
def synthetic_reader():
    try:
        reader = data.GoldReader.from_environment("합성")
        reader.read("gold_market_type_counts")
    except Exception as error:  # noqa: BLE001  (연결 안 됨 · 합성 dbt build 전이면 건너뜀)
        pytest.skip(f"합성 gold를 읽을 수 없음: {type(error).__name__}")
    return reader


@pytest.mark.integration
def test_synthetic_gold_is_consistent_and_read_only(synthetic_reader):
    market_type = synthetic_reader.read("gold_market_type")
    assert data.counts_match(market_type, synthetic_reader.read("gold_market_type_counts"))

    # 모든 지역 × 업종에서 연령대 기여도 합 = Future Stress
    age_stress = synthetic_reader.read("gold_age_stress")
    future_stress = synthetic_reader.read("gold_future_stress")
    keys = ["province", "district", "industry_code"]
    sums = age_stress.groupby(keys)["stress_2040"].sum(min_count=1).rename("sum_2040").reset_index()
    merged = future_stress.merge(sums, on=keys, how="outer", validate="one_to_one")
    assert ((merged["sum_2040"] - merged["stress_2040"]).abs().fillna(0) < data.TOLERANCE).all()

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        synthetic_reader._query("CREATE TABLE synthetic_gold.should_not_exist (x int)")
