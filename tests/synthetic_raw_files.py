"""파이프라인 전체 실행 테스트용 가짜 원본 파일 생성기.

실제 원본과 '파일 형식'만 같고 숫자는 무작위입니다. (분석 결과 확인용이 아니라,
파일을 읽고 단계를 연결하는 코드가 끝까지 오류 없이 도는지 확인하는 용도)
"""

import numpy as np
import pandas as pd

from future_stress.age_groups import AGE_GROUP_ORDER

SEOUL_DISTRICTS = {11110: "종로구", 11140: "중구", 11200: "성동구", 11290: "성북구",
                   11320: "도봉구", 11440: "마포구", 11680: "강남구", 11710: "송파구"}
BUSAN_DISTRICTS = ["중구", "서구", "동구", "부산진구", "동래구", "남구", "사상구", "해운대구"]
GYEONGGI_DISTRICTS = ["수원시 장안구", "수원시 권선구", "성남시 분당구", "평택시", "화성시", "시흥시", "파주시", "가평군"]
INDUSTRIES = [("1001", "일반한식"), ("1002", "서양음식"), ("1003", "편의점"), ("1004", "대형할인점"),
              ("1005", "슈퍼마켓"), ("1006", "제과점"), ("1007", "중국음식"), ("1008", "스낵")]
MONTHS = [202601, 202602, 202603, 202604, 202605, 202606]
YEARS = [2026, 2030, 2035, 2040]
FIVE_YEAR_STARTS = list(range(0, 100, 5))   # 0, 5, ..., 95


def age_label(start, separator):
    return "100세이상" if start >= 100 else f"{start}{separator}{start + 4}세"


def write_card_csv(path, rng):
    rows = []
    regions = ([("서울특별시", d) for d in SEOUL_DISTRICTS.values()]
               + [("부산광역시", d) for d in BUSAN_DISTRICTS]
               + [("경기도", d) for d in GYEONGGI_DISTRICTS])
    for province, district in regions:
        for code, industry in INDUSTRIES:
            base = rng.uniform(1_000, 50_000)
            trend = rng.uniform(-0.04, 0.05)              # 월 성장률: 성장 · 비성장이 섞이도록
            age_weights = rng.dirichlet(np.ones(6) * 2)
            for month_index, month in enumerate(MONTHS):
                monthly_total = base * (1 + trend) ** month_index * rng.uniform(0.97, 1.03)
                for age_code, weight in enumerate(age_weights, start=1):
                    rows.append({"STRD_YYMM": month, "SIDO_NM": province, "CCG_NM": district,
                                 "GENDER_CD": "1", "AGE_CD": str(age_code), "TP_BUZ_NO": code,
                                 "TP_BUZ_NM": industry, "amt": round(monthly_total * weight), "cnt": 10})
    # 개인이 아닌 결제 (정제에서 빠져야 함)
    rows.append({"STRD_YYMM": 202601, "SIDO_NM": "서울특별시", "CCG_NM": "중구", "GENDER_CD": "9",
                 "AGE_CD": "9", "TP_BUZ_NO": "1001", "TP_BUZ_NM": "일반한식", "amt": 1, "cnt": 1})
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def random_population_by_year(rng):
    base = rng.uniform(5_000, 20_000)
    rates = rng.uniform(-0.4, 0.4, size=len(YEARS) - 1)
    return [base] + [base * (1 + rate) for rate in rates]


def write_seoul_future_csv(path, rng):
    rows = []
    for district in list(SEOUL_DISTRICTS.values()) + ["합계"]:
        labels = [age_label(s, "~") for s in FIVE_YEAR_STARTS[:18]] + ["90세 이상", "65세 이상"]  # 65세 이상은 합계 행
        for label in labels:
            values = random_population_by_year(rng)
            rows.append({"자치구별": district, "성별": "계", "연령별": label,
                         **{f"{year} 년": round(v) for year, v in zip(YEARS, values)}})
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def write_kosis_future_xlsx(path, province_name, districts, rng):
    rows = []
    for district in [province_name] + districts:
        first_row = True
        for label in ["계"] + [age_label(s, "-") for s in FIVE_YEAR_STARTS] + ["100세이상"]:
            values = random_population_by_year(rng)
            rows.append({"시군구별": district if first_row else None, "성별": "계" if first_row else None,
                         "연령별(1)": label, "연령별(2)": "소계", **dict(zip(YEARS, values))})
            first_row = False
    pd.DataFrame(rows).to_excel(path, index=False)


def write_resident_population_csvs(folder, rng):
    regions = (["서울특별시"] + [f"서울특별시 {d}" for d in SEOUL_DISTRICTS.values()]
               + ["경기도 수원시", "경기도 평택시", "경기도 화성시", "경기도 시흥시"])
    source_ages = ["0~9세", "10~19세", "20~29세", "30~39세", "40~49세", "50~59세",
                   "60~69세", "70~79세", "80~89세", "90~99세", "100세 이상"]
    for month in MONTHS:
        prefix = f"{str(month)[:4]}년{str(month)[4:]}월_계_"
        rows = []
        for region in regions:
            row = {"행정구역": f"{region} (1100000000)"}
            row.update({prefix + age: f"{int(rng.uniform(1_000, 9_000)):,}" for age in source_ages})
            rows.append(row)
        pd.DataFrame(rows).to_csv(folder / f"population_{month}.csv", index=False, encoding="cp949")


def write_seoul_living_csv(path, rng):
    ranges = ["0t9", "10t14", "15t19", "20t24", "25t29", "30t34", "35t39", "40t44", "45t49",
              "50t54", "55t59", "60t64", "65t69", "70t74"]
    rows = []
    for code in SEOUL_DISTRICTS:
        for _ in range(3):   # 같은 구의 여러 시간대
            row = {"adstrd_code_se": code}
            row.update({f"{sex}_f{r}_lvpop_co": rng.uniform(100, 1_000) for sex in ("male", "female") for r in ranges})
            rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def write_busan_living_xlsx(path, rng):
    rows = []
    for month in ["202501", "202502", "202412"]:   # 2024년 행은 걸러져야 함
        for district in BUSAN_DISTRICTS:
            for dong in ("가동", "나동"):
                for age in ["20대미만", "20대", "30대", "40대", "50대", "60대", "70대이상"]:
                    rows.append({"기준년월": month, "행정동명": f"{district} {dong}", "나이대": age,
                                 "평균주거인구수": rng.uniform(100, 900), "평균직장인구수": rng.uniform(50, 500),
                                 "평균방문인구수": rng.uniform(50, 500)})
    pd.DataFrame(rows).to_excel(path, index=False)


def write_gyeonggi_flow_folder(folder, rng):
    folder.mkdir()
    starts = ["10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60", "65", "70"]
    for month in MONTHS[:3]:
        for city in ["수원시", "평택시", "화성시", "시흥시"]:
            rows = [{"CTY_NM": f"{city} 어느동",
                     **{f"{sex}_{s}_CNT": rng.uniform(100, 1_000) for sex in ("M", "F") for s in starts}}
                    for _ in range(2)]
            pd.DataFrame(rows).to_csv(folder / f"flow_{month}_{city}.csv", index=False, encoding="utf-8-sig")


def write_all_raw_files(raw_dir, seed=7):
    """medallion.RAW_SOURCES에 적힌 이름 그대로 가짜 원본을 만듭니다."""
    rng = np.random.default_rng(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_card_csv(raw_dir / "bc_card_202601_202606.csv", rng)
    write_resident_population_csvs(raw_dir, rng)
    write_seoul_future_csv(raw_dir / "seoul_future_population_2022_2042.csv", rng)
    write_kosis_future_xlsx(raw_dir / "busan_future_population_2015_2040.xlsx", "부산광역시", BUSAN_DISTRICTS, rng)
    write_kosis_future_xlsx(raw_dir / "gyeonggi_future_population_2022_2042.xlsx", "경기도",
                            ["수원시", "성남시", "평택시", "화성시", "시흥시", "파주시", "가평군"], rng)
    write_seoul_living_csv(raw_dir / "seoul_living_population_2025.csv", rng)
    write_busan_living_xlsx(raw_dir / "busan_living_population_age.xlsx", rng)
    write_gyeonggi_flow_folder(raw_dir / "gyeonggi_flow_202601_202603", rng)
    assert AGE_GROUP_ORDER  # 연령대 기준표가 비어 있지 않은지 (import 확인용)
