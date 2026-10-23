"""대시보드가 읽는 데이터 (Phase 4-3).

왜 화면 코드(dashboard/app.py)와 나누나요?
    화면은 Streamlit이 그리지만, '무엇을 어떻게 골라 보여 줄지'는 평범한 pandas 함수라서
    Streamlit 없이 테스트할 수 있습니다. Airflow의 orchestration.py와 같은 방식입니다.
    (기록: docs/notes/19_dashboard.md)

무엇을 읽나요?
    PostgreSQL의 gold 스키마(dbt 결과)만 읽습니다. 원본(raw) · silver는 읽지 않아서, 화면에 개인 단위
    결제가 나오지 않고, 화면이 보여 주는 숫자는 dbt 테스트 · 파이썬 비교를 통과한 결과뿐입니다.
    연결은 읽기 전용 트랜잭션이라 화면에서 실수로 표를 바꿀 수 없습니다.

원본 / 합성
    '합성'을 고르면 synthetic_gold(합성 데이터로 만든 결과)를 읽습니다. 원본 숫자를 보여 줄 수 없는 자리
    (README 캡처, 발표 시연)에서 씁니다.
"""

from decimal import Decimal

import pandas as pd
import psycopg
from psycopg import sql

from .. import config
from ..analysis.age_groups import AGE_GROUP_ORDER
from ..analysis.diagnosis import MARKET_TYPE_STRATEGY
from ..storage.warehouse import Warehouse

DATASETS = {
    "원본": {"gold": "gold", "raw": "raw"},
    "합성": {"gold": "synthetic_gold", "raw": "raw_synthetic"},
}

# 화면이 읽을 수 있는 표. 이 밖의 이름은 받지 않습니다 (표 이름을 SQL에 넣기 전에 한 번 더 막기).
GOLD_TABLES = {"gold_analysis_window", "gold_future_stress", "gold_age_stress", "gold_market_type",
               "gold_market_type_counts"}

REGION_LABELS = {"서울특별시": "서울", "부산광역시": "부산", "경기도": "경기"}

# 같은 값인지 볼 때 허용하는 차이. 소수 계산 순서에 따라 생기는 1e-15 수준 차이만 넘깁니다.
TOLERANCE = 1e-9


class GoldReader:
    """gold 스키마를 읽는 창구. 연결을 만드는 함수를 밖에서 받습니다(테스트에서는 가짜를 넣음)."""

    def __init__(self, connect, dataset="원본"):
        if dataset not in DATASETS:
            raise ValueError(f"데이터 이름은 {list(DATASETS)} 중 하나여야 합니다: {dataset}")
        self.connect = connect
        self.dataset = dataset
        self.schemas = DATASETS[dataset]

    @classmethod
    def from_environment(cls, dataset="원본", env_file=None):
        """.env의 POSTGRES_* 값으로 연결 (warehouse.py와 같은 규칙)."""
        return cls(Warehouse.from_environment(env_file).connect, dataset)

    def _query(self, query):
        with self.connect() as connection:
            connection.read_only = True        # BEGIN READ ONLY: 이 연결로는 어떤 표도 바꿀 수 없음
            cursor = connection.execute(query)
            columns = [column.name for column in cursor.description]
            frame = pd.DataFrame(cursor.fetchall(), columns=columns)
        # PostgreSQL numeric은 Decimal로 오므로 계산 · 그래프를 위해 float로 바꿉니다.
        for column in frame.columns:
            if frame[column].map(lambda value: isinstance(value, Decimal)).any():
                frame[column] = frame[column].astype(float)
        return frame

    def read(self, table):
        """gold 표 하나 전체. 가장 큰 표(gold_age_stress)도 수천 줄이라 한 번에 읽어 화면에서 거릅니다."""
        if table not in GOLD_TABLES:
            raise ValueError(f"대시보드가 읽지 않는 표입니다: {table}")
        return self._query(sql.SQL("SELECT * FROM {}.{}").format(
            sql.Identifier(self.schemas["gold"]), sql.Identifier(table)))

    def load_log(self):
        """raw 표마다 가장 최근 적재 기록 (언제 · 몇 행 · 상태). 화면의 '데이터 기준'."""
        return self._query(sql.SQL(
            "SELECT DISTINCT ON (table_name) table_name, row_count, status, loaded_at "
            "FROM {}._load_log ORDER BY table_name, loaded_at DESC").format(sql.Identifier(self.schemas["raw"])))


def connection_problem(error):
    """연결 · 표 없음 오류를 사람이 읽을 안내로. 비밀번호 같은 값은 담지 않습니다."""
    if isinstance(error, psycopg.errors.UndefinedTable):
        return "gold 표가 없습니다. 파이프라인과 dbt build를 먼저 돌려 주세요 (docs/getting_started.md)."
    if isinstance(error, psycopg.OperationalError):
        return "PostgreSQL에 연결할 수 없습니다. `docker compose up -d`로 warehouse를 띄웠는지 확인해 주세요."
    if isinstance(error, ValueError):
        return f".env 설정을 확인해 주세요: {error}"
    return f"데이터를 읽지 못했습니다 ({type(error).__name__})."


# ===========================================================================
# 화면에 보여 줄 모양으로 고르기 (DB 없이 테스트하는 순수 함수)
# ===========================================================================

def window_label(analysis_window):
    """분석 기간 표 한 줄 → '2026.02 ~ 2026.07 (6개월)'. 새 달이 오면 옮겨 가므로 화면 맨 위에 보여 줍니다."""
    row = analysis_window.iloc[0]
    start, end = int(row["start_month"]), int(row["end_month"])
    return f"{start // 100}.{start % 100:02d} ~ {end // 100}.{end % 100:02d} ({int(row['month_count'])}개월)"


def stress_column(year):
    if year not in config.STRESS_YEARS:
        raise ValueError(f"Stress 연도는 {config.STRESS_YEARS} 중 하나입니다: {year}")
    return f"stress_{year}"


def with_region_label(frame):
    """'서울특별시' → '서울', 화면에 쓸 '서울 성동구 · 편의점' 이름 열을 붙입니다."""
    frame = frame.copy()
    frame["region"] = frame["province"].map(REGION_LABELS).fillna(frame["province"])
    frame["case_name"] = frame["region"] + " " + frame["district"] + " · " + frame["industry_name"]
    return frame


def stress_ranking(future_stress, year, region=None, industry=None, most_vulnerable_first=True, limit=None):
    """지역 × 업종 Future Stress 순위. 음수가 클수록(아래로 갈수록) 인구 변화에 더 취약합니다.

    Args:
        region: '서울' · '부산' · '경기' 또는 None(전체)
        industry: 업종 이름 또는 None(전체)
    """
    column = stress_column(year)
    frame = with_region_label(future_stress).dropna(subset=[column])
    if region:
        frame = frame[frame["region"] == region]
    if industry:
        frame = frame[frame["industry_name"] == industry]
    # 동점이면 이름 순으로 (다시 그려도 순서가 같게)
    frame = frame.sort_values([column, "case_name"], ascending=[most_vulnerable_first, True])
    frame = frame.rename(columns={column: "stress"})
    columns = ["case_name", "region", "district", "industry_name", "main_age_group", "main_age_share",
               "industry_total_amount", "stress"]
    return frame[columns].head(limit).reset_index(drop=True) if limit else frame[columns].reset_index(drop=True)


def type_counts(market_type):
    """4유형 × 지역 건수. 한 건도 없는 유형도 0으로 보여 줍니다 (빠진 줄이 '0건'인지 '안 셌다'인지 헷갈리지 않게)."""
    frame = with_region_label(market_type)
    regions = [label for label in REGION_LABELS.values() if label in set(frame["region"])]
    counts = (frame.groupby(["market_type", "region"]).size().unstack(fill_value=0)
              .reindex(index=list(MARKET_TYPE_STRATEGY), columns=regions, fill_value=0))
    counts.insert(0, "전략", [MARKET_TYPE_STRATEGY[name] for name in counts.index])
    counts["합계"] = counts[regions].sum(axis=1)
    return counts.rename_axis("유형").reset_index()


def counts_match(market_type, market_type_counts):
    """화면이 센 유형별 건수 = dbt가 만든 gold_market_type_counts 인가? (화면 숫자의 대사)"""
    mine = type_counts(market_type).set_index("유형")
    theirs = market_type_counts.set_index("market_type").rename(columns={"seoul": "서울", "busan": "부산",
                                                                          "gyeonggi": "경기"})
    regions = [region for region in ["서울", "부산", "경기"] if region in mine.columns]
    return bool((mine[regions] == theirs.loc[mine.index, regions].astype(int)).all().all())


def scatter_frame(market_type, region=None):
    """4유형 그림용: 가로 = 첫 달 대비 마지막 달 증감률(현재 성장), 세로 = Stress 2040(미래). 유형은 2040 기준."""
    frame = with_region_label(market_type)
    if region:
        frame = frame[frame["region"] == region]
    frame = frame.assign(
        future=frame["is_stable_2040"].map({True: "안정 (Stress ≥ 0)", False: "취약 (Stress < 0)"}),
        present=frame["is_growing"].map({True: "성장", False: "비성장"}),
    )
    return frame[["case_name", "region", "market_type", "change_first_to_last_month", "avg_monthly_change",
                  "rising_months", "stress_2040", "future", "present"]].reset_index(drop=True)


def case_options(future_stress):
    """'한 건 자세히'에서 고를 수 있는 시도 → 시군구 → 업종 목록."""
    return with_region_label(future_stress).sort_values(["region", "district", "industry_name"])


def age_breakdown(age_stress, province, district, industry_code, year):
    """한 지역 × 업종의 연령대별 이용금액 비중 · 인구 증감률 · Stress 기여도.

    기여도 = 비중 ÷ 100 × 인구 증감률. 6개 연령대 기여도를 더하면 그 건의 Future Stress입니다.
    """
    rows = age_stress[(age_stress["province"] == province) & (age_stress["district"] == district)
                      & (age_stress["industry_code"] == industry_code)]
    frame = (rows.set_index("age_group")
             .reindex(AGE_GROUP_ORDER)
             .rename(columns={f"change_rate_{year}": "change_rate", stress_column(year): "contribution"}))
    return frame[["amount_share", "change_rate", "contribution", "amount"]].rename_axis("age_group").reset_index()


def contributions_add_up(breakdown, stress):
    """연령대 기여도의 합 = 그 건의 Future Stress 인가? (화면에 '합계가 맞는지'를 함께 보여 줌)"""
    return abs(breakdown["contribution"].sum(min_count=1) - stress) < TOLERANCE


def to_eok(amount):
    """원 → 억 원 (화면 표시용). 예: 1_234_000_000 → 12.3"""
    return round(amount / 100_000_000, 1)
