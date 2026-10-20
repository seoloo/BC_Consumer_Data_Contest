"""합성 원본 생성기 테스트.

확인하는 것
    1. 같은 시드면 바이트까지 같은 파일이 나오는지 (Bronze 영수증의 해시가 바뀌지 않아야 함)
    2. 원본에서 실제로 부딪혔던 까다로운 형식이 합성 데이터에도 들어 있는지
       (빠져 있으면 정제 코드가 그 경우를 처리하는지 합성 데이터로는 확인할 수 없음)
"""

import csv

import pandas as pd

from future_stress.medallion import file_fingerprint
from future_stress.synthetic import write_synthetic_raw_files


def fingerprints(folder):
    return {path.relative_to(folder).as_posix(): file_fingerprint(path)
            for path in sorted(folder.rglob("*")) if path.is_file()}


def test_same_seed_gives_identical_files(synthetic_raw_dir, tmp_path):
    again = write_synthetic_raw_files(tmp_path / "raw", seed=42)
    assert fingerprints(again) == fingerprints(synthetic_raw_dir)


def test_card_file_keeps_raw_quirks(synthetic_raw_dir):
    card = pd.read_csv(synthetic_raw_dir / "bc_card_202601_202606.csv", dtype={"GENDER_CD": str, "AGE_CD": str})
    assert set(card["GENDER_CD"]) == {"1", "2", "3", "x"}
    assert set(card.loc[card["GENDER_CD"] == "x", "AGE_CD"]) == {"x"}        # 성별을 모르면 연령도 모름
    assert {"편 의 점", "슈퍼 마켓", "제 과 점"} <= set(card["TP_BUZ_NM"])   # 업종명 안 공백

    # 6개월이 다 없는 지역 × 업종이 있어야 '6개월 완전관측' 판정이 실제로 걸러내는지 볼 수 있음
    months_per_case = card.groupby(["SIDO_NM", "CCG_NM", "TP_BUZ_NO"])["STRD_YYMM"].nunique()
    assert (months_per_case < 6).any() and (months_per_case == 6).any()

    # 경기도는 일반구 단위로 나옴 (Gold에서 시 단위로 합침)
    gyeonggi = set(card.loc[card["SIDO_NM"] == "경기도", "CCG_NM"])
    assert "수원시 장안구" in gyeonggi and "수원시" not in gyeonggi


def test_population_files_keep_raw_quirks(synthetic_raw_dir):
    resident = pd.read_csv(synthetic_raw_dir / "population_202601.csv", encoding="cp949")
    assert resident["행정구역"].str.contains(r"\(\d{10}\)$").all()           # 지역명 뒤 행정코드
    assert resident["2026년01월_계_0~9세"].str.contains(",").any()           # 쉼표가 든 숫자

    with open(synthetic_raw_dir / "seoul_future_population_2022_2042.csv", encoding="utf-8-sig") as file:
        seoul_labels = {row[2] for row in csv.reader(file)}
    assert {"합계", "0~4세", "0세", "90~94세", "95세 이상"} <= seoul_labels   # 5세 · 1세 · 합계 행 혼재

    busan = pd.read_excel(synthetic_raw_dir / "busan_future_population_2015_2040.xlsx")
    assert busan["시군구별"].isna().any()                                     # 병합 셀 → 첫 행에만 값
    assert "0 - 4세" in set(busan["연령별(1)"])

    flow_files = {path.name for path in (synthetic_raw_dir / "gyeonggi_flow_202601_202603").glob("*.csv")}
    assert "T21_GG_SGG_FLOWPOP_202601_연천시.csv" in flow_files               # 파일명 오타 그대로
    assert len(flow_files) == 16 * 3

    busan_living = pd.read_excel(synthetic_raw_dir / "busan_living_population_age.xlsx")
    assert 202412 in set(busan_living["기준년월"])                             # 2025년만 쓰는 필터 확인용
