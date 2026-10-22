"""합성 원본 데이터 생성기.

왜 필요한가요?
    공모전 원본(BC카드 결제)은 재배포할 수 없어서, 원본이 없는 사람은 파이프라인을 돌려 볼 수 없었습니다.
    이 모듈은 원본 8종과 '형식이 똑같은' 가짜 파일을 만듭니다. 파이프라인은 원본인지 합성인지
    구분하지 않고 같은 코드로 읽습니다.

무엇을 원본과 같게 만들었나요?
    - 파일 이름, 열 이름, 시트 구조, 인코딩 (cp949 / utf-8-sig)
    - 원본에서 실제로 부딪혔던 까다로운 점
        BC카드: 성별 코드 '3' · 'x'가 섞인 행, 업종명 공백('편 의 점'), 6개월이 다 없는 지역 × 업종
        주민등록인구: '2026년01월_계_0~9세' 같은 열 이름, 쉼표 숫자, 지역명 뒤 행정코드
        서울 장래인구: 5세 구간 · 1세 단위 · 합계 행 혼재, 마지막 구간 '90~94세' · '95세 이상'
        부산 · 경기 장래인구: 병합 셀 때문에 첫 행에만 있는 시군구 · 성별, '0 - 4세' 표기
        부산 생활인구: 행정동 단위, '20대미만' 표기, 2025년이 아닌 행
        경기 유동인구: 시군 × 월별로 쪼개진 파일, '연천시' 오타
    - 지역명, 업종 코드 · 이름 같은 공개 기준 정보

무엇이 원본과 다른가요?
    모든 숫자. 원본에서 계산한 값은 하나도 쓰지 않았고, 아래 상수(업종별 연령 구성, 기본 매출 규모,
    인구 피라미드, 연령별 인구 증감 방향)는 '그럴듯한 값'을 직접 정한 것입니다.
    그래서 합성 데이터로 돌린 결과는 발표 결과와 숫자가 다릅니다.

같은 시드(seed)를 쓰면 언제 실행해도 같은 파일이 나옵니다.

실행 방법 (저장소 루트에서)
    .venv\\Scripts\\python -m future_stress.synthetic                 # data/synthetic/raw 에 생성
    .venv\\Scripts\\python -m future_stress.pipeline --synthetic      # 생성 + 파이프라인 실행
"""

import argparse
import csv
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .regions import SEOUL_DISTRICT_CODE_TO_NAME

# ===========================================================================
# 공개 기준 정보 (행정구역 이름, 업종 코드)
# ===========================================================================

SEOUL_DISTRICTS = list(SEOUL_DISTRICT_CODE_TO_NAME.values())
BUSAN_DISTRICTS = ["중구", "서구", "동구", "영도구", "부산진구", "동래구", "남구", "북구", "해운대구",
                   "사하구", "금정구", "강서구", "연제구", "수영구", "사상구", "기장군"]

# 경기도: 시 → 일반구 목록 (일반구가 없는 시군은 빈 목록)
# BC카드는 일반구 단위로, 장래인구 · 유동인구는 시 단위로 나오는 원본 형식을 그대로 따릅니다.
GYEONGGI_CITIES = {
    "수원시": ["장안구", "권선구", "팔달구", "영통구"], "성남시": ["수정구", "중원구", "분당구"],
    "의정부시": [], "안양시": ["만안구", "동안구"], "부천시": ["원미구", "소사구", "오정구"], "광명시": [],
    "평택시": [], "동두천시": [], "안산시": ["상록구", "단원구"], "고양시": ["덕양구", "일산동구", "일산서구"],
    "과천시": [], "구리시": [], "남양주시": [], "오산시": [], "시흥시": [], "군포시": [], "의왕시": [],
    "하남시": [], "용인시": ["처인구", "기흥구", "수지구"], "파주시": [], "이천시": [], "안성시": [],
    "김포시": [], "화성시": ["동탄구", "만세구", "병점구", "효행구"], "광주시": [], "양주시": [],
    "포천시": [], "여주시": [], "연천군": [], "가평군": [], "양평군": [],
}

# 분석 대상(서울 · 부산 · 경기)은 아니지만, '전국 상위 25%' 기준을 계산할 때 들어가는 다른 시도
OTHER_PROVINCES = {
    "강원특별자치도": ["춘천시", "원주시", "강릉시", "속초시"],
    "경상남도": ["창원시 성산구", "김해시", "진주시", "양산시"],
    "경상북도": ["포항시 북구", "구미시", "경산시", "안동시"],
    "광주광역시": ["동구", "서구", "남구", "북구", "광산구"],
    "대구광역시": ["중구", "동구", "수성구", "달서구", "북구"],
    "대전광역시": ["동구", "중구", "서구", "유성구", "대덕구"],
    "세종특별자치시": ["세종특별자치시"],
    "울산광역시": ["중구", "남구", "동구", "북구", "울주군"],
    "인천광역시": ["중구", "미추홀구", "연수구", "남동구", "부평구", "서구"],
    "전라남도": ["목포시", "여수시", "순천시"],
    "전북특별자치도": ["전주시 완산구", "전주시 덕진구", "군산시", "익산시"],
    "제주특별자치도": ["제주시", "서귀포시"],
    "충청남도": ["천안시 서북구", "천안시 동남구", "아산시", "서산시"],
    "충청북도": ["청주시 흥덕구", "청주시 상당구", "충주시", "제천시"],
}

# 경기 유동인구가 제공되는 16개 시군. '연천시'는 원본 파일명의 오타를 그대로 재현한 것입니다.
GYEONGGI_FLOW_CITIES = ["광명시", "김포시", "남양주시", "성남시", "수원시", "시흥시", "안산시", "안양시",
                        "여주시", "연천시", "용인시", "의정부시", "파주시", "포천시", "하남시", "화성시"]

# BC카드 업종 코드 → 원본 표기(공백 포함) · 기본 월 매출 규모(원) · 평균 결제 금액(원) · 연령 구성
# 연령 구성 순서: AGE_CD 1~6 = 20대이하, 20대, 30대, 40대, 50대, 60대이상
# 매출 규모와 연령 구성은 원본에서 계산한 값이 아니라 업종 성격을 생각해 직접 정한 값입니다.
INDUSTRIES = {
    "4004": ("대형할인점", 6.0e9, 60_000, [0.02, 0.10, 0.22, 0.28, 0.22, 0.16]),
    "4010": ("편 의 점", 5.0e9, 8_000, [0.12, 0.30, 0.22, 0.16, 0.12, 0.08]),
    "4020": ("슈퍼 마켓", 4.0e9, 25_000, [0.03, 0.12, 0.20, 0.24, 0.22, 0.19]),
    "8001": ("일반한식", 8.0e9, 25_000, [0.03, 0.12, 0.18, 0.22, 0.23, 0.22]),
    "8002": ("갈비전문점", 1.5e9, 60_000, [0.02, 0.12, 0.20, 0.25, 0.24, 0.17]),
    "8003": ("한정식", 0.5e9, 70_000, [0.01, 0.06, 0.14, 0.24, 0.28, 0.27]),
    "8004": ("일식회집", 1.2e9, 55_000, [0.02, 0.12, 0.22, 0.26, 0.22, 0.16]),
    "8005": ("중국음식", 1.5e9, 22_000, [0.05, 0.20, 0.24, 0.22, 0.17, 0.12]),
    "8006": ("서양음식", 3.0e9, 35_000, [0.05, 0.28, 0.30, 0.20, 0.11, 0.06]),
    "8021": ("스넥", 1.0e9, 9_000, [0.10, 0.30, 0.24, 0.17, 0.12, 0.07]),
    "8301": ("제 과 점", 1.0e9, 12_000, [0.06, 0.24, 0.26, 0.20, 0.14, 0.10]),
}

# 5세 구간 시작 나이 0, 5, ..., 90 과 마지막 '95세 이상' → 20개 구간
FIVE_YEAR_STARTS = list(range(0, 100, 5))

# 2026년 연령 구조(인구 피라미드)의 대략적인 모양. 20개 5세 구간의 상대 크기입니다.
BASE_PYRAMID = np.array([3.0, 3.5, 4.0, 4.5, 6.0, 6.5, 6.5, 7.0, 7.5, 8.0,
                         8.5, 8.5, 7.5, 6.0, 4.5, 3.5, 2.5, 1.5, 0.7, 0.3])

# 2026 → 2040년 인구 증감률(%)의 기본 방향. 저출산 · 고령화로 젊을수록 줄고 나이 들수록 느는 모양입니다.
def change_rate_2040(start_age):
    if start_age < 20:
        return -30.0
    if start_age < 30:
        return -25.0
    if start_age < 40:
        return -20.0
    if start_age < 50:
        return -15.0
    if start_age < 60:
        return -8.0
    if start_age < 70:
        return 15.0
    return 45.0


# ===========================================================================
# 엑셀 저장
# ===========================================================================

FIXED_SAVE_TIME = (2026, 1, 1, 0, 0, 0)


def save_excel(table, path):
    """엑셀로 저장하되, 파일 안에 기록되는 '저장 시각'을 고정합니다.

    xlsx는 압축 파일이라 안쪽 파일마다 저장 시각이 들어가고, docProps/core.xml에도 작성 · 수정 시각이 남습니다.
    그대로 두면 같은 시드로 만들어도 실행할 때마다 바이트가 달라져서 Bronze 영수증의 SHA-256이 바뀝니다.
    시각을 고정하면 같은 시드 → 같은 해시가 되어, Bronze가 '변경 없음'으로 판단할 수 있습니다.
    """
    buffer = io.BytesIO()
    table.to_excel(buffer, index=False)
    with zipfile.ZipFile(buffer) as source, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                content = re.sub(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", b"2026-01-01T00:00:00Z", content)
            target.writestr(zipfile.ZipInfo(item.filename, FIXED_SAVE_TIME), content, zipfile.ZIP_DEFLATED)


# ===========================================================================
# 장래인구 (모든 인구 파일의 기준이 되는 2026년 연령 구조도 여기서 만듦)
# ===========================================================================

def make_population_by_year(rng, total_population, years):
    """한 지역의 5세 구간 × 연도별 인구를 만듭니다.

    Returns:
        DataFrame (행: 20개 5세 구간, 열: 연도)
    """
    shares = rng.dirichlet(BASE_PYRAMID * 40)          # 지역마다 연령 구조가 조금씩 다르게
    base = total_population * shares
    table = {}
    for year in years:
        factors = []
        for start in FIVE_YEAR_STARTS:
            # 연도에 비례해 증감 (2026년 = 1배). 지역마다 증감 폭에 ±6%p 차이를 둡니다.
            rate = (change_rate_2040(start) + rng.normal(0, 6)) / 100
            factors.append(1 + rate * (year - config.POPULATION_BASE_YEAR) / 14)
        table[year] = np.maximum(base * np.array(factors), 0).round()
    return pd.DataFrame(table, index=FIVE_YEAR_STARTS)


def split_by_sex(rng, by_year):
    """구간 × 연도 인구를 남자 · 여자로 나눕니다 (구간마다 남자 비율 46~52%)."""
    male_ratio = rng.uniform(0.46, 0.52, size=len(by_year))
    male = (by_year.to_numpy() * male_ratio[:, None]).round()
    return male, by_year.to_numpy() - male


def split_into_single_years(rng, value):
    """5세 구간 인구를 1세 단위 5개로 나눕니다 (합은 그대로)."""
    parts = rng.dirichlet(np.ones(5) * 50) * value
    parts = parts.round()
    parts[-1] = value - parts[:-1].sum()
    return parts


def write_seoul_future_csv(path, rng, populations):
    """서울 장래인구 CSV: 모든 칸을 따옴표로 감싸고 머리글 끝에 빈 열이 있는 원본 형식."""
    years = list(range(2022, 2043))
    header = ["자치구별", "성별", "연령별", "항목", "단위"] + [f"{y} 년" for y in years] + [""]
    rows = []
    blocks = {"합계": sum(populations.values())}
    blocks.update(populations)
    for district, by_year in blocks.items():
        by_year = by_year[years]
        male, female = split_by_sex(rng, by_year)
        for sex, values in [("계", by_year.to_numpy()), ("남자", male), ("여자", female)]:
            values = np.asarray(values)
            def add(label, numbers):
                rows.append([district, sex, label, "성 및 연령별 추계인구(1세별, 5세별)", ""]
                            + [str(int(v)) for v in numbers] + [""])
            add("합계", values.sum(axis=0))
            for i, start in enumerate(FIVE_YEAR_STARTS):
                label = "95세 이상" if start == 95 else f"{start}~{start + 4}세"
                add(label, values[i])
                if start < 95:   # 1세 단위 행 (5세 구간과 섞여 있어서 그냥 더하면 두 번 세게 됨)
                    singles = np.array([split_into_single_years(rng, v) for v in values[i]]).T
                    for offset in range(5):
                        add(f"{start + offset}세", singles[offset])
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)


def write_kosis_future_xlsx(path, rng, province_name, populations, years):
    """부산 · 경기 장래인구 엑셀: 병합 셀처럼 블록 첫 행에만 시군구 · 성별이 있는 KOSIS 형식."""
    rows = []
    blocks = {province_name: sum(populations.values())}
    blocks.update(populations)
    for district, by_year in blocks.items():
        by_year = by_year[years]
        male, female = split_by_sex(rng, by_year)
        first_in_district = True
        for sex, values in [("계", by_year.to_numpy()), ("남자", male), ("여자", female)]:
            values = np.asarray(values)
            first_in_sex = True
            def add(age_label, sub_label, numbers):
                nonlocal first_in_district, first_in_sex
                rows.append([district if first_in_district else None, sex if first_in_sex else None,
                             age_label, sub_label] + [int(v) for v in numbers])
                first_in_district = first_in_sex = False
            add("계", "소계", values.sum(axis=0))
            for i, start in enumerate(FIVE_YEAR_STARTS):
                label = "95세 이상" if start == 95 else f"{start} - {start + 4}세"
                add(label, "소계", values[i])
                if start < 95:
                    singles = np.array([split_into_single_years(rng, v) for v in values[i]]).T
                    for offset in range(5):
                        add(None, f"{start + offset}세", singles[offset])
    save_excel(pd.DataFrame(rows, columns=["시군구별", "성별", "연령별(1)", "연령별(2)"] + years), path)


# ===========================================================================
# 주민등록인구 (행정안전부 형식, cp949)
# ===========================================================================

RESIDENT_AGE_LABELS = ["0~9세", "10~19세", "20~29세", "30~39세", "40~49세", "50~59세",
                       "60~69세", "70~79세", "80~89세", "90~99세", "100세 이상"]


def to_ten_year_groups(five_year_counts):
    """20개 5세 구간 → 주민등록인구의 11개 10세 구간 (95세 이상은 90~99세와 100세 이상으로 나눔)."""
    values = np.asarray(five_year_counts)
    groups = [values[i] + values[i + 1] for i in range(0, 18, 2)]       # 0~9 ... 80~89
    groups.append(values[18] + values[19] * 0.8)                         # 90~99
    groups.append(values[19] * 0.2)                                      # 100세 이상
    return np.array(groups)


def write_resident_population_csvs(folder, rng, regions):
    """월별 주민등록인구 CSV 6개.

    Args:
        regions: [(행정구역 이름, 5세 구간 2026년 인구)] · 시도 합계 행도 포함
    """
    for month in config.ANALYSIS_MONTHS:
        prefix = f"{str(month)[:4]}년{str(month)[4:]}월_"
        rows = []
        for code_number, (name, counts) in enumerate(regions, start=1):
            month_drift = 1 + rng.normal(0, 0.002)                    # 달마다 아주 조금씩 변함
            total = to_ten_year_groups(counts) * month_drift
            male_ratio = rng.uniform(0.47, 0.51)
            row = {"행정구역": f"{name} ({1100000000 + code_number * 10000})"}
            for sex, values in [("계", total), ("남", total * male_ratio), ("여", total * (1 - male_ratio))]:
                values = values.round().astype(int)
                row[f"{prefix}{sex}_총인구수"] = f"{values.sum():,}"
                row[f"{prefix}{sex}_연령구간인구수"] = f"{values.sum():,}"
                for label, value in zip(RESIDENT_AGE_LABELS, values):
                    row[f"{prefix}{sex}_{label}"] = f"{value:,}"
            rows.append(row)
        pd.DataFrame(rows).to_csv(folder / f"population_{month}.csv", index=False, encoding="cp949")


# ===========================================================================
# 생활인구 · 유동인구
# ===========================================================================

SEOUL_LIVING_RANGES = ["0t9", "10t14", "15t19", "20t24", "25t29", "30t34", "35t39", "40t44", "45t49",
                       "50t54", "55t59", "60t64", "65t69", "70t74"]
# 낮에는 일하는 연령(20~50대)이 더 많이 머무른다고 보고 연령 구성을 조금 기울입니다.
DAYTIME_TILT = np.array([0.8, 0.8, 0.9, 1.2, 1.3, 1.3, 1.3, 1.2, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7])


def write_seoul_living_csv(path, rng, populations):
    """서울 생활인구 CSV: 자치구 코드 × 날짜 × 시간대 행, 성별 × 5세 열(74세까지)."""
    rows = []
    code_by_name = {name: code for code, name in SEOUL_DISTRICT_CODE_TO_NAME.items()}
    days = [f"2025{m:02d}15" for m in range(1, 13)]                   # 달마다 하루씩 (원본은 매일)
    for district, by_year in populations.items():
        base = to_age_ranges_up_to_74(by_year[config.POPULATION_BASE_YEAR].to_numpy())
        for day in days:
            for hour in range(24):
                tilt = DAYTIME_TILT if 9 <= hour <= 18 else np.ones_like(DAYTIME_TILT)
                level = rng.uniform(0.85, 1.25)                         # 구마다 · 시간마다 유입 규모가 다름
                male = base * tilt * level * rng.uniform(0.46, 0.52) * rng.uniform(0.95, 1.05, len(base))
                female = base * tilt * level * rng.uniform(0.48, 0.54) * rng.uniform(0.95, 1.05, len(base))
                row = {"stdr_de_id": int(day), "tmzon_pd_se": hour, "adstrd_code_se": code_by_name[district],
                       "tot_lvpop_co": round(float(male.sum() + female.sum()) * 1.03, 4)}
                row.update({f"male_f{r}_lvpop_co": round(float(v), 4) for r, v in zip(SEOUL_LIVING_RANGES, male)})
                row.update({f"female_f{r}_lvpop_co": round(float(v), 4) for r, v in zip(SEOUL_LIVING_RANGES, female)})
                row["ldadng_dt"] = 20250106060917
                rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def to_age_ranges_up_to_74(five_year_counts):
    """20개 5세 구간 → 서울 생활인구 열 14개(0~9세를 하나로, 74세까지만)."""
    values = np.asarray(five_year_counts)
    return np.concatenate([[values[0] + values[1]], values[2:15]])


BUSAN_LIVING_AGE_LABELS = ["20대미만", "20대", "30대", "40대", "50대", "60대이상"]


def write_busan_living_xlsx(path, rng):
    """부산 생활인구 엑셀: 행정동 × 월 × 나이대. 2024년 12월 행도 넣어 '2025년만 쓰기' 필터를 확인합니다."""
    rows = []
    months = [202412] + [202500 + m for m in range(1, 13)]
    for gu_index, gu in enumerate(BUSAN_DISTRICTS):
        resident_share = rng.uniform(0.45, 0.85)                       # 구마다 '사는 사람' 비율이 다름
        for dong in range(1, 4):
            dong_code = 2611000000 + gu_index * 10000 + dong * 100
            for month in months:
                for age in BUSAN_LIVING_AGE_LABELS:
                    total = rng.uniform(800, 6000)
                    resident = total * resident_share * rng.uniform(0.9, 1.1)
                    rest = total - resident
                    rows.append([month, dong_code, f"{gu} 제{dong}동", age,
                                 round(resident), round(rest * 0.55), round(rest * 0.45)])
    save_excel(pd.DataFrame(rows, columns=["기준년월", "행정동코드", "행정동명", "나이대",
                                           "평균주거인구수", "평균직장인구수", "평균방문인구수"]), path)


FLOW_AGE_STARTS = ["10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60", "65", "70"]


def write_gyeonggi_flow_folder(folder, rng):
    """경기 유동인구: 시군 × 월마다 CSV 하나. 일반구가 있는 시는 CTY_NM에 구 이름까지 적습니다."""
    folder.mkdir(parents=True, exist_ok=True)
    for city_index, city in enumerate(GYEONGGI_FLOW_CITIES):
        districts = GYEONGGI_CITIES.get(city, [])
        names = [f"{city} {d}" for d in districts] or [city]
        age_weights = rng.dirichlet(np.ones(len(FLOW_AGE_STARTS)) * 8)
        for month in config.ANALYSIS_MONTHS[:3]:
            rows = []
            for name in names:
                for time_code in range(24):
                    for foreign in ("N", "F"):
                        scale = rng.uniform(2000, 9000) * (0.05 if foreign == "F" else 1)
                        row = {"CTY_CD": 41000 + city_index * 10, "CTY_NM": name, "TIME_CD": time_code, "FORN_GB": foreign}
                        for sex in ("M", "F"):
                            for start, weight in zip(FLOW_AGE_STARTS, age_weights):
                                row[f"{sex}_{start}_CNT"] = round(scale * weight * rng.uniform(0.9, 1.1), 2)
                        row["ETL_YMD"] = int(f"{month}01") + 100
                        rows.append(row)
            file_name = f"T21_GG_SGG_FLOWPOP_{month}_{city}.csv"
            pd.DataFrame(rows).to_csv(folder / file_name, index=False, encoding="utf-8-sig")


# ===========================================================================
# BC카드 결제
# ===========================================================================

def card_regions():
    """BC카드에 나오는 (시도, 시군구) 목록. 경기는 일반구 단위로 나옵니다."""
    regions = [("서울특별시", d) for d in SEOUL_DISTRICTS] + [("부산광역시", d) for d in BUSAN_DISTRICTS]
    for city, districts in GYEONGGI_CITIES.items():
        regions += [("경기도", f"{city} {d}") for d in districts] or [("경기도", city)]
    for province, districts in OTHER_PROVINCES.items():
        regions += [(province, d) for d in districts]
    return regions


def write_card_csv(path, rng, months=None):
    """BC카드 결제 CSV (월 × 시도 × 시군구 × 성별 × 연령 × 업종).

    만드는 방법
        1. 지역 × 업종마다 월 매출 규모를 정합니다 (업종 기본 규모 × 지역 규모, 서울은 조금 더 크게).
        2. 연령 구성은 업종의 기본 구성을 중심으로 지역마다 조금씩 다르게 뽑습니다 (디리클레 분포).
        3. 월별로 추세(평균 -0.3%, 표준편차 1.5%)와 잡음을 곱해 성장하는 곳과 아닌 곳이 섞이게 합니다.
        4. 지역 × 업종의 3%는 한 달을 통째로 빼서 '6개월이 다 없는' 사례를 만듭니다.
        5. 개인이 아닌 결제(성별 3, 성별 · 연령 x)를 전체 금액의 약 12%로 섞습니다 (Silver에서 빠져야 하는 행).
        6. 원본처럼 결제 10건 이하인 칸은 빼고 씁니다 (원본 제공처가 작은 칸을 빼고 제공함, config.MIN_CARD_PAYMENT_COUNT).

    months: 만들 달 (기본 2026.01 ~ 06). 다음 달 원본을 시험할 때는 그 달 하나만 넘깁니다 (write_synthetic_next_month).
    """
    months = months or config.ANALYSIS_MONTHS
    rows = []
    for province, district in card_regions():
        region_scale = rng.lognormal(0.3 if province == "서울특별시" else 0.0, 0.6)
        for code, (name, base_amount, ticket, age_profile) in INDUSTRIES.items():
            age_shares = rng.dirichlet(np.array(age_profile) * 60)
            monthly_trend = rng.normal(-0.003, 0.015)
            missing_month = rng.choice(months) if rng.random() < 0.03 else None
            level = base_amount * region_scale * rng.uniform(0.5, 1.5)
            for month_index, month in enumerate(months):
                if month == missing_month:
                    continue
                month_total = level * (1 + monthly_trend) ** month_index * (1 + rng.normal(0, 0.015))
                male_ratio = rng.normal(0.5, 0.08)
                for age_code, share in enumerate(age_shares, start=1):
                    for gender, ratio in (("1", male_ratio), ("2", 1 - male_ratio)):
                        amount = month_total * share * ratio
                        rows.append(card_row(rng, month, province, district, gender, str(age_code), code, name, amount, ticket))
                    # 법인 등 개인이 아닌 결제 (성별 코드 3, 연령은 있음)
                    rows.append(card_row(rng, month, province, district, "3", str(age_code), code, name,
                                         month_total * share * 0.10, ticket))
                # 성별 · 연령을 알 수 없는 결제
                rows.append(card_row(rng, month, province, district, "x", "x", code, name, month_total * 0.04, ticket))
    table = pd.DataFrame(rows, columns=["STRD_YYMM", "SIDO_NM", "CCG_NM", "GENDER_CD", "AGE_CD",
                                        "TP_BUZ_NO", "TP_BUZ_NM", "amt", "cnt"])
    table[table["cnt"] >= config.MIN_CARD_PAYMENT_COUNT].to_csv(path, index=False, encoding="utf-8-sig")


def card_row(rng, month, province, district, gender, age, code, name, amount, ticket):
    """결제 행 하나. 금액은 원본처럼 만 원 단위로 반올림합니다."""
    amount = max(amount * rng.uniform(0.97, 1.03), 10_000)
    amount = int(round(amount / 10_000) * 10_000)
    count = max(int(amount / (ticket * rng.uniform(0.8, 1.2))), 1)
    return [month, province, district, gender, age, code, name, amount, count]


# ===========================================================================
# 전체 생성
# ===========================================================================

def write_synthetic_raw_files(raw_dir, seed=42):
    """data/raw와 같은 이름 · 형식의 합성 원본 8종을 만듭니다.

    Returns:
        만든 폴더 경로
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    # 1) 장래인구: 시군구마다 5세 구간 × 2015~2042년 인구를 먼저 만들고, 다른 인구 파일도 2026년 값을 기준으로 씁니다.
    all_years = list(range(2015, 2043))
    seoul = {d: make_population_by_year(rng, rng.uniform(150_000, 650_000), all_years) for d in SEOUL_DISTRICTS}
    busan = {d: make_population_by_year(rng, rng.uniform(40_000, 400_000), all_years) for d in BUSAN_DISTRICTS}
    gyeonggi = {c: make_population_by_year(rng, rng.uniform(40_000, 1_100_000), all_years) for c in GYEONGGI_CITIES}

    write_seoul_future_csv(raw_dir / "seoul_future_population_2022_2042.csv", rng, seoul)
    write_kosis_future_xlsx(raw_dir / "busan_future_population_2015_2040.xlsx", rng, "부산광역시", busan,
                            list(range(2015, 2041)))
    write_kosis_future_xlsx(raw_dir / "gyeonggi_future_population_2022_2042.xlsx", rng, "경기도", gyeonggi,
                            list(range(2022, 2043)))

    # 2) 주민등록인구: 시도 합계 행 + 시군구 행 (경기는 시 행과 일반구 행이 함께 있음)
    base_year = config.POPULATION_BASE_YEAR
    resident_regions = [("서울특별시 ", sum(p[base_year] for p in seoul.values()))]
    resident_regions += [(f"서울특별시 {d}", p[base_year]) for d, p in seoul.items()]
    resident_regions += [("부산광역시 ", sum(p[base_year] for p in busan.values()))]
    resident_regions += [(f"부산광역시 {d}", p[base_year]) for d, p in busan.items()]
    resident_regions += [("경기도 ", sum(p[base_year] for p in gyeonggi.values()))]
    for city, population in gyeonggi.items():
        resident_regions.append((f"경기도 {city}", population[base_year]))
        districts = GYEONGGI_CITIES[city]
        for district in districts:
            resident_regions.append((f"경기도 {city} {district}", population[base_year] / len(districts)))
    resident_regions += [("세종특별자치시 ", seoul["중구"][base_year] * 2)]   # 하위 시군구가 없는 세종시 형식
    write_resident_population_csvs(raw_dir, rng, resident_regions)

    # 3) 생활인구 · 유동인구
    write_seoul_living_csv(raw_dir / "seoul_living_population_2025.csv", rng, seoul)
    write_busan_living_xlsx(raw_dir / "busan_living_population_age.xlsx", rng)
    write_gyeonggi_flow_folder(raw_dir / "gyeonggi_flow_202601_202603", rng)

    # 4) BC카드 결제
    write_card_csv(raw_dir / "bc_card_202601_202606.csv", rng)
    return raw_dir


def write_synthetic_next_month(raw_dir, month, seed=42):
    """다음 달 BC카드 원본 하나(bc_card_<월>_<월>.csv)를 만듭니다. 월 배치가 새 달을 처리하는지 시험하는 용도.

    시드에 달을 섞어(seed, month) 같은 달은 언제 만들어도 같은 파일이 됩니다. 기존 6개월 파일은 건드리지 않습니다.
    지역 × 업종의 매출 규모를 새로 뽑으므로 앞 달과 이어지지는 않습니다 (숫자에는 뜻이 없고, 흐름만 시험).
    """
    path = Path(raw_dir) / f"bc_card_{month}_{month}.csv"
    write_card_csv(path, np.random.default_rng([seed, month]), months=[month])
    return path


def main():
    parser = argparse.ArgumentParser(description="원본과 같은 형식의 합성 원본 데이터 생성")
    parser.add_argument("--output", default=config.SYNTHETIC_RAW_DIR, help="저장 폴더 (기본: data/synthetic/raw)")
    parser.add_argument("--seed", type=int, default=42, help="같은 시드면 같은 데이터가 나옵니다")
    parser.add_argument("--next-month", type=int, default=None,
                        help="이 달(예: 202607)의 BC카드 원본 하나만 더 만듦 (월 배치 시험)")
    arguments = parser.parse_args()
    if arguments.next_month:
        path = write_synthetic_next_month(arguments.output, arguments.next_month, arguments.seed)
        print(f"다음 달 합성 원본을 만들었습니다: {path}")
        return
    folder = write_synthetic_raw_files(arguments.output, arguments.seed)
    print(f"합성 원본을 {folder}에 만들었습니다.")


if __name__ == "__main__":
    main()
