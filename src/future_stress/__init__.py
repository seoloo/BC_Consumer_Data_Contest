"""미래 소비기반 스트레스 테스트 패키지.

공모전 노트북 3개(contest/notebooks/)에 흩어져 있던 분석 로직을 옮기고, 그 위에 보관 · 적재 · 운영을 붙인 패키지입니다.
역할별로 폴더를 나눴고, 맨 위에는 전체 흐름과 모두가 쓰는 도구만 둡니다.

맨 위
    config          경로 · 분석 기간 · 판정 기준값 같은 설정을 한 곳에 모음
    io_utils        CSV 인코딩(utf-8-sig / cp949) 차이 흡수, Parquet 저장, .env 읽기
    medallion       Bronze → Silver → Gold 층 만들기와 층 사이 대사
    pipeline        위 층을 순서대로 실행하고 결과 CSV를 저장 (python -m future_stress.pipeline)

analysis/  분석 규칙 (표를 받아 표를 돌려줌, 어디에 저장하는지는 모름)
    age_groups      서로 다른 연령 표기(0~4세, 0-4세, AGE_CD 등)를 6개 연령대로 통일
    regions         지역명 표준화(경기 일반구 → 시, 서울 자치구 코드 → 이름)
    card_spending   STEP 1~3  BC카드 결제 정제, 연령별 소비구조, 현재 성장 지표, 분석 기간
    population      장래인구 · 주민등록인구 · 생활/유동인구 읽기
    stress          STEP 4    Future Stress 계산
    diagnosis       STEP 2~5  분석 대상 선정, 현재 성장 판정, 4유형 분류
    validation      검증 · 성장군과 비성장군 비교, 통계 검정, 규모 기준 민감도
    robustness      검증 · 생활/유동인구로 보정해도 결과가 유지되는지 확인
    strategy        전략 · 방어형 고객 찾기, 고객 구성 재조정 최적화
    naver_datalab   전략 · NAVER 검색/쇼핑 관심도 수집과 메뉴 유형 분류

ingest/  원본을 받거나 만듦
    kosis           KOSIS 장래인구 수집기 (재시도, 받은 응답 보관, 파일과 비교)
    synthetic       원본과 형식이 같은 합성 데이터 (원본 없이 전체를 돌리기 위해)

storage/  보관 · 적재
    object_store    Bronze를 객체 저장소(SeaweedFS)에 올리고 받아 지문 확인
    warehouse       PostgreSQL raw 적재, dbt 결과 = 파이썬 결과 비교
    warehouse_docs  DB와 dbt 결과에서 데이터 사전 · ERD 자동 생성
    local_env       이 PC 전용 서비스 계정을 .env에 만듦

ops/  운영
    orchestration   Airflow 월 배치의 단계별 작업 (DAG는 순서만, 일은 여기서)
    health          서비스와 데이터 상태를 한 번에 점검
    dashboard_data  대시보드가 gold를 읽기 전용으로 읽고 고르는 함수
"""
