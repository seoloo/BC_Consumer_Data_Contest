"""미래 소비기반 스트레스 테스트 패키지.

노트북 3개(01_population, 02_naver_api, 03_bc_data)에 흩어져 있던 분석 로직을
역할별 모듈로 나눈 패키지입니다. 실행 순서대로 보면 아래와 같습니다.

    config          경로 · 분석 기간 · 판정 기준값 같은 설정을 한 곳에 모음
    io_utils        CSV 인코딩(utf-8-sig / cp949) 차이를 흡수하는 읽기 · 저장 함수
    age_groups      서로 다른 연령 표기(0~4세, 0-4세, AGE_CD 등)를 6개 연령대로 통일
    regions         지역명 표준화(경기 일반구 → 시, 서울 자치구 코드 → 이름)
    card_spending   STEP 1~3  BC카드 결제 정제, 연령별 소비구조, 현재 성장 지표
    population      장래인구 · 주민등록인구 · 생활/유동인구 읽기
    stress          STEP 4    Future Stress 계산
    diagnosis       STEP 2~5  분석 대상 선정, 현재 성장 판정, 4유형 분류
    validation      검증 · 성장군과 비성장군 비교, 통계 검정, 규모 기준 민감도
    robustness      검증 · 생활/유동인구로 보정해도 결과가 유지되는지 확인
    strategy        전략 · 방어형 고객 찾기, 고객 구성 재조정 최적화
    naver_datalab   전략 · NAVER 검색/쇼핑 관심도 수집과 메뉴 유형 분류
    pipeline        위 단계를 순서대로 실행하고 결과 CSV를 저장
"""
