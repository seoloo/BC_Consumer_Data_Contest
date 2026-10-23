"""연령 · 지역 표준화 테스트: 데이터마다 다른 표기가 같은 이름으로 모이는지 확인합니다."""

import pandas as pd
import pytest

from future_stress.analysis.age_groups import (
    age_group_from_label,
    sort_by_age_group,
    standardize_age_group_name,
)
from future_stress.analysis.regions import fix_region_name, to_parent_city


@pytest.mark.parametrize("label, expected", [
    ("0~4세", "20대이하"),      # 서울 장래인구 표기
    ("15-19세", "20대이하"),    # 부산 · 경기 장래인구 표기
    ("25~29세", "20대"),
    ("45-49세", "40대"),
    ("55~59세", "50대"),
    ("60~64세", "60대이상"),
    ("90세 이상", "60대이상"),
    ("100세이상", "60대이상"),
    ("계", None),               # 합계 행은 연령대가 없어야 함
])
def test_age_group_from_label(label, expected):
    assert age_group_from_label(label) == expected


def test_standardize_age_group_name_merges_aliases():
    names = pd.Series(["20대미만", "60대", "70대이상", "30대"])
    assert standardize_age_group_name(names).tolist() == ["20대이하", "60대이상", "60대이상", "30대"]


def test_sort_by_age_group_uses_age_order_not_text_order():
    shuffled = pd.DataFrame({"연령대": ["30대", "20대이하", "60대이상", "20대"]})
    assert sort_by_age_group(shuffled)["연령대"].astype(str).tolist() == ["20대이하", "20대", "30대", "60대이상"]


@pytest.mark.parametrize("name, expected", [
    ("수원시 장안구", "수원시"),
    ("고양시 덕양구", "고양시"),
    ("가평군", "가평군"),
    ("과천시", "과천시"),
])
def test_to_parent_city(name, expected):
    assert to_parent_city(name) == expected


def test_fix_region_name():
    assert fix_region_name("연천시") == "연천군"
    assert fix_region_name("수원시") == "수원시"
