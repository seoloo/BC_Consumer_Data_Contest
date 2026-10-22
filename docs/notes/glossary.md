# 용어 사전

모르는 말이 나오면 여기서 찾습니다. '어디서'는 그 말이 실제로 쓰인 코드나 문서입니다.

## 데이터 구조 · 저장

| 말 | 뜻 (쉬운 말) | 어디서 |
|---|---|---|
| **메달리온 아키텍처** | 데이터를 다듬어진 정도에 따라 Bronze · Silver · Gold 세 층으로 나눠 저장하는 방식. 각 층은 바로 앞 층만 읽는다. | `medallion.py`, [03](03_medallion.md) |
| **Bronze** | 받은 원본을 손대지 않고 그대로 둔 층. 무엇을 받았는지의 기록. | `data/bronze/`, 버킷 `bronze` |
| **Silver** | 이름 · 코드 · 타입만 표준으로 맞춘 층. 아직 합치거나 비율을 내지 않음. | `data/silver/*.parquet` |
| **Gold** | 분석 결과 층. 합계 · 비율 · 판정이 들어감. | `data/gold/*.parquet` |
| **영수증 (manifest)** | Bronze에 무엇을 언제 넣었는지 적은 파일. 파일마다 경로 · 크기 · 지문 · 행 수 · 상태. | `_manifest.json` |
| **Parquet** | 열 단위로 압축해 저장하는 파일 형식. 열 타입이 같이 저장돼 다시 읽어도 바뀌지 않음. | `io_utils.save_parquet()`, [06](06_parquet.md) |
| **객체 저장소** | 파일(객체)을 버킷에 넣고 HTTP API로 올리고 받는 저장소. 여러 서비스가 함께 쓸 수 있음. | [14](14_object_storage.md) |
| **S3 / S3 API** | 아마존의 객체 저장소 서비스와 그 사용 방식. 다른 저장소들도 이 방식을 따라 해서 사실상 표준이 됨. | `object_store.py` (boto3) |
| **SeaweedFS** | S3 API를 지원하는 오픈소스 저장소. Docker로 이 PC에 띄움. | `docker-compose.yml` |
| **버킷 (bucket)** | 객체 저장소의 가장 큰 보관함. 폴더 묶음 하나라고 보면 됨. | `bronze`, `bronze-synthetic` |
| **키 (key) · 객체 (object)** | 버킷 안 파일의 전체 경로 · 그 파일. 진짜 폴더가 있는 게 아니라 '/'가 든 이름일 뿐. | `batch_month=202606/card_spending/...` |
| **파티션 (`이름=값` 폴더)** | 데이터를 기준(여기서는 배치 월)으로 나눈 폴더. 그 부분만 다시 처리할 수 있음. | `batch_month=202606/` |
| **데이터 웨어하우스** | 분석용 데이터를 모아 두고 SQL로 꺼내 쓰는 데이터베이스. 여기서는 PostgreSQL. | [15](15_postgresql.md) |
| **스키마 (schema)** | 데이터베이스 안의 표 묶음(폴더 같은 것). 층마다 하나: `raw` · `silver` · `gold`. | `raw.card_spending` |
| **raw 스키마** | 원본을 표기 그대로 넣은 DB의 첫 층. 거르기 · 바꾸기는 하지 않음 (Bronze와 같은 생각). | `warehouse.py` |
| **트랜잭션 · 커밋 · 롤백** | 여러 작업을 '모두 되거나 모두 안 되거나'로 묶는 단위 · 다 됐으니 확정 · 실패했으니 전부 되돌리기. | `Warehouse.load()` |
| **COPY** | PostgreSQL에 많은 행을 한 번에 넣는 명령. 한 행씩 INSERT보다 훨씬 빠름. | `Warehouse._copy()` |
| **객체 메타데이터** | 객체에 붙여 두는 작은 꼬리표. 여기서는 SHA-256 지문을 적어 둠. | `x-amz-meta-sha256` |

## 품질 · 신뢰

| 말 | 뜻 (쉬운 말) | 어디서 |
|---|---|---|
| **대사 (reconciliation)** | 두 곳의 숫자가 설명 가능한 차이만큼만 다른지 맞춰 보는 것. 예: 원본 행 = Silver 행 + 뺀 행. | `run_quality_checks()`, [04](04_data_quality.md) |
| **허용값 검사** | 값이 정해 둔 목록(6개 연령대 등) 안에만 있는지 확인. | 연령대 허용값 검사 |
| **멱등성** | 같은 작업을 여러 번 해도 한 번 한 것과 결과가 같은 성질. | Bronze 적재, 업로드, KOSIS 저장, [05](05_idempotency.md) |
| **재현성** | 다른 날 · 다른 PC에서 돌려도 같은 결과가 나오는 성질. | 시드 고정, 버전 고정 |
| **지문 (SHA-256)** | 파일 내용으로 계산한 64자리 값. 한 글자만 달라도 완전히 바뀌어서 '같은 파일인가'를 판단할 때 씀. | `file_fingerprint()` |
| **시드 (seed)** | 무작위 숫자를 만드는 출발값. 같으면 같은 '무작위' 숫자가 나옴. | `synthetic.py` (`seed=42`) |
| **6개월 완전관측** | 1~6월 결제가 모두 있는 지역 × 업종. 성장 판정은 이것만 씀. | `calculate_monthly_growth()` |
| **결과 재현 확인** | 원본으로 돌린 결과를 발표자료 CSV와 한 칸씩 비교. | `pipeline --compare` |

## 수집 · 오류 처리

| 말 | 뜻 (쉬운 말) | 어디서 |
|---|---|---|
| **API** | 프로그램끼리 정해진 방식으로 데이터를 주고받는 창구. | NAVER 데이터랩, KOSIS, S3 |
| **재시도 · 지수 백오프** | 일시적인 실패면 다시 보내되, 기다리는 시간을 2초 → 4초처럼 두 배씩 늘리는 방식. | `KosisClient._get()`, [09](09_api_collection.md) |
| **HTTP 429 · 5xx** | 429 = 너무 자주 불렀다(호출 제한), 5xx = 서버 쪽 오류. 둘 다 잠시 뒤 풀릴 수 있어 다시 시도. | `RETRYABLE_STATUS_CODES` |
| **사용자 정의 예외** | 문제 종류에 이름을 붙인 오류. 이름만 봐도 무엇이 문제인지 앎. | `DataQualityError`, `KosisApiError` |
| **traceback** | 오류가 난 위치를 줄줄이 보여 주는 긴 메시지. 사용자가 고칠 수 있는 오류는 대신 한 줄 안내를 보여 줌. | `[중단] ...` 메시지 |
| **환경변수 · .env** | 코드 밖에서 넣는 설정값 · 그 값을 적어 두는 파일. 인증키를 코드에 쓰지 않으려고 씀. `.env`는 git에 올리지 않음. | `io_utils.read_env_value()`, [10](10_secrets_and_privacy.md) |

## 도구

| 말 | 뜻 (쉬운 말) | 어디서 |
|---|---|---|
| **Docker · 컨테이너** | 프로그램을 필요한 환경째 상자(컨테이너)에 넣어 어디서나 똑같이 돌리는 도구. | SeaweedFS 실행 |
| **Docker Compose** | 여러 컨테이너의 설정을 파일 하나에 적고 명령 하나로 띄우고 끄는 도구. | `docker-compose.yml` |
| **이미지 · 태그** | 컨테이너의 설계도 · 그 버전 이름. 태그를 고정해야 언제 띄워도 같은 환경. | `chrislusf/seaweedfs:4.48` |
| **볼륨** | 컨테이너를 지워도 남는 데이터 보관 공간. | `object-store-data` |
| **healthcheck** | 컨테이너가 일할 준비가 됐는지 주기적으로 확인하는 설정. 준비되면 `healthy`. | `docker-compose.yml` |
| **psycopg** | 파이썬에서 PostgreSQL에 연결하는 라이브러리. | `warehouse.py` |
| **dbt** | DB 안의 표를 SQL 파일(모델)로 바꿔 가는 도구. 모델 사이 관계를 알아서 순서대로 만들고, 테스트를 붙일 수 있음. | `dbt/`, [16](16_dbt.md) |
| **dbt 모델** | SELECT 문 하나 = 표 하나. dbt가 실행해 표로 만들어 둠. | `dbt/models/silver/*.sql` |
| **source · ref** | dbt 밖에서 들어온 표(raw) · dbt가 만든 다른 모델이나 seed. ref를 보고 만드는 순서를 정함. | `{{ source('raw', ...) }}`, `{{ ref(...) }}` |
| **seed** | 저장소의 작은 CSV를 표로 올린 것. 여기서는 코드 → 이름 기준표. | `dbt/seeds/*.csv` |
| **dbt test** | '문제가 되는 행'을 찾는 SELECT. 0행이면 통과. 기본 제공(not_null 등)과 직접 만든 것이 있음. | `schema.yml`, `dbt/tests/` |
| **lineage (계보)** | 어떤 표가 어떤 표에서 만들어졌는지의 연결. dbt가 ref로 알아냄. | `dbt docs` |
| **ephemeral** | 표로 저장하지 않고, 그 모델을 쓰는 곳에 SQL로 끼워 넣는 dbt 방식. 중간 단계에 씀. | `int_gyeonggi_city_card_spending` |
| **percentile_cont** | 정렬한 값 사이를 선형으로 이어 분위수를 구하는 SQL 함수. 파이썬 `quantile`과 같은 방식. | 상위 25% 기준 |
| **짝수 쪽 반올림 (banker's rounding)** | 정확히 .5일 때 짝수 쪽으로 반올림 (2.5 → 2, 12.25 → 12.2). 파이썬 numpy의 방식. | `round_half_even` 매크로 |
| **collate "C"** | 글자를 문자 코드 순서로 비교하라는 SQL 지정. 언어 규칙 정렬과 달리 파이썬 문자열 정렬과 같음. | 핵심 연령대 동점 처리 |
| **데이터 사전 (data dictionary)** | 표마다 무엇이 들었고 열이 무슨 뜻인지 적은 문서. 여기서는 자동으로 만듦. | `docs/warehouse/README.md` |
| **ERD** | 표와 표 사이 연결(어떤 열로 이어지나)을 그린 그림. PK = 겹치면 안 되는 열쇠, FK = 다른 표에 반드시 있어야 하는 값. | 데이터 사전 3절 |
| **docs 블록** | dbt에서 설명을 한 번만 써 두고 여러 곳에서 `{{ doc('이름') }}`으로 가져다 쓰는 방법. | `dbt/models/docs.md` |
| **persist_docs** | dbt의 표 · 열 설명을 데이터베이스 COMMENT로도 저장하는 설정. | `dbt_project.yml` |
| **manifest.json** | dbt가 실행할 때 만드는 '프로젝트 지도'. 모델 · 계보 · 테스트가 모두 들어 있음. | `dbt/target/` |
| **Mermaid** | 글로 쓰면 그림이 되는 도표 문법. GitHub가 마크다운 안에서 바로 그려 줌. | 계보 · ERD |
| **YAML 앵커 (&, *)** | YAML에서 한 번 쓴 내용에 이름(&)을 붙이고 다른 곳에서(*) 그대로 다시 쓰는 문법. | `gold/schema.yml` 프로필 열 |
| **매크로 (macro)** | SQL 안에서 되풀이해 쓰는 조각을 함수처럼 만든 것. | `dbt/macros/` |
| **boto3** | 파이썬에서 S3 API를 쓰는 표준 라이브러리. | `object_store.py` |
| **pytest · fixture** | 파이썬 테스트 도구 · 여러 테스트가 함께 쓰는 준비물(예: 합성 원본 폴더). | `tests/`, `conftest.py` |
| **가짜 객체 (fake)** | 실제 서버 대신 같은 모양으로 대답하는 테스트용 객체. 서버 없이도 테스트가 돌게 함. | `FakeS3Client`, `FakeSession` |
| **CI (지속적 통합)** | 코드를 올릴 때마다 자동으로 설치 · 테스트를 돌려 문제가 있으면 바로 알려 주는 방식. | `.github/workflows/ci.yml`, [17](17_ci.md) |
| **GitHub Actions · 워크플로** | GitHub가 제공하는 CI · 그 실행 순서를 적은 YAML 파일. | `ci.yml` |
| **러너 (runner)** | 워크플로를 실제로 돌리는 서버. 실행마다 깨끗한 새 서버를 받음. | `ubuntu-latest` |
| **PR (Pull Request)** | 브랜치의 변경을 main에 합쳐 달라는 요청. 여기서 CI 결과와 바뀐 내용을 함께 봄. | PR #2 |
| **종료 코드** | 명령이 끝날 때 남기는 숫자. 0이면 성공, 그 밖은 실패. CI는 이것으로 판단. | `compare-gold` |
| **운영 매뉴얼 (runbook)** | 띄우기 · 매달 할 일 · 실패했을 때 할 일을 순서대로 적은 문서. 명령은 실제로 돌려 본 것만. | `docs/operations.md`, [20](20_operations.md) |
| **상태 점검 (health check)** | 서비스와 데이터가 지금 정상인지 한 번에 확인하는 것. 실패가 있으면 종료 코드 1. | `python -m future_stress.health` |
| **종료 코드** | 프로그램이 끝날 때 남기는 숫자. 0이면 성공, 0이 아니면 실패. CI · 스크립트가 이 값으로 다음 단계를 정함. | `health`, `compare-gold` |
| **업스트림 실패** | 앞 단계가 실패해서 이 단계는 시작도 하지 않은 상태 (Airflow). 앞 단계를 고치면 함께 다시 돎. | Airflow 화면 |
| **Streamlit** | 파이썬 코드만으로 웹 화면(표 · 그래프 · 선택 상자)을 만드는 도구. 값을 바꿀 때마다 코드 전체를 다시 실행해 화면을 다시 그림. | `dashboard/app.py`, [19](19_dashboard.md) |
| **읽기 전용 트랜잭션** | `BEGIN READ ONLY`로 연 연결. 이 연결로는 INSERT · UPDATE · CREATE가 거절됨. | `GoldReader._query()` |
| **캐시 (cache_data)** | 한 번 읽은 결과를 잠깐 저장해 두고 다시 쓰는 것. 화면을 누를 때마다 DB를 읽지 않게. | `st.cache_data(ttl=300)` |
| **AppTest** | 브라우저 없이 Streamlit 앱을 실행해 화면 요소(탭 · 숫자 · 오류)를 확인하는 테스트 도구. | `tests/test_dashboard.py` |
| **Airflow · DAG** | 작업 흐름을 정해 진 시각에 순서대로 돌리는 도구 · 그 흐름(단계와 순서)을 적은 것. | `airflow/dags/`, [18](18_airflow.md) |
| **task (단계)** | DAG 안의 일 하나. 따로 성공 · 실패 · 재시도 · 건너뜀 상태를 가짐. | `build_bronze` 등 8개 |
| **short_circuit** | False를 돌려주면 뒤 단계를 '건너뜀'으로 두는 단계. 실패가 아님. | `has_new_batch` |
| **backfill** | 지난 기간을 골라 다시 돌리는 것. 멱등해야 안전함. | `airflow backfill create` |
| **XCom** | 단계 사이에 작은 값을 넘기는 Airflow 저장소. 큰 표는 넘기지 않음. | 단계별 요약 dict |
| **분석 기간** | 성장 · Stress를 계산하는 6개월. 결제 데이터의 마지막 달에서 거꾸로 6개월이라 새 달이 오면 옮겨 감. | Gold `analysis_window`, [21](21_monthly_batch.md) |
| **월 단위 교체** | 같은 달이 두 파일에 있으면 늦게 온 파일의 그 달만 쓰는 것. 두 번 더해지지 않고, 다시 돌려도 같음. | `load_card_files()` |
| **작은 칸 (최소 건수)** | 결제가 몇 건 안 되는 칸은 개인이 드러날 수 있어 제공하지 않는 기준. BC카드 원본은 10건 이하 칸이 없음. | dbt `assert_card_cells_meet_minimum_count` |
| **배치 월** | 한 번에 도착한 원본 묶음의 이름(BC카드 파일 이름의 끝월). DAG는 실행 시각(한국 시간)의 지난달을 처리. | `batch_month=202606` |
| **브랜치 · 병합** | 작업을 main과 떼어 따로 하는 갈래 · 다 확인한 뒤 main에 합치는 것. | `feature/*`, [12](12_docs_and_git.md) |

## 분석

| 말 | 뜻 (쉬운 말) | 어디서 |
|---|---|---|
| **Future Stress** | 지금 손님의 연령 구성이 2040년 인구 변화에 얼마나 노출됐는지. Σ(연령별 소비 비중 × 인구 증감률). 음수면 손님 연령층이 줄어드는 쪽. | `stress.py` |
| **엄격 성장** | 월평균 증감률 > 0, 1월 대비 6월 > 0, 오른 달 3번 이상을 모두 만족. | `diagnosis.is_strictly_growing()` |
| **4유형** | 지금 성장 여부 × Stress 부호로 나눈 상권 유형 (착시성장 · 지속성장 · 구조취약 · 회복기회). | `diagnosis.classify_market_type()` |
| **HHI** | 한쪽으로 얼마나 쏠렸는지 재는 지수. 비중 제곱의 합. 클수록 한 연령대에 의존. | `calculate_age_concentration()` |
| **Mann-Whitney U · Fisher · Spearman** | 두 집단 분포 비교 · 두 비율 비교 · 순위가 얼마나 같은지 보는 통계 방법. | `validation.py`, `robustness.py` |
