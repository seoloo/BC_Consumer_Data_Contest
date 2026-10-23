"""NAVER 데이터랩 모듈 테스트. 실제 API는 호출하지 않습니다(인증정보 · 호출 제한 때문)."""

import pandas as pd
import pytest

from future_stress.analysis.naver_datalab import (
    NaverDataLabClient,
    calculate_payment_interest_gap,
    classify_menu_by_generation,
)


def test_client_requires_credentials():
    with pytest.raises(ValueError):
        NaverDataLabClient(client_id=None, client_secret=None)


def test_search_interest_parses_response(monkeypatch):
    client = NaverDataLabClient("id", "secret")
    fake_response = {"results": [
        {"title": "피자", "data": [{"period": "2026-01-01", "ratio": 80.0}, {"period": "2026-02-01", "ratio": 100.0}]},
    ]}
    # 실제 HTTP 요청 대신 정해진 응답을 돌려주게 바꿔 끼웁니다.
    monkeypatch.setattr(client, "_post", lambda path, body: fake_response)
    interest = client.search_interest_by_age("30대", {"피자": ["피자"]})
    assert interest.columns.tolist() == ["주제", "기간", "검색도"]
    assert interest["검색도"].tolist() == [80.0, 100.0]


def test_classify_menu_by_generation():
    ages = ["20대이하", "20대", "30대", "40대", "50대", "60대이상"]
    rank_table = pd.DataFrame(
        [[1, 1, 1, 1, 2, 2],    # 모든 세대 상위권 → 세대공통형
         [1, 1, 4, 4, 4, 4],    # 젊은층에서만 강함 (평균 3위, 세대 간 차이 큼)
         [5, 5, 5, 5, 4, 4]],   # 평균 4위 이하 → 전반적 약세
        index=["피자", "브런치", "스테이크"], columns=ages,
    )
    types = classify_menu_by_generation(rank_table)["메뉴유형"]
    assert types.tolist() == ["세대공통형", "젊은층형", "전반적 약세"]


def test_payment_interest_gap():
    case = pd.DataFrame({"연령대": ["20대", "30대", "40대"], "이용금액비중": [10.0, 60.0, 30.0]})
    shopping = pd.DataFrame({"20대": [90.0, 80.0], "30대": [50.0, 40.0], "40대": [70.0, 60.0]}, index=["피자", "파스타"])
    gap, mismatch = calculate_payment_interest_gap(case, shopping, compare_ages=["20대", "30대", "40대"])
    by_age = gap.set_index("연령대")
    assert by_age.loc["30대", "결제순위"] == 1 and by_age.loc["30대", "관심순위"] == 3
    assert mismatch == pytest.approx((2 + 2 + 0) / 3, abs=0.01)
