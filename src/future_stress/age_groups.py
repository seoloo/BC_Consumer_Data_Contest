"""연령 표기를 6개 연령대로 통일하는 모듈.

왜 필요한가요?
    데이터마다 연령 표기가 전부 달랐습니다.

        BC카드          AGE_CD 1~6 (코드)
        서울 장래인구    "0~4세", "90세 이상"
        부산·경기 장래인구 "0-4세", "100세이상"
        주민등록인구     "계_0~9세" (10세 단위)
        생활인구         "20대미만", "60대", "70대이상"

    원래 노트북에는 지역마다 비슷한 변환 함수(busan_age_group, gyeonggi_age_group)와
    매핑 딕셔너리가 복사되어 있었습니다. 기준이 한 곳만 바뀌어도 연령대가 어긋나
    merge 결과가 비는 문제가 실제로 있었습니다(예: '20대미만' vs '20대이하').
    이 모듈 하나를 "연령 기준표"로 삼아 모든 데이터가 같은 이름을 쓰게 합니다.
"""

import re

import pandas as pd

# 분석에서 사용하는 6개 연령대. 그래프·표에서 이 순서대로 보여줍니다.
AGE_GROUP_ORDER = ["20대이하", "20대", "30대", "40대", "50대", "60대이상"]

# 20대 이상 연령대만. 경기 유동인구는 10세 미만 데이터가 없어서
# 비교할 때 20대이하를 빼고 이 5개만 사용합니다.
ADULT_AGE_GROUPS = AGE_GROUP_ORDER[1:]

# BC카드 AGE_CD 코드 → 연령대
BC_AGE_CODE_TO_GROUP = {
    "1": "20대이하",
    "2": "20대",
    "3": "30대",
    "4": "40대",
    "5": "50대",
    "6": "60대이상",
}

# BC카드 GENDER_CD 코드 → 성별. 원본의 '3', 'x'처럼 남녀를 알 수 없는 코드는 분석에서 제외합니다.
BC_GENDER_CODE_TO_NAME = {"1": "남성", "2": "여성"}

# 다른 데이터에서 같은 뜻을 다르게 쓴 연령대 이름 → 표준 이름
AGE_GROUP_ALIASES = {
    "20대미만": "20대이하",
    "60대": "60대이상",
    "70대이상": "60대이상",
}


def age_group_from_start_age(start_age):
    """구간의 시작 나이로 연령대를 정합니다.

    예: 0~19세 → 20대이하, 25세 → 20대, 63세 → 60대이상
    """
    if start_age < 20:
        return "20대이하"
    if start_age >= 60:
        return "60대이상"
    # 20~59세는 10의 자리로 연령대가 정해집니다 (예: 47 → 40대).
    return f"{(start_age // 10) * 10}대"


def age_group_from_label(age_label):
    """'0~4세', '0-4세', '90세 이상', '100세이상' 같은 문자열을 연령대로 바꿉니다.

    왜 시작 나이만 보나요?
        5세 · 10세 구간은 모두 한 연령대 안에 완전히 들어가므로(예: 45~49세는 40대),
        구간의 시작 나이만 알면 연령대가 정해집니다.
        '이상'으로 끝나는 마지막 구간(90세 이상, 100세 이상)은 항상 60대이상입니다.
    """
    text = str(age_label).replace(" ", "")
    if "이상" in text:
        return "60대이상"
    numbers = re.findall(r"\d+", text)
    if not numbers:
        # '계', '소계'처럼 연령 구간이 아닌 행은 None으로 돌려 호출한 쪽에서 버리게 합니다.
        return None
    return age_group_from_start_age(int(numbers[0]))


def standardize_age_group_name(series):
    """'20대미만' → '20대이하'처럼 같은 뜻의 다른 이름을 표준 이름으로 맞춥니다."""
    return series.replace(AGE_GROUP_ALIASES)


def sort_by_age_group(dataframe, column="연령대"):
    """연령대 열을 20대이하 → 60대이상 순서로 정렬합니다.

    그냥 문자열로 정렬하면 '20대' < '20대이하' < '30대' ... 순서가 되어
    그래프의 막대 순서가 어긋나기 때문에, 순서가 있는 범주형으로 바꿔 정렬합니다.
    """
    result = dataframe.copy()
    result[column] = pd.Categorical(result[column], categories=AGE_GROUP_ORDER, ordered=True)
    return result.sort_values(column).reset_index(drop=True)
