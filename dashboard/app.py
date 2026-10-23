"""미래 소비기반 스트레스 테스트 · 조회 화면 (Phase 4-3)

실행 (저장소 루트에서, warehouse가 떠 있고 dbt build까지 끝난 상태)
    .venv\\Scripts\\streamlit run dashboard/app.py

이 파일은 '어떻게 보여 줄지'만 적습니다. 데이터를 읽고 고르는 일은 future_stress.ops.dashboard_data가 하고,
그쪽은 Streamlit 없이 테스트합니다. (기록: docs/notes/19_dashboard.md)

색은 뜻 하나에 하나만 씁니다.
    빨강 = 취약 (Stress < 0), 파랑 = 안정 (Stress ≥ 0), 막대 하나짜리 그림은 파랑 한 가지.
    4유형은 색 4개 대신 '미래(색) × 현재(모양)' 두 가지로 나눠, 색약이어도 모양으로 구분됩니다.
"""

from zoneinfo import ZoneInfo

import altair as alt
import streamlit as st

from future_stress import config
from future_stress.ops import dashboard_data as data
from future_stress.analysis.age_groups import AGE_GROUP_ORDER
from future_stress.analysis.diagnosis import MARKET_TYPE_STRATEGY

st.set_page_config(page_title="미래 소비기반 스트레스 테스트", layout="wide")

# 밝은 · 어두운 화면에서 각각 배경과 대비가 충분한 단계 (dataviz 기본 팔레트의 파랑 · 빨강)
DARK = st.context.theme.type == "dark"
BLUE = "#3987e5" if DARK else "#2a78d6"
RED = "#e66767" if DARK else "#e34948"
MUTED = "#898781"
SIGN_SCALE = alt.Scale(domain=["취약", "안정"], range=[RED, BLUE])

# 주소로 처음 화면을 정할 수 있게 (README 캡처 · 링크 공유용). 예: /?data=synthetic&tab=types
TABS = {"overview": "개요", "ranking": "지역 · 업종 순위", "types": "4유형 지도", "detail": "한 건 자세히"}
START_WITH_SYNTHETIC = st.query_params.get("data") == "synthetic"
START_TAB = TABS.get(st.query_params.get("tab"))


@st.cache_data(ttl=300, show_spinner="gold 스키마를 읽는 중…")
def load(dataset):
    """gold 표 4개 + 적재 기록. 5분 동안은 다시 읽지 않습니다 (새로 읽기 버튼으로 비울 수 있음)."""
    reader = data.GoldReader.from_environment(dataset)
    tables = {name: reader.read(name) for name in sorted(data.GOLD_TABLES)}
    tables["load_log"] = reader.load_log()
    return tables


def sign_of(values):
    return values.map(lambda value: "취약" if value < 0 else "안정")


def zero_rule(axis):
    """0 기준선 (취약 / 안정 경계)."""
    channel = alt.X("zero:Q") if axis == "x" else alt.Y("zero:Q")
    return alt.Chart(alt.InlineData(values=[{"zero": 0}])).mark_rule(color=MUTED, strokeDash=[4, 3]) \
        .encode(**{axis: channel})


# ---------------------------------------------------------------------------
# 옆 메뉴
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("보기 설정")
    dataset = st.radio("데이터", list(data.DATASETS), index=int(START_WITH_SYNTHETIC), horizontal=True,
                       help="합성: 원본 숫자를 보여 줄 수 없는 자리(캡처 · 시연)에서 쓰는 합성 데이터 결과 (synthetic_gold)")
    year = st.radio("Stress 연도", config.STRESS_YEARS, index=len(config.STRESS_YEARS) - 1, horizontal=True,
                    help="2026년 대비 그 해의 연령대별 인구 증감률로 계산합니다. 4유형은 2040년 기준입니다.")
    if dataset == "합성":
        st.info("합성 데이터는 원본과 형식만 같고 숫자에는 뜻이 없습니다. 화면이 어떻게 동작하는지 보는 용도입니다.")
    if st.button("새로 읽기"):
        load.clear()
    st.caption(f"PostgreSQL `{data.DATASETS[dataset]['gold']}` 스키마를 읽기 전용으로 읽습니다. "
               "dbt 테스트와 파이썬 비교를 통과한 결과만 보여 줍니다.")

st.title("미래 소비기반 스트레스 테스트")
st.caption("지금 잘 되는 상권도, 핵심 고객 연령대의 인구가 줄면 소비 기반이 약해집니다. "
           "Future Stress = Σ(연령대별 이용금액 비중 × 그 연령대의 인구 증감률). 음수면 취약, 0 이상이면 안정입니다.")

try:
    tables = load(dataset)
except Exception as error:  # noqa: BLE001  (어떤 이유든 화면에는 안내만 보여 줌)
    st.error(data.connection_problem(error))
    st.stop()

st.caption(f"**분석 기간** {data.window_label(tables['gold_analysis_window'])} · 결제 데이터의 마지막 달에서 거꾸로 "
           "6개월이며, 새 달 원본이 오면 옮겨 갑니다.")

future_stress = tables["gold_future_stress"]
age_stress = tables["gold_age_stress"]
market_type = tables["gold_market_type"]

overview, ranking_tab, types_tab, detail_tab = st.tabs(list(TABS.values()), default=START_TAB)

# ---------------------------------------------------------------------------
# 개요
# ---------------------------------------------------------------------------
with overview:
    vulnerable = int((market_type["stress_2040"] < 0).sum())
    illusion = int((market_type["market_type"] == "착시성장형").sum())
    first, second, third = st.columns(3)
    first.metric("분석 대상 (지역별 상위 25%)", f"{len(market_type):,}건")
    second.metric("2040년 취약 (Stress < 0)", f"{vulnerable:,}건",
                  f"{vulnerable / len(market_type):.0%}" if len(market_type) else None, delta_color="off",
                  delta_arrow="off")
    third.metric("착시성장형 (지금 성장 · 미래 취약)", f"{illusion:,}건")

    st.subheader("4유형 건수")
    counts = data.type_counts(market_type)
    st.dataframe(counts, hide_index=True, width="stretch")
    if data.counts_match(market_type, tables["gold_market_type_counts"]):
        st.caption("✓ 화면에서 센 건수가 dbt가 만든 gold_market_type_counts와 같습니다.")
    else:
        st.warning("화면에서 센 건수가 gold_market_type_counts와 다릅니다. dbt build를 다시 확인해 주세요.")
    st.caption(" · ".join(f"**{name}** {strategy}" for name, strategy in MARKET_TYPE_STRATEGY.items())
               + " — 현재 성장(첫 달→마지막 달 증감률 > 0, 월평균 증감률 > 0, 오른 달 ≥ 3) × 미래(Stress 2040)로 나눕니다.")

    with st.expander("데이터 기준 (raw 적재 기록)"):
        log = tables["load_log"].copy()
        if log.empty:
            st.write("적재 기록이 없습니다.")
        else:
            log["loaded_at"] = log["loaded_at"].dt.tz_convert(ZoneInfo(config.TIMEZONE)).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(log.rename(columns={"table_name": "표", "row_count": "행 수", "status": "마지막 상태",
                                             "loaded_at": "적재 시각 (한국)"}), hide_index=True)

# ---------------------------------------------------------------------------
# 지역 · 업종 순위
# ---------------------------------------------------------------------------
with ranking_tab:
    labeled = data.with_region_label(future_stress)
    filter_region, filter_industry, filter_order, filter_limit = st.columns([1, 2, 1.4, 1.6])
    region = filter_region.selectbox("지역", ["전체", *[r for r in data.REGION_LABELS.values()
                                                       if r in set(labeled["region"])]])
    industry = filter_industry.selectbox("업종", ["전체", *sorted(labeled["industry_name"].unique())])
    order = filter_order.radio("순서", ["취약한 순", "안정적인 순"], horizontal=True)
    limit = filter_limit.slider("보여 줄 건수", 5, 50, 20, step=5)

    ranking = data.stress_ranking(future_stress, year, None if region == "전체" else region,
                                  None if industry == "전체" else industry,
                                  most_vulnerable_first=order == "취약한 순", limit=limit)
    if ranking.empty:
        st.info("고른 조건에 맞는 건이 없습니다.")
    else:
        ranking["구분"] = sign_of(ranking["stress"])
        ranking["이용금액(억 원)"] = ranking["industry_total_amount"].map(data.to_eok)
        bars = alt.Chart(ranking).mark_bar(cornerRadiusEnd=4, height={"band": 0.7}).encode(
            y=alt.Y("case_name:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X("stress:Q", title=f"Future Stress {year}"),
            color=alt.Color("구분:N", scale=SIGN_SCALE, legend=alt.Legend(title=None, orient="top")),
            tooltip=[alt.Tooltip("case_name:N", title="지역 · 업종"),
                     alt.Tooltip("stress:Q", title=f"Stress {year}", format=".2f"),
                     alt.Tooltip("main_age_group:N", title="핵심 연령대"),
                     alt.Tooltip("main_age_share:Q", title="핵심 연령대 비중(%)", format=".1f"),
                     alt.Tooltip("이용금액(억 원):Q", format=",.1f")],
        )
        st.altair_chart((bars + zero_rule("x")).properties(height=26 * len(ranking) + 40),
                        width="stretch")
        with st.expander("표로 보기"):
            st.dataframe(ranking[["case_name", "main_age_group", "main_age_share", "이용금액(억 원)", "stress"]]
                         .rename(columns={"case_name": "지역 · 업종", "main_age_group": "핵심 연령대",
                                          "main_age_share": "핵심 연령대 비중(%)", "stress": f"Stress {year}"}),
                         hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# 4유형 지도
# ---------------------------------------------------------------------------
with types_tab:
    st.caption("가로는 지금(분석 기간 첫 달 대비 마지막 달 이용금액 증감률), 세로는 미래(Stress 2040)입니다. "
               "점선 아래가 취약입니다. 성장 판정은 증감률 세 가지를 함께 보므로 가로 0과 정확히 같지는 않습니다.")
    scatter_region = st.selectbox("지역", ["전체", *[r for r in data.REGION_LABELS.values()
                                                    if r in set(data.with_region_label(market_type)["region"])]],
                                  key="scatter_region")
    points = data.scatter_frame(market_type, None if scatter_region == "전체" else scatter_region)
    scatter = alt.Chart(points).mark_point(filled=True, size=90, opacity=0.85).encode(
        x=alt.X("change_first_to_last_month:Q", title="첫 달 대비 마지막 달 증감률 (%)"),
        y=alt.Y("stress_2040:Q", title="Future Stress 2040"),
        color=alt.Color("future:N", title="미래", scale=alt.Scale(
            domain=["취약 (Stress < 0)", "안정 (Stress ≥ 0)"], range=[RED, BLUE])),
        shape=alt.Shape("present:N", title="현재", scale=alt.Scale(
            domain=["성장", "비성장"], range=["triangle-up", "circle"])),
        tooltip=[alt.Tooltip("case_name:N", title="지역 · 업종"), alt.Tooltip("market_type:N", title="유형"),
                 alt.Tooltip("change_first_to_last_month:Q", title="첫 달→마지막 달 증감률(%)", format=".1f"),
                 alt.Tooltip("avg_monthly_change:Q", title="월평균 증감률(%)", format=".1f"),
                 alt.Tooltip("rising_months:Q", title="오른 달"),
                 alt.Tooltip("stress_2040:Q", title="Stress 2040", format=".2f")],
    )
    st.altair_chart((scatter + zero_rule("y")).properties(height=460), width="stretch")
    st.dataframe(points.groupby("market_type").size().reindex(list(MARKET_TYPE_STRATEGY), fill_value=0)
                 .rename("건수").rename_axis("유형").reset_index(), hide_index=True)

# ---------------------------------------------------------------------------
# 한 건 자세히
# ---------------------------------------------------------------------------
with detail_tab:
    options = data.case_options(future_stress)
    pick_region, pick_district, pick_industry = st.columns(3)
    region = pick_region.selectbox("지역", [r for r in data.REGION_LABELS.values() if r in set(options["region"])],
                                   key="detail_region")
    in_region = options[options["region"] == region]
    district = pick_district.selectbox("시군구", list(dict.fromkeys(in_region["district"])), key="detail_district")
    in_district = in_region[in_region["district"] == district]
    industry_name = pick_industry.selectbox("업종", list(in_district["industry_name"]), key="detail_industry")
    case = in_district[in_district["industry_name"] == industry_name].iloc[0]

    stress = case[data.gold_stress_column(year)]
    typed = market_type[(market_type["province"] == case["province"]) & (market_type["district"] == district)
                        & (market_type["industry_code"] == case["industry_code"])]
    first, second, third, fourth = st.columns(4)
    first.metric(f"Future Stress {year}", f"{stress:.2f}", "취약" if stress < 0 else "안정",
                 delta_color="inverse" if stress < 0 else "normal", delta_arrow="off")
    second.metric("핵심 연령대", case["main_age_group"], f"비중 {case['main_age_share']:.1f}%", delta_color="off",
                  delta_arrow="off")
    third.metric("6개월 이용금액", f"{data.to_eok(case['industry_total_amount']):,.1f}억 원")
    fourth.metric("4유형", typed["market_type"].iloc[0] if len(typed) else "분석 대상 아님",
                  help="지역별 이용금액 상위 25%만 4유형으로 나눕니다.")

    breakdown = data.age_breakdown(age_stress, case["province"], district, case["industry_code"], year)
    breakdown["구분"] = sign_of(breakdown["change_rate"].fillna(0))
    breakdown["기여 구분"] = sign_of(breakdown["contribution"].fillna(0))
    age_axis = alt.X("age_group:N", sort=AGE_GROUP_ORDER, title=None, axis=alt.Axis(labelAngle=0))

    share_chart = alt.Chart(breakdown, title="① 연령대별 이용금액 비중 (%)").mark_bar(
        color=BLUE, cornerRadiusEnd=4).encode(
        x=age_axis, y=alt.Y("amount_share:Q", title=None),
        tooltip=[alt.Tooltip("age_group:N", title="연령대"),
                 alt.Tooltip("amount_share:Q", title="비중(%)", format=".1f")])
    change_chart = alt.Chart(breakdown, title=f"② 2026 → {year} 인구 증감률 (%)").mark_bar(
        cornerRadiusEnd=4).encode(
        x=age_axis, y=alt.Y("change_rate:Q", title=None),
        color=alt.Color("구분:N", scale=SIGN_SCALE, legend=None),
        tooltip=[alt.Tooltip("age_group:N", title="연령대"),
                 alt.Tooltip("change_rate:Q", title="증감률(%)", format=".1f")])
    contribution_chart = alt.Chart(breakdown, title="③ Stress 기여도 = ① ÷ 100 × ②").mark_bar(
        cornerRadiusEnd=4).encode(
        x=age_axis, y=alt.Y("contribution:Q", title=None),
        color=alt.Color("기여 구분:N", scale=SIGN_SCALE, legend=None),
        tooltip=[alt.Tooltip("age_group:N", title="연령대"),
                 alt.Tooltip("contribution:Q", title="기여도", format=".3f")])
    left, middle, right = st.columns(3)
    left.altair_chart(share_chart.properties(height=260), width="stretch")
    middle.altair_chart((change_chart + zero_rule("y")).properties(height=260), width="stretch")
    right.altair_chart((contribution_chart + zero_rule("y")).properties(height=260), width="stretch")

    if data.contributions_add_up(breakdown, stress):
        st.caption(f"✓ 연령대 기여도 6개를 더하면 Future Stress {year} ({stress:.2f})와 같습니다.")
    else:
        st.warning("연령대 기여도의 합이 Future Stress와 다릅니다. gold_age_stress와 gold_future_stress를 확인해 주세요.")
    with st.expander("표로 보기"):
        st.dataframe(breakdown[["age_group", "amount_share", "change_rate", "contribution"]].rename(columns={
            "age_group": "연령대", "amount_share": "이용금액 비중(%)", "change_rate": f"인구 증감률 {year}(%)",
            "contribution": "Stress 기여도"}), hide_index=True)
