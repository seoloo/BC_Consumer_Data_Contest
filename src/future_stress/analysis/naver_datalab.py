"""NAVER 데이터랩 API로 연령대별 관심도를 수집하고 해석합니다. (전략 단계)

왜 쓰나요?
    BC카드 결제는 '이미 돈을 쓴 고객'만 보여줍니다. 아직 오지 않은 고객이 무엇에 관심이
    있는지는 알 수 없어서, 연령대별 검색 · 쇼핑 관심도로 메뉴 · 상품 후보를 고릅니다.

원래 노트북과 달라진 점
    - 같은 API 호출 함수가 노트북 안에서 5번 이상 복사 · 수정되어 있었습니다.
      → NaverDataLabClient 클래스 하나로 합쳤습니다.
    - 네트워크 오류나 호출 제한(429)이 나면 그대로 멈췄습니다.
      → 잠시 기다렸다가 다시 시도합니다.
    - 인증정보는 코드에 쓰지 않고 환경변수(NAVER_CLIENT_ID / NAVER_CLIENT_SECRET)에서 읽습니다.

원래 위치: contest/notebooks/02_naver_api.ipynb 전체
"""

import os
import time

import pandas as pd
import requests

from .age_groups import AGE_GROUP_ORDER

API_BASE_URL = "https://naverapihub.apigw.ntruss.com"
SEARCH_TREND_PATH = "/search-trend/v1/search"
SHOPPING_KEYWORD_AGE_PATH = "/shopping/v1/category/keyword/age"

# 식품 쇼핑 카테고리 코드 (원본 분석에서 사용한 값)
FOOD_CATEGORY_CODE = "50000006"

# 분석 연령대 → NAVER 검색어트렌드의 연령 코드 (5세 단위 코드 여러 개를 묶어서 보냄)
NAVER_SEARCH_AGE_CODES = {
    "20대이하": ["1", "2"],
    "20대": ["3", "4"],
    "30대": ["5", "6"],
    "40대": ["7", "8"],
    "50대": ["9", "10"],
    "60대이상": ["11"],
}

# NAVER 쇼핑인사이트 응답의 연령 그룹 → 표시 이름
NAVER_SHOPPING_AGE_NAMES = {"10": "10대", "20": "20대", "30": "30대", "40": "40대", "50": "50대", "60": "60대이상"}

# 다시 시도할 HTTP 상태: 호출 제한(429)과 일시적인 서버 오류(5xx)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class NaverDataLabClient:
    """NAVER 데이터랩 API 호출을 담당합니다.

    사용 예
        client = NaverDataLabClient.from_environment()
        interest = client.search_interest_by_age("30대", {"피자": ["피자"]})
    """

    def __init__(self, client_id, client_secret, start_date="2026-01-01", end_date="2026-08-31",
                 max_retries=3, retry_wait_seconds=2.0, timeout_seconds=10):
        if not client_id or not client_secret:
            raise ValueError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정해 주세요 (.env.example 참고).")
        self.start_date = start_date
        self.end_date = end_date
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds
        self.timeout_seconds = timeout_seconds
        # Session을 쓰면 같은 서버에 반복 호출할 때 연결을 재사용해서 더 빠릅니다.
        self.session = requests.Session()
        self.session.headers.update({
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
            "Content-Type": "application/json",
        })

    @classmethod
    def from_environment(cls, **options):
        """환경변수에서 인증정보를 읽어 클라이언트를 만듭니다."""
        return cls(os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET"), **options)

    def _post(self, path, body):
        """POST 요청을 보내고, 일시적인 오류면 점점 길게 기다리며 다시 시도합니다."""
        for attempt in range(1, self.max_retries + 1):
            response = self.session.post(API_BASE_URL + path, json=body, timeout=self.timeout_seconds)
            if response.status_code == 200:
                return response.json()
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt == self.max_retries:
                raise RuntimeError(f"NAVER API 오류 {response.status_code}: {response.text[:200]}")
            # 2초 → 4초 (최대 3번 시도): 호출 제한에 걸렸을 때 바로 다시 보내면 또 막히기 때문입니다.
            time.sleep(self.retry_wait_seconds * 2 ** (attempt - 1))
        return None

    def search_interest_by_age(self, age_group, keyword_groups):
        """한 연령대의 키워드 그룹별 월간 검색 관심도를 가져옵니다.

        Args:
            age_group: 분석 연령대 (예: "30대").
            keyword_groups: {주제: [검색어, ...]} (예: {"파스타": ["파스타", "스파게티"]}).

        Returns:
            주제 | 기간 | 검색도  (검색도는 기간 중 최댓값을 100으로 한 상대값)
        """
        body = {
            "startDate": self.start_date,
            "endDate": self.end_date,
            "timeUnit": "month",
            "keywordGroups": [{"groupName": name, "keywords": words} for name, words in keyword_groups.items()],
            "ages": NAVER_SEARCH_AGE_CODES[age_group],
        }
        response = self._post(SEARCH_TREND_PATH, body)
        return pd.DataFrame([
            {"주제": result["title"], "기간": point["period"], "검색도": point["ratio"]}
            for result in response["results"]
            for point in result["data"]
        ])

    def shopping_keyword_interest_by_age(self, keyword, category_code=FOOD_CATEGORY_CODE):
        """쇼핑인사이트에서 한 키워드의 연령대별 평균 클릭 관심도를 가져옵니다.

        Returns:
            연령대 | ratio  (연령별 데이터가 없는 키워드는 None)
        """
        body = {
            "startDate": self.start_date,
            "endDate": self.end_date,
            "timeUnit": "month",
            "category": category_code,
            "keyword": keyword,
        }
        points = self._post(SHOPPING_KEYWORD_AGE_PATH, body)["results"][0]["data"]
        if not points or "group" not in points[0]:
            # 검색량이 적은 키워드는 연령별 데이터가 비어서 옵니다. 분석에서 빼기 위해 None을 돌려줍니다.
            return None
        by_age = pd.DataFrame(points).groupby("group", as_index=False)["ratio"].mean()
        by_age["연령대"] = by_age["group"].map(NAVER_SHOPPING_AGE_NAMES)
        return by_age[["연령대", "ratio"]]


# ===========================================================================
# 수집한 관심도 해석
# ===========================================================================

def build_keyword_rank_table(client, keyword_groups, age_groups=None):
    """연령대마다 키워드 검색도 순위를 매겨 '키워드 × 연령대' 순위표를 만듭니다.

    검색도 값 대신 순위를 쓰는 이유:
        NAVER 검색도는 요청마다 최댓값을 100으로 다시 맞춘 상대값이라,
        다른 연령대끼리 값을 직접 비교할 수 없습니다. 같은 연령대 안의 순위는 비교할 수 있습니다.
    """
    age_groups = age_groups or AGE_GROUP_ORDER
    rankings = []
    for age_group in age_groups:
        average = client.search_interest_by_age(age_group, keyword_groups).groupby("주제", as_index=False)["검색도"].mean()
        average["연령대"] = age_group
        average["순위"] = average["검색도"].rank(ascending=False, method="min").astype(int)
        rankings.append(average)
    return pd.concat(rankings).pivot(index="주제", columns="연령대", values="순위")[age_groups]


def classify_menu_by_generation(rank_table):
    """키워드(메뉴 · 상품)가 어느 세대에서 강한지 분류합니다.

    규칙 (순서대로 확인)
        전반적 약세  모든 연령의 평균 순위가 4위 이하
        세대공통형   평균 순위 2위 이내이고 연령 간 순위 차이(표준편차)가 1 이하
        그 외        젊은층(20대이하·20대) / 중년층(30·40대) / 고연령(50대·60대이상) 중
                    평균 순위가 가장 좋은 쪽. 동률이면 '복합형(젊은층·중년층)'처럼 표시
    """
    result = rank_table.copy()
    ages = list(rank_table.columns)
    result["전체평균순위"] = result[ages].mean(axis=1).round(2)
    result["순위표준편차"] = result[ages].std(axis=1).round(2)
    generation_columns = {
        "젊은층": ["20대이하", "20대"],
        "중년층": ["30대", "40대"],
        "고연령": ["50대", "60대이상"],
    }
    for generation, columns in generation_columns.items():
        result[f"{generation}평균"] = result[columns].mean(axis=1).round(2)

    def classify(row):
        if row["전체평균순위"] >= 4:
            return "전반적 약세"
        if row["전체평균순위"] <= 2 and row["순위표준편차"] <= 1:
            return "세대공통형"
        scores = {generation: row[f"{generation}평균"] for generation in generation_columns}
        best_score = min(scores.values())
        best_generations = [generation for generation, score in scores.items() if score == best_score]
        if len(best_generations) == 1:
            return best_generations[0] + "형"
        return "복합형(" + "·".join(best_generations) + ")"

    result["메뉴유형"] = result.apply(classify, axis=1)
    return result


def calculate_payment_interest_gap(case_age_structure, shopping_age_table, compare_ages=None):
    """'실제로 돈을 쓰는 연령 순위'와 '관심이 높은 연령 순위'가 얼마나 다른지 계산합니다.

    Args:
        case_age_structure: 한 지역 × 업종의 연령대 | 이용금액비중.
        shopping_age_table: 키워드 × 연령대 쇼핑 관심도 표.
        compare_ages: 두 데이터에 모두 있는 연령대 (NAVER는 20대이하가 없어 기본은 20대 이상).

    Returns:
        (연령대별 비교표, 평균 순위 차이)
        평균 순위 차이가 클수록 '결제 고객'과 '관심 고객'이 다르다는 뜻입니다.
    """
    compare_ages = compare_ages or ["20대", "30대", "40대", "50대", "60대이상"]

    payment = case_age_structure[case_age_structure["연령대"].isin(compare_ages)].copy()
    payment["결제순위"] = payment["이용금액비중"].rank(ascending=False, method="min").astype(int)

    # 키워드마다 연령대 순위를 매긴 뒤 평균 → 여러 메뉴에 걸쳐 관심이 높은 연령대
    age_rank = shopping_age_table.rank(axis=1, ascending=False, method="average")
    interest = age_rank.mean(axis=0).rename("관심평균순위").reset_index().rename(columns={"index": "연령대"})
    interest.columns = ["연령대", "관심평균순위"]
    interest = interest[interest["연령대"].isin(compare_ages)].copy()
    interest["관심순위"] = interest["관심평균순위"].rank(method="min").astype(int)

    gap = payment.merge(interest, on="연령대", how="inner")
    gap["관심-결제차이"] = gap["결제순위"] - gap["관심순위"]   # +면 결제보다 관심이 더 강한 연령대
    gap["순위차이절댓값"] = gap["관심-결제차이"].abs()
    return gap.sort_values("관심순위"), round(gap["순위차이절댓값"].mean(), 2)
