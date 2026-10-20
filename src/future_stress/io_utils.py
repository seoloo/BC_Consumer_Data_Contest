"""파일 읽기 · 저장 도우미.

왜 필요한가요?
    공공데이터는 파일마다 인코딩이 달랐습니다. 행안부 주민등록인구는 cp949,
    서울 장래인구는 utf-8-sig였고, 노트북에서는 한 번 읽어 보고 깨지면 인코딩을
    바꿔 다시 읽는 셀이 여러 번 반복됐습니다. 그 시행착오를 함수 하나로 정리합니다.
"""

from pathlib import Path

import pandas as pd

# 시도할 인코딩 순서.
# utf-8-sig: 엑셀에서 저장한 UTF-8 (파일 맨 앞 BOM 문자를 자동으로 제거)
# cp949:     한국 공공기관 CSV에서 흔한 윈도우 한글 인코딩
CANDIDATE_ENCODINGS = ("utf-8-sig", "cp949")


def read_csv_with_encoding_fallback(path, **read_csv_options):
    """인코딩을 차례로 바꿔 가며 CSV를 읽습니다.

    Args:
        path: 읽을 CSV 경로.
        **read_csv_options: pandas.read_csv에 그대로 넘길 옵션 (예: dtype).

    Returns:
        읽은 DataFrame.

    Raises:
        UnicodeDecodeError: 후보 인코딩으로 모두 읽지 못한 경우.
    """
    last_error = None
    for encoding in CANDIDATE_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding, **read_csv_options)
        except UnicodeDecodeError as error:
            # 이 인코딩이 아니면 다음 후보로 넘어갑니다.
            last_error = error
    raise last_error


def save_csv(dataframe, path):
    """결과 CSV를 utf-8-sig로 저장합니다.

    utf-8-sig를 쓰는 이유: 엑셀에서 바로 열어도 한글이 깨지지 않기 때문입니다.
    저장할 폴더가 없으면 만들어서 "폴더가 없어 실패"하는 일을 막습니다.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def save_parquet(dataframe, path):
    """메달리온 계층(Silver · Gold)의 표를 Parquet으로 저장합니다.

    한 열에 숫자와 문자가 섞여 있으면(예: 대표 사례 표의 '전환 후'에 -14.85와 '-'가 함께 있음)
    Parquet이 열의 타입을 정하지 못해 저장에 실패합니다. 그런 열만 문자로 바꿔 저장합니다.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = dataframe.copy()
    for column in table.columns[table.dtypes == object]:
        value_types = {type(value) for value in table[column].dropna()}
        if len(value_types) > 1:
            table[column] = table[column].map(lambda value: value if pd.isna(value) else str(value))
    table.to_parquet(path, index=False)
    return path


def read_parquet(path):
    """Parquet 표를 읽습니다. (저장할 때의 열 타입이 그대로 돌아옵니다)"""
    return pd.read_parquet(path)


def to_number(series):
    """'1,234' 처럼 쉼표가 들어간 문자열을 숫자로 바꿉니다.

    행안부 인구 파일은 숫자에 천 단위 쉼표가 들어 있어 그대로 더하면
    문자열이 이어 붙습니다. 변환할 수 없는 값은 NaN으로 둡니다.
    """
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")
