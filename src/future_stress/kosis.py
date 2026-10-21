"""KOSIS(국가통계포털) OpenAPI로 장래인구를 받아 오는 수집기.

왜 필요한가요?
    공모전 때는 장래인구를 KOSIS 사이트에서 엑셀 · CSV로 직접 내려받았습니다.
    매번 손으로 받으면 어떤 파일을 언제 받았는지 기록이 남지 않고, 다시 받을 때 같은 조건으로 받았는지도 알 수 없습니다.
    이 모듈은 같은 통계표를 API로 받아서, 받은 응답을 손대지 않고 저장하고 언제 받았는지 기록합니다.

받는 통계표 (둘 다 2022년 기준 장래인구추계, 2022~2042년)
    서울: 서울특별시 자치구별 장래인구추계 · 성 및 연령별 추계인구   orgId=101, tblId=INH_PB0001_2022_11
    경기: 경기도 시군단위 장래인구추계 · 성및연령별 추계인구         orgId=101, tblId=INH_PB0001_2022_31
    부산 구군별 장래인구(2015~2040)는 부산시가 따로 낸 자료라 KOSIS에 없습니다. 부산은 지금처럼 파일을 씁니다.

수집기가 지키는 것
    1. 일시적인 오류(연결 끊김, 서버 오류, 호출 제한)는 최대 3번까지 시도하며, 사이에 2초 → 4초로 점점 길게 기다립니다.
       인증키 오류처럼 다시 해도 소용없는 오류는 바로 멈추고, KOSIS가 보낸 메시지를 그대로 보여 줍니다.
    2. KOSIS는 한 번에 받을 수 있는 셀 수에 제한이 있어서, 연도별로 나눠 받습니다.
    3. 두 번 받아도 같은 파일이 나옵니다. 행을 정렬해서 저장하고, 받은 시각은 데이터 파일이 아니라
       기록 파일(_collect_log.jsonl)에 따로 남깁니다. 내용이 같으면 파일을 다시 쓰지 않고 '변경 없음'으로 기록합니다.
    4. API로 받은 값이 원래 내려받은 파일 값과 같은지 비교할 수 있습니다 (compare_with_files).

인증키
    코드에 쓰지 않습니다. 환경변수 KOSIS_API_KEY나 저장소 루트의 .env 파일(KOSIS_API_KEY=...)에서 읽습니다.
    .env는 .gitignore에 들어 있어 저장소에 올라가지 않습니다.

실행 방법 (저장소 루트에서)
    .venv\\Scripts\\python -m future_stress.kosis collect    # data/raw/kosis/ 에 저장
    .venv\\Scripts\\python -m future_stress.kosis collect --env-file <다른 프로젝트의 .env>   # 키를 다른 .env에서 읽기
    .venv\\Scripts\\python -m future_stress.kosis compare    # 받은 값과 data/raw의 파일 값 비교
"""

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from . import config
from .io_utils import read_env_value
from .population import POPULATION_YEARS

API_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


@dataclass(frozen=True)
class KosisTable:
    """KOSIS 통계표 하나를 가리키는 정보.

    file_name은 같은 통계를 예전에 사이트에서 내려받은 파일 이름입니다 (compare_with_files에서 사용).
    """
    key: str
    org_id: str
    tbl_id: str
    title: str
    province: str
    file_name: str


FUTURE_POPULATION_TABLES = {
    "seoul": KosisTable("seoul", "101", "INH_PB0001_2022_11",
                        "서울특별시 자치구별 장래인구추계 · 성 및 연령별 추계인구(1세별, 5세별)",
                        "서울특별시", "seoul_future_population_2022_2042.csv"),
    "gyeonggi": KosisTable("gyeonggi", "101", "INH_PB0001_2022_31",
                           "경기도 시군단위 장래인구추계 · 성및연령별 추계인구(1세별, 5세별)",
                           "경기도", "gyeonggi_future_population_2022_2042.xlsx"),
}

# 다시 시도할 HTTP 상태: 호출 제한(429)과 일시적인 서버 오류(5xx)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# KOSIS는 오류도 HTTP 200에 {"err": "코드", "errMsg": "설명"}으로 보냅니다.
# 그중 서버 쪽 일시적인 오류(50)만 다시 시도하고, 나머지(인증키 · 요청변수 · 조회 결과 없음 · 호출 한도)는 바로 멈춥니다.
# 호출 한도는 하루 단위라 몇 초 뒤에 다시 보내도 풀리지 않기 때문입니다.
RETRYABLE_KOSIS_ERRORS = {"50"}

COLLECT_LOG_NAME = "_collect_log.jsonl"


class KosisApiError(RuntimeError):
    """KOSIS가 오류 응답을 보냈을 때. 코드와 KOSIS의 설명을 함께 담습니다."""

    def __init__(self, code, message):
        super().__init__(f"KOSIS 오류 {code}: {message}")
        self.code = code


def read_api_key(env_file=None):
    """KOSIS 인증키를 환경변수 → .env 파일 순서로 찾습니다 (io_utils.read_env_value 참고)."""
    return read_env_value("KOSIS_API_KEY", env_file)


class KosisClient:
    """KOSIS OpenAPI 호출을 담당합니다.

    사용 예
        client = KosisClient.from_environment()
        rows = client.fetch_year(FUTURE_POPULATION_TABLES["seoul"], 2040)
    """

    def __init__(self, api_key, max_retries=3, retry_wait_seconds=2.0, timeout_seconds=30, session=None):
        if not api_key:
            raise ValueError("KOSIS 인증키가 없습니다. 환경변수 KOSIS_API_KEY 또는 .env 파일에 넣어 주세요 (.env.example 참고).")
        self.api_key = api_key
        self.max_retries = max_retries
        self.retry_wait_seconds = retry_wait_seconds
        self.timeout_seconds = timeout_seconds
        # Session을 쓰면 같은 서버에 여러 번 요청할 때 연결을 재사용합니다. 테스트에서는 가짜 세션을 넘깁니다.
        self.session = session or requests.Session()

    @classmethod
    def from_environment(cls, env_file=None, **options):
        return cls(read_api_key(env_file), **options)

    def _get(self, params):
        """GET 요청을 보내고 응답 행 목록을 돌려줍니다. 일시적인 오류면 점점 길게 기다리며 다시 시도합니다."""
        for attempt in range(1, self.max_retries + 1):
            is_last_attempt = attempt == self.max_retries
            try:
                response = self.session.get(API_URL, params={**params, "apiKey": self.api_key},
                                            timeout=self.timeout_seconds)
            except (requests.ConnectionError, requests.Timeout) as error:
                # requests의 오류 메시지에는 요청 주소 전체(인증키 포함)가 들어 있어서, 그대로 올리지 않고 종류만 남깁니다.
                problem = f"연결 오류 ({type(error).__name__})"
                if is_last_attempt:
                    raise KosisApiError("연결", problem) from None
            else:
                if response.status_code == 200:
                    payload = response.json()
                    if not (isinstance(payload, dict) and "err" in payload):
                        return payload
                    code = str(payload["err"])
                    if code not in RETRYABLE_KOSIS_ERRORS or is_last_attempt:
                        raise KosisApiError(code, payload.get("errMsg", ""))
                    problem = f"KOSIS 오류 {code}"
                elif response.status_code in RETRYABLE_STATUS_CODES and not is_last_attempt:
                    problem = f"HTTP {response.status_code}"
                else:
                    raise KosisApiError(f"HTTP {response.status_code}", response.text[:200])
            wait_seconds = self.retry_wait_seconds * 2 ** (attempt - 1)
            print(f"  {problem} → {wait_seconds:.0f}초 뒤 다시 시도 ({attempt}/{self.max_retries})")
            time.sleep(wait_seconds)
        return None

    def fetch_year(self, table, year):
        """통계표 한 개의 한 해치 값을 모두 받습니다.

        분류(지역 · 성별 · 연령)와 항목은 모두 'ALL'로 받습니다. 어떤 값을 쓸지는 받은 뒤에 고르는 편이,
        나중에 기준이 바뀌어도 다시 받지 않아도 되기 때문입니다.
        """
        return self._get({
            "method": "getList", "orgId": table.org_id, "tblId": table.tbl_id,
            "itmId": "ALL", "objL1": "ALL", "objL2": "ALL", "objL3": "ALL",
            "prdSe": "Y", "startPrdDe": str(year), "endPrdDe": str(year),
            "format": "json", "jsonVD": "Y",
        })


# ===========================================================================
# 저장 (두 번 받아도 같은 파일)
# ===========================================================================

def landing_path(output_dir, table, year):
    """받은 응답을 저장할 위치: <output_dir>/<통계표 ID>/<연도>.json"""
    return Path(output_dir) / table.tbl_id / f"{year}.json"


def landing_json(table, year, rows):
    """응답 행을 정렬해서 JSON 바이트로 만듭니다. 받은 시각 같은 '실행마다 바뀌는 값'은 넣지 않습니다."""
    sorted_rows = sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    document = {"org_id": table.org_id, "tbl_id": table.tbl_id, "title": table.title, "year": year,
                "rows": sorted_rows}
    return json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")


def write_if_changed(path, content):
    """내용이 다를 때만 파일을 씁니다. Returns: '신규' / '변경' / '변경 없음'"""
    path = Path(path)
    if path.exists():
        if path.read_bytes() == content:
            return "변경 없음"
        status = "변경"
    else:
        status = "신규"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return status


def collect_future_population(client, output_dir=None, tables=None, years=None):
    """서울 · 경기 장래인구를 연도별로 받아 저장하고, 받은 기록을 _collect_log.jsonl에 한 줄씩 덧붙입니다.

    Returns:
        이번 실행 기록 DataFrame (통계표 | 연도 | 행 수 | 상태 | 파일 | sha256)
    """
    output_dir = Path(output_dir or config.KOSIS_RAW_DIR)
    tables = tables or list(FUTURE_POPULATION_TABLES.values())
    years = years or POPULATION_YEARS
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    records = []
    for table in tables:
        for year in years:
            rows = client.fetch_year(table, year)
            content = landing_json(table, year, rows)
            path = landing_path(output_dir, table, year)
            records.append({
                "collected_at": collected_at, "tbl_id": table.tbl_id, "year": year, "rows": len(rows),
                "status": write_if_changed(path, content),
                "file": path.relative_to(output_dir).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
            })

    # 기록은 덮어쓰지 않고 덧붙입니다. 언제 받았고 그때 내용이 바뀌었는지가 계속 남게 하기 위해서입니다.
    with open(output_dir / COLLECT_LOG_NAME, "a", encoding="utf-8") as log:
        for record in records:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
    return pd.DataFrame(records).rename(columns={
        "tbl_id": "통계표", "year": "연도", "rows": "행 수", "status": "상태", "file": "파일"})


# ===========================================================================
# 받은 값과 예전 파일 값 비교
# ===========================================================================

def normalize_age_label(label):
    """'0 - 4세', '0~4세', '95세 이상' → '0-4세', '95세이상' (표기 차이만 없앰)"""
    return str(label).replace(" ", "").replace("~", "-")


def is_five_year_label(label):
    """5세 구간(예: '0-4세')이나 마지막 구간(예: '95세이상')인지. '계'나 1세 단위('0세')는 제외됩니다."""
    text = normalize_age_label(label)
    return bool(re.fullmatch(r"\d+-\d+세", text)) or text.endswith("세이상")


def find_dimension_columns(api_rows):
    """응답에서 지역 · 성별 · 연령이 각각 몇 번째 분류(C1_NM, C2_NM, ...)인지 찾습니다.

    분류 순서는 통계표마다 다를 수 있어서, 순서를 가정하지 않고 값의 모양으로 판단합니다.
        연령: 값 대부분에 '세'가 들어 있음
        성별: 값이 계 · 남자 · 여자뿐
        지역: 나머지
    """
    frame = pd.DataFrame(api_rows)
    name_columns = [c for c in frame.columns if re.fullmatch(r"C\d_NM", c)]
    found = {}
    for column in name_columns:
        values = set(frame[column].dropna().astype(str))
        if values <= {"계", "남자", "여자", "남", "여"}:
            found["성별"] = column
        elif sum("세" in v for v in values) > len(values) / 2:
            found["연령"] = column
        else:
            found["지역"] = column
    if set(found) != {"지역", "성별", "연령"}:
        raise ValueError(f"지역 · 성별 · 연령 분류를 찾지 못했습니다: {found}, 분류 열 {name_columns}")
    return found


def five_year_population_from_api(api_rows, province):
    """API 응답 → 시군구 | 연령구간 | 연도 | 인구 (남녀 합계, 5세 구간, 시도 합계 행 제외)"""
    frame = pd.DataFrame(api_rows)
    items = frame["ITM_NM"].unique() if "ITM_NM" in frame else []
    if len(items) > 1:
        raise ValueError(f"항목이 여러 개입니다. 어떤 항목을 쓸지 정해야 합니다: {list(items)}")
    columns = find_dimension_columns(api_rows)
    keep = (
        (frame[columns["성별"]] == "계")
        & frame[columns["연령"]].map(is_five_year_label)
        & ~frame[columns["지역"]].isin([province, "합계", "계"])
    )
    selected = frame[keep]
    return pd.DataFrame({
        "시군구": selected[columns["지역"]].str.strip(),
        "연령구간": selected[columns["연령"]].map(normalize_age_label),
        "연도": selected["PRD_DE"].astype(int),
        "인구": pd.to_numeric(selected["DT"], errors="coerce"),
    }).reset_index(drop=True)


def five_year_population_from_seoul_file(path, years):
    """예전에 내려받은 서울 CSV → 같은 모양의 표. (닫히지 않은 따옴표 때문에 csv 모듈로 읽음, population.py 참고)"""
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    raw = pd.DataFrame(rows[1:], columns=[name.strip() for name in rows[0]])
    selected = raw[(raw["성별"] == "계") & raw["연령별"].map(is_five_year_label) & (raw["자치구별"] != "합계")]
    long = selected.melt(id_vars=["자치구별", "연령별"], value_vars=[f"{y} 년" for y in years],
                         var_name="연도", value_name="인구")
    return pd.DataFrame({
        "시군구": long["자치구별"].str.strip(),
        "연령구간": long["연령별"].map(normalize_age_label),
        "연도": long["연도"].str.replace(" 년", "", regex=False).astype(int),
        "인구": pd.to_numeric(long["인구"], errors="coerce"),
    })


def five_year_population_from_kosis_excel(path, province, years):
    """예전에 KOSIS 사이트에서 내려받은 엑셀(병합 셀) → 같은 모양의 표."""
    raw = pd.read_excel(path, sheet_name=0, header=0)
    raw[["시군구별", "성별"]] = raw[["시군구별", "성별"]].ffill()
    selected = raw[(raw["성별"] == "계") & (raw["연령별(2)"] == "소계")
                   & raw["연령별(1)"].map(is_five_year_label) & (raw["시군구별"] != province)]
    long = selected.melt(id_vars=["시군구별", "연령별(1)"], value_vars=years, var_name="연도", value_name="인구")
    return pd.DataFrame({
        "시군구": long["시군구별"].str.strip(),
        "연령구간": long["연령별(1)"].map(normalize_age_label),
        "연도": long["연도"].astype(int),
        "인구": pd.to_numeric(long["인구"], errors="coerce"),
    })


def compare_population(api_table, file_table):
    """두 표를 시군구 × 연령구간 × 연도로 맞춰 봅니다.

    Returns:
        (요약 dict, 다른 칸 DataFrame)
    """
    keys = ["시군구", "연령구간", "연도"]
    merged = api_table.merge(file_table, on=keys, how="outer", suffixes=("_API", "_파일"), indicator=True)
    both = merged[merged["_merge"] == "both"]
    different = both[(both["인구_API"] - both["인구_파일"]).abs() > 0.5]
    summary = {
        "비교한 칸": len(both),
        "다른 칸": len(different),
        "API에만": int((merged["_merge"] == "left_only").sum()),
        "파일에만": int((merged["_merge"] == "right_only").sum()),
    }
    summary["결과"] = "일치" if summary["다른 칸"] == summary["API에만"] == summary["파일에만"] == 0 else "불일치"
    return summary, different[keys + ["인구_API", "인구_파일"]]


def read_landing_rows(kosis_dir, table, years):
    """저장해 둔 연도별 JSON을 읽어 응답 행을 모두 합칩니다."""
    rows = []
    for year in years:
        path = landing_path(kosis_dir, table, year)
        if not path.exists():
            raise FileNotFoundError(f"{path}가 없습니다. 먼저 'python -m future_stress.kosis collect'로 받아 주세요.")
        rows += json.loads(path.read_text(encoding="utf-8"))["rows"]
    return rows


def compare_with_files(kosis_dir=None, raw_dir=None, years=None):
    """API로 받은 서울 · 경기 장래인구가 예전에 내려받은 파일과 같은지 확인합니다.

    같다면 파일 대신 API를 원본으로 써도 분석 결과가 바뀌지 않는다는 뜻입니다.
    """
    kosis_dir = Path(kosis_dir or config.KOSIS_RAW_DIR)
    raw_dir = Path(raw_dir or config.RAW_DATA_DIR)
    years = years or POPULATION_YEARS
    rows = []
    for table in FUTURE_POPULATION_TABLES.values():
        api_table = five_year_population_from_api(read_landing_rows(kosis_dir, table, years), table.province)
        file_path = raw_dir / table.file_name
        if file_path.suffix == ".csv":
            file_table = five_year_population_from_seoul_file(file_path, years)
        else:
            file_table = five_year_population_from_kosis_excel(file_path, table.province, years)
        summary, _ = compare_population(api_table, file_table)
        rows.append({"지역": table.province, "통계표": table.tbl_id, **summary})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="KOSIS 장래인구 수집기")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="서울 · 경기 장래인구를 API로 받아 저장")
    collect.add_argument("--output-dir", default=config.KOSIS_RAW_DIR, help="저장 폴더 (기본: data/raw/kosis)")
    collect.add_argument("--env-file", default=None,
                         help="KOSIS_API_KEY가 든 .env 파일 (기본: 이 저장소의 .env). 다른 프로젝트와 키를 함께 쓸 때 사용")
    compare = commands.add_parser("compare", help="받은 값과 예전에 내려받은 파일 값 비교")
    compare.add_argument("--kosis-dir", default=config.KOSIS_RAW_DIR)
    compare.add_argument("--raw-dir", default=config.RAW_DATA_DIR)
    arguments = parser.parse_args()

    try:
        if arguments.command == "collect":
            client = KosisClient.from_environment(arguments.env_file)
            report = collect_future_population(client, arguments.output_dir)
            print(report.drop(columns=["sha256", "collected_at"]).to_string(index=False))
        else:
            print(compare_with_files(arguments.kosis_dir, arguments.raw_dir).to_string(index=False))
    except (ValueError, FileNotFoundError, KosisApiError) as error:
        # 인증키 없음 · 받은 파일 없음 · KOSIS 오류는 사용자가 고칠 수 있는 문제라, 긴 오류 대신 안내만 보여 줍니다.
        raise SystemExit(f"[중단] {error}")


if __name__ == "__main__":
    main()
