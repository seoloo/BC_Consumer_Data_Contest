# 작업 일지

날짜별로 무엇을 왜 했고, 숫자로 무엇을 확인했고, 무엇에 부딪혔는지 적습니다. 최신이 위입니다.
기술마다 정리한 내용은 [README 목차](README.md)의 주제 문서에 있습니다.

## 2026-10-22 — 새 달 원본 처리 (월 배치 보완)

- **찾은 문제:** 카드 원본 파일 이름과 분석 기간(1 ~ 6월)이 코드에 고정되어, 7월 원본이 와도 예전 6개월을 다시 처리하고 성공으로 끝나는 상태였음. 18번 기록의 '다음 달 원본을 처리한다'도 사실과 달라 바로잡음.
- **고친 것:** `bc_card_*.csv` 모두 합치기(같은 달은 늦게 온 파일), 분석 기간 = 마지막 달에서 6개월(파이썬 · dbt 같은 규칙), Gold `analysis_window`, raw `source_file`, 결제 10건 이하 칸 dbt 테스트, 합성 `--next-month`.
- **확인:** 원본 6/6 · dbt 69 통과 · dbt = 파이썬 일치. 합성 + 7월 원본 → 기간 202602 ~ 202607로 옮겨 감, dbt = 파이썬 일치. Airflow `dags trigger` 8단계 성공.
- **부딪힘:** `dags test`를 켜진 DAG에 쓰면 스케줄러와 같은 단계를 두 번 돌림 → `dags trigger`로 / 합성 데이터가 10건 이하 칸을 만들고 있었음 → 원본처럼 빼도록.

## 2026-10-21 — 운영 매뉴얼 · 상태 점검 (Phase 4-4)

- `health.py`: .env 계정 · 객체 저장소 · 새 원본 · raw 적재 · gold 표 · Airflow를 정상 / 경고 / 실패와 '할 일'로. 실패가 있으면 종료 코드 1. CI 마지막 단계로 `health --synthetic`.
- `docs/operations.md`: 구성 · 처음 설치 · 띄우기 · 매달 할 일 · backfill · 단계별 실패 대응 · 다시 만들기 · 점검표. 명령은 모두 실제로 돌려 봄(PowerShell 손 실행 · 한 달 backfill 포함).
- **일부러 망가뜨려 봄:** 저장소를 끄고 실행 → `upload` 실패 · 뒤 6단계 업스트림 실패 → `health`가 실패한 단계까지 보여 줌 → 저장소를 켜고 '실패한 작업만 지우기' → 6단계만 다시 돌아 성공.
- **고친 것:** 마지막 실행을 논리 날짜 순으로 고르면 손 실행(논리 날짜 없음)이 빠짐 → `run_after` 순 / 저장소가 꺼졌을 때 '새 원본 처리 전'으로 잘못 알림 → '판단하지 않음'.

## 2026-10-21 — Streamlit 대시보드 (Phase 4-3)

- `dashboard_data.py`(gold만 읽기 전용으로 읽고 고르는 함수) + `dashboard/app.py`(탭 4개: 개요 · 지역 · 업종 순위 · 4유형 지도 · 한 건 자세히). 원본 / 합성을 옆 메뉴에서 고름.
- 화면 안에서 맞춰 보기 2가지: 4유형 건수 = `gold_market_type_counts`, 연령대 기여도 합 = Future Stress. 원본 176건 · 합성 792건 모두 맞음.
- 테스트 9개(고르는 함수 5, Streamlit AppTest 3, 실제 DB 1). 실제 DB 테스트에서 쓰기 시도가 `ReadOnlySqlTransaction`으로 막히는 것까지 확인.
- **부딪힘:** Chrome `--screenshot`은 빈 화면(웹소켓으로 그리기 전에 찍음) → Playwright로 합성 데이터 화면 4장(`docs/dashboard/`).

## 2026-10-21 — Airflow 월 배치 (Phase 4-2)

- GitHub Actions를 11월부터 쓸 수 있어서, 기다리는 동안 월 배치를 먼저 함. CI PR(#2)은 이 PC 확인으로 합침.
- 이 PC의 공식 이미지(3.1.7) 위에 프로젝트 의존성 + dbt 1.9.0(별도 가상환경)을 얹은 이미지, `airflow standalone`, 기록 DB는 같은 PostgreSQL의 `airflow` 데이터베이스, 평소엔 안 띄움(`--profile airflow`).
- DAG `future_stress_monthly`: 새 원본 확인 → Bronze → 저장소 → raw → (dbt ‖ 파이썬) → 비교. 일은 `orchestration.py`가, DAG는 순서만.
- **확인:** 6월 배치 8단계 성공(67초), 다시 돌려도 '변경 없음'. backfill: 2 ~ 5월 1일 실행은 건너뜀, 7월 1일 실행(배치 202606)만 처리.
- **부딪힘 3가지:** 기록 DB가 생기기 전에 공식 이미지가 접속 확인 → `CONNECTION_CHECK_MAX_COUNT=0` / dbt 폴더 권한(root가 만든 dbt/logs) → `DBT_TARGET_PATH` · `DBT_LOG_PATH` / 배치 월이 UTC 때문에 한 달 어긋남 → 한국 시간 '지난달'로 고치고 테스트.

## 2026-10-21 — GitHub Actions CI (Phase 4-1)

- Phase 4를 CI → Airflow → 대시보드 → 운영 매뉴얼 순서로 나눔. CI가 생기므로 작업 방식을 브랜치 → PR → CI → 합치기로 다시 바꿈.
- `.github/workflows/ci.yml`: 실행마다 새 무작위 계정(`local_env`) → `docker compose up -d --wait` → pytest 전체 → 합성 데이터 파이프라인(객체 저장소 + raw + 대사) → dbt build → dbt = 파이썬 비교.
- `compare-silver` · `compare-gold`가 불일치면 실패 코드로 끝나게 바꿈. 올리기 전에 YAML 문법 오류(`{raw_schema: ...}`의 `: `)를 찾아 고침.
- PR [#2](https://github.com/seoloo/BC_Consumer_Data_Contest/pull/2)를 올렸지만 GitHub Actions를 아직 쓸 수 없어 실행이 대기 중에 머묾. **CI 첫 실행 결과는 11월에 확인.**

## 2026-10-21 — 데이터 사전 · ERD · 출처 문서 (Phase 3-4, Phase 3 완료)

- 열 설명을 dbt docs 블록(`dbt/models/docs.md`)에 모으고 `persist_docs`로 PostgreSQL COMMENT에도 저장. 여러 열 연결 테스트(`composite_relationships`) 5개 추가 → dbt 65단계 모두 통과(테스트 49개).
- `warehouse_docs.py`: DB(열 · 타입 · 설명 · 행 수)와 dbt manifest(계보 · 열쇠 · 연결)를 읽어 `docs/warehouse/README.md` 자동 생성 (표 18개, Mermaid 계보 · ERD). 테스트 수 누락(42 → 49)과 ERD 연결 기호 오류를 찾아 고침.
- `docs/data_sources.md`: 원본 8종 + API. 서울 · 경기 장래인구는 KOSIS와 값이 같아 '확인', 나머지는 '형식으로 추정' · '확인 필요'로 나눠 표시 (발표자료에도 기관 이름은 없었음).
- 흐름도 10 웨어하우스 추가. 테스트 68개.

## 2026-10-21 — dbt Gold 모델 (Phase 3-3)

- Gold 모델 9개 + 중간 단계 1개: 연령별 소비구조(전국 · 경기 시), 프로필(핵심 연령대 · HHI · 성장 지표), 연령대별 기여도, Future Stress, 4유형, 유형별 건수, 서울 발표 기준 대상. 공통 계산은 매크로로 한 번만.
- 숫자를 칸 단위로 맞추려고 두 가지를 맞춤: 반올림(파이썬 짝수 쪽 ↔ PostgreSQL `round(numeric)` 0에서 먼 쪽 → `float8` + 짝수 쪽 매크로, Silver도 바꿈), 핵심 연령대 동점 순서(`collate "C"`).
- **확인:** `dbt build` 57개 통과. `warehouse compare-gold`: **7개 표 125,805칸 모두 같음**(반올림 값은 마지막 자리까지, HHI · Stress 합계만 보정 덧셈 차이로 최대 3.6×10⁻¹⁵). **서울 114건 → 성장 14 · 비성장 100.**
- **부딪힘:** 합성 데이터에서 4유형 건수 표가 어긋남(지속성장형 0건을 파이썬은 줄을 빼고 dbt는 0으로) → 파이썬도 항상 4줄로 고침. 원본 6/6 유지.

## 2026-10-21 — dbt Silver 모델 (Phase 3-2) · 작업 방식 바꿈

- 혼자 작업하고 매번 바로 합쳐서 브랜치가 하는 일이 없었음 → 이때부터 Phase 3 끝까지 main에 바로 커밋 (12 참고).
- `docker-compose.yml`에 dbt(`ghcr.io/dbt-labs/dbt-postgres:1.9.0`, `profiles: ["tools"]`) 추가. `dbt/` 프로젝트: seed 기준표 4개, Silver 모델 2개, 테스트 25개(직접 만든 중복 · 대사 테스트 포함), 스키마 이름 규칙 매크로.
- **확인:** `dbt build` 31개 모두 통과(2.6초). `warehouse compare-silver`: **카드 318,470칸 · 장래인구 3,024칸 모두 파이썬 Silver와 같음.** 합성 데이터(`synthetic_` 스키마)도 같음.
- 반올림 방식 차이(pandas 짝수 쪽 vs PostgreSQL 0에서 먼 쪽)를 걱정했지만 증감률 1,296칸 모두 같았음 (Gold에서는 차이가 나서 맞춤).

## 2026-10-21 — PostgreSQL raw 스키마 (Phase 3-1)

- dbt는 Python 3.14 지원이 불확실해 Docker 공식 이미지로 하기로 함.
- `docker-compose.yml`에 PostgreSQL 16.4(127.0.0.1:55532) 추가, `local_env.py`로 S3 · DB 계정 생성을 한곳에. `warehouse.py`: 원본을 표기 그대로 `raw.card_spending` · `raw.future_population`에 COPY, 지문 · 행 수 · 합계가 같으면 '변경 없음', 대사가 틀리면 되돌림, `raw._load_log` 기록.
- **확인:** 원본 242,574행 · 17.22조, 장래인구 577,680행. 9초 → 두 번째 3초 '변경 없음'. **SQL만으로 개인 결제 159,235행 · 14.89조 = 파이썬 Silver와 같음.**
- **부딪힘:** 처음 실행은 `COMMENT ... IS %s` 문법 오류로 실패했지만 트랜잭션이 모두 되돌려 깨끗하게 남음 → `sql.Literal`로 수정. 되돌리기 테스트가 표를 지우기 *전*에 실패하고 있던 것을 찾아, 지운 *뒤* 실패하도록 고침.

## 2026-10-21 — KOSIS 실제 호출 확인

- 서울 · 경기 × 4개 연도, 8번 요청 모두 성공 ('ALL' 요청 그대로 됨). 서울 9,048행 · 경기 11,136행/연도.
- **부딪힘:** 첫 비교에서 다른 값은 0인데 API에만 80칸씩 있음 → 시도 합계 행 이름이 원본마다 다름(API '서울' · '경기', 파일 '합계' · '경기도'). 이름을 `(시도 합계)`로 맞춘 뒤 **서울 2,080칸 · 경기 2,560칸 모두 일치**.
- 다시 받기: 8개 모두 '변경 없음'.

## 2026-10-21 — Bronze를 객체 저장소(SeaweedFS)로 · 기록 방식 맞추기

- 계획은 MinIO였지만 `minio/minio` 이미지 조회가 '접근 거부'. 무료판 이미지가 2026-09 Docker Hub에서 지워진 것을 확인 → SeaweedFS · RustFS · Garage · Chainguard MinIO를 비교해 SeaweedFS로 정함.
- `docker-compose.yml`(SeaweedFS 4.48, 127.0.0.1:59100), `object_store.py`(올리기 · 받기 · 지문 확인), `pipeline --object-store`. `.env` 읽기를 `io_utils.read_env_value()`로 합침.
- **확인:** 파일 60개(132MB) 왕복 지문 모두 같음, `--compare` 6/6. 두 번째 실행은 60개 '변경 없음'.
- **부딪힘:** 합성 데이터 실행이 같은 버킷의 원본 61개를 덮어쓴 것을 '변경 61'로 발견 → 합성은 `bronze-synthetic` 버킷으로 분리.
- 기록 방식을 다른 저장소(`Market_Data_Platform`)에서 쓰던 형식에 맞춤: [용어 사전](glossary.md), [01의 패턴 표](01_code_structure.md), 이 작업 일지, 주제별 '결정 기록'. [14 객체 저장소](14_object_storage.md) 새로 씀.

## 2026-10-21 — 기술 · 설계 기록 시작

- 왜 이 기술을 썼고 써 보니 무엇이 좋아졌는지 설명할 수 있게, 주제별 기록 `docs/notes/` 01 ~ 13을 씀.
- 쓰면서 코드와 다른 설명 2개를 찾아 고침: 재시도 대기는 '2 → 4 → 8초'가 아니라 최대 3번 시도라 '2 → 4초', 품질 검사 7 ~ 9번은 '멈춤'이 아니라 '경고'.

## 2026-10-21 — KOSIS 장래인구 수집기

- KOSIS에서 통계표 ID를 직접 찾음: 서울 `INH_PB0001_2022_11`, 경기 `INH_PB0001_2022_31`. 부산 구군별(2015 ~ 2040)은 KOSIS에 없어 파일 유지.
- `kosis.py`: 연도별 요청, 일시 오류만 재시도, 응답 정렬 저장(두 번 받아도 같은 파일), `_collect_log.jsonl` 기록, 파일과 한 칸씩 비교(`compare`). 오류 메시지에 인증키가 섞이지 않게 처리.
- 인증키는 코드 · 저장소에 두지 않고 `.env`에서만 읽음. 실제 호출 확인은 키를 넣은 뒤로 미룸.

## 2026-10-21 — 합성 원본 데이터 생성기 (Phase 2-1)

- `synthetic.py`: 원본 8종과 형식이 같은 합성 파일. 성별 코드 3 · x, 업종명 공백, 병합 셀, 깨진 형식, `연천시` 오타까지 재현. 숫자는 직접 정한 값.
- **확인:** 합성 데이터로 대사 10개 통과(179,702 − 66,206 = 113,496행).
- **부딪힘:** 같은 시드인데 엑셀 해시가 달라서 확인해 보니 xlsx 안의 저장 시각 때문 → 시각 고정으로 해시까지 같게.

## 2026-10-21 — 메달리온 아키텍처 · 흐름도 정리

- `medallion.py`: Bronze(원본 + 영수증) · Silver(Parquet 6개) · Gold(Parquet 16개), 층 사이 대사 10개. 원본 242,574 − 83,339 = 159,235행, 금액 17.22조 − 2.33조 = 14.89조. 발표 결과 6/6 그대로.
- 흐름도가 길어 README에서 잘 안 보여서 `render.py`에 `data-part` 나눠 보기 추가. 흐름도 문구는 발표자료처럼 존댓말로.

## 2026-10-20 — 리팩토링 (Phase 1)

- 노트북 코드는 직접 설명하기 어려워서, 새 기능보다 리팩토링을 먼저 함. 이름만 봐도 역할을 알 수 있게 바꾸고, 함수마다 쓰는 이유를 주석으로 남김.
- 노트북 3개(셀 555개) → `src/future_stress/` 모듈, 테스트. 원본으로 발표 결과 6/6 재현.
- 정리하다 찾은 문제 11가지(손으로 입력한 결과표, 서울 90세 이상 누락, SLSQP 결과 버림 등) → [리팩토링 노트](../refactoring_notes.md).
