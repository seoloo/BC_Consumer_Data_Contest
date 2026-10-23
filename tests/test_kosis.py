"""KOSIS 수집기 테스트.

실제 KOSIS 서버에는 요청하지 않습니다. 인증키 없이도 돌아가야 하고, 서버 상태에 따라 결과가 바뀌면 안 되기 때문입니다.
대신 KOSIS 응답 모양을 흉내 낸 가짜 세션(FakeSession)으로 재시도 · 저장 · 비교 동작을 확인합니다.
"""

import json

import pandas as pd
import pytest
import requests

from future_stress.ingest.kosis import (
    FUTURE_POPULATION_TABLES,
    KosisApiError,
    KosisClient,
    collect_future_population,
    compare_population,
    five_year_population_from_api,
    five_year_population_from_kosis_excel,
    read_api_key,
)

GYEONGGI = FUTURE_POPULATION_TABLES["gyeonggi"]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload, self.status_code, self.text = payload, status_code, json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self.payload


class FakeSession:
    """미리 정해 둔 응답(또는 예외)을 순서대로 돌려주고, 받은 요청을 기록합니다."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append(params)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def api_row(region, sex, age, year, value):
    """KOSIS 응답 한 행. 일부러 분류 순서를 연령 · 지역 · 성별로 섞어, 순서를 가정하지 않는지 확인합니다."""
    return {"ORG_ID": "101", "TBL_ID": GYEONGGI.tbl_id, "ITM_NM": "추계인구", "UNIT_NM": "명", "PRD_SE": "Y",
            "C1": age, "C1_NM": age, "C2": region, "C2_NM": region, "C3": sex, "C3_NM": sex,
            "PRD_DE": str(year), "DT": str(value)}


def make_client(responses):
    return KosisClient("test-key", retry_wait_seconds=0, session=FakeSession(responses))


def test_client_requires_api_key():
    with pytest.raises(ValueError, match="KOSIS_API_KEY"):
        KosisClient(None)


def test_api_key_is_read_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("KOSIS_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("NAVER_CLIENT_ID=x\nKOSIS_API_KEY=\"abc\"\n", encoding="utf-8")
    assert read_api_key(env_file) == "abc"

    env_file.write_text("﻿export KOSIS_API_KEY=xyz  # 메모\n", encoding="utf-8")
    assert read_api_key(env_file) == "xyz"

    env_file.write_text("KOSIS_API_KEY=\n", encoding="utf-8")
    with pytest.raises(ValueError, match="값이 비어"):
        read_api_key(env_file)


def test_request_asks_one_year_of_the_table():
    client = make_client([FakeResponse([api_row("수원시", "계", "0 - 4세", 2040, 10)])])
    client.fetch_year(GYEONGGI, 2040)
    params = client.session.requests[0]
    assert (params["orgId"], params["tblId"]) == ("101", "INH_PB0001_2022_31")
    assert params["startPrdDe"] == params["endPrdDe"] == "2040"
    assert params["apiKey"] == "test-key" and params["format"] == "json"


def test_temporary_errors_are_retried():
    """연결 끊김 · 서버 오류 다음에 성공하면 결과를 돌려줘야 합니다."""
    client = make_client([requests.ConnectionError(), FakeResponse({}, status_code=503),
                          FakeResponse([api_row("수원시", "계", "0 - 4세", 2040, 10)])])
    assert len(client.fetch_year(GYEONGGI, 2040)) == 1
    assert len(client.session.requests) == 3


def test_permanent_kosis_error_stops_without_retry():
    """인증키 오류는 다시 보내도 같으므로 한 번만 요청하고 KOSIS 메시지를 그대로 보여줘야 합니다."""
    client = make_client([FakeResponse({"err": "11", "errMsg": "인증키 기간이 만료되었습니다."})] * 3)
    with pytest.raises(KosisApiError, match="인증키 기간이 만료"):
        client.fetch_year(GYEONGGI, 2040)
    assert len(client.session.requests) == 1


def test_collect_twice_gives_same_file(tmp_path):
    """같은 응답을 순서만 바꿔 두 번 받아도 파일이 같고, 두 번째는 '변경 없음'으로 기록돼야 합니다."""
    rows = [api_row("수원시", "계", "0 - 4세", 2040, 10), api_row("화성시", "계", "0 - 4세", 2040, 20)]
    first = collect_future_population(make_client([FakeResponse(rows)]), tmp_path, [GYEONGGI], [2040])
    saved = (tmp_path / GYEONGGI.tbl_id / "2040.json").read_bytes()

    second = collect_future_population(make_client([FakeResponse(rows[::-1])]), tmp_path, [GYEONGGI], [2040])
    assert (tmp_path / GYEONGGI.tbl_id / "2040.json").read_bytes() == saved
    assert first["상태"].tolist() == ["신규"] and second["상태"].tolist() == ["변경 없음"]
    assert first["sha256"].tolist() == second["sha256"].tolist()

    log_lines = (tmp_path / "_collect_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 2                                  # 기록은 덮어쓰지 않고 쌓임
    assert "collected_at" not in saved.decode("utf-8")         # 받은 시각은 데이터 파일에 넣지 않음


def test_api_rows_keep_only_five_year_totals():
    rows = [
        api_row("경기", "계", "0 - 4세", 2040, 500),            # 시도 합계 (API는 짧은 이름) → '(시도 합계)'
        api_row("수원시", "계", "계", 2040, 999),               # 연령 합계 → 제외
        api_row("수원시", "계", "0세", 2040, 999),              # 1세 단위 → 제외
        api_row("수원시", "남자", "0 - 4세", 2040, 999),        # 남자 → 제외
        api_row("수원시", "계", "0 - 4세", 2040, 10),
        api_row("수원시", "계", "95세 이상", 2040, 3),
    ]
    table = five_year_population_from_api(rows, "경기도")
    assert table.to_dict("records") == [
        {"시군구": "(시도 합계)", "연령구간": "0-4세", "연도": 2040, "인구": 500},
        {"시군구": "수원시", "연령구간": "0-4세", "연도": 2040, "인구": 10},
        {"시군구": "수원시", "연령구간": "95세이상", "연도": 2040, "인구": 3},
    ]


def excel_as_api_rows(path):
    """합성 경기 엑셀을 KOSIS API 응답 모양으로 바꿉니다 (API와 파일이 같은 통계일 때의 모습)."""
    raw = pd.read_excel(path)
    raw[["시군구별", "성별", "연령별(1)"]] = raw[["시군구별", "성별", "연령별(1)"]].ffill()
    rows = []
    for _, row in raw.iterrows():
        age = row["연령별(1)"] if row["연령별(2)"] == "소계" else row["연령별(2)"]
        rows += [api_row(row["시군구별"], row["성별"], age, year, int(row[year])) for year in (2026, 2040)]
    return rows


def test_api_and_downloaded_file_match(synthetic_raw_dir):
    """같은 통계라면 비교 결과가 '일치', 한 칸이라도 다르면 그 칸을 찾아내야 합니다."""
    excel_path = synthetic_raw_dir / GYEONGGI.file_name
    file_table = five_year_population_from_kosis_excel(excel_path, "경기도", [2026, 2040])
    api_table = five_year_population_from_api(excel_as_api_rows(excel_path), "경기도")

    summary, _ = compare_population(api_table, file_table)
    assert summary["결과"] == "일치" and summary["비교한 칸"] == len(file_table) > 0

    api_table.loc[0, "인구"] += 1
    summary, different = compare_population(api_table, file_table)
    assert summary["결과"] == "불일치" and summary["다른 칸"] == 1 and len(different) == 1
