# 시작하기

Windows PowerShell 기준입니다. 저장소 폴더에서 한 줄씩 실행합니다. 서비스를 띄운 뒤의 일상 운영(매달 할 일, 실패했을 때)은 [운영 매뉴얼](operations.md)에 있습니다.

## 1. 설치와 테스트

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\python -m pip install -e ".[dev,dashboard]"
```

```powershell
.venv\Scripts\python -m pytest
```

## 2. 원본 없이 합성 데이터로

원본은 공개할 수 없어서, 원본과 형식이 같은 합성 파일을 `data/synthetic/raw/`에 만들고 같은 폴더 아래에 bronze · silver · gold · output을 만듭니다. 숫자는 직접 정한 값이라 발표 결과와는 다릅니다.

```powershell
.venv\Scripts\python -m future_stress.pipeline --synthetic
```

다음 달 원본이 왔을 때를 시험하려면 합성 7월 파일을 하나 더 만든 뒤 다시 돌립니다. 분석 기간이 2 ~ 7월로 옮겨 갑니다.

```powershell
.venv\Scripts\python -m future_stress.synthetic --next-month 202607
```

## 3. 원본으로 (발표 수치와 비교)

원본을 `data/raw/`에 넣었다면 전체 분석을 실행하고 발표 수치와 비교합니다. `data/bronze` (원본 + 적재 영수증) → `data/silver` (정제 Parquet) → `data/gold` (분석 Parquet) 순서로 만들어지고, 층 사이 건수 · 금액 대사를 통과해야 `output/`에 결과 CSV가 저장됩니다.

```powershell
.venv\Scripts\python -m future_stress.pipeline --compare
```

서울 · 경기 장래인구는 KOSIS API로 직접 받을 수 있습니다. 인증키는 `.env`에 `KOSIS_API_KEY=발급받은키`로 넣습니다(`.env`는 git에 올라가지 않음). 두 번째 명령은 예전에 내려받은 파일 값과 같은지 비교합니다.

```powershell
.venv\Scripts\python -m future_stress.kosis collect
```

```powershell
.venv\Scripts\python -m future_stress.kosis compare
```

## 4. Docker 서비스까지 (객체 저장소 · PostgreSQL · dbt)

Docker Desktop이 필요합니다. 첫 줄은 처음 한 번만 실행하며, `.env`에 이 PC 전용 계정(저장소 키, DB 비밀번호)을 만듭니다(값은 화면에 출력하지 않음).

```powershell
.venv\Scripts\python -m future_stress.local_env
```

```powershell
docker compose up -d
```

`--object-store`는 Bronze를 SeaweedFS에 올리고 거기서 다시 받아 실행하고, `--warehouse`는 원본을 PostgreSQL `raw` 스키마에도 적재합니다. 원본이 없으면 `--synthetic`을 함께 붙입니다.

```powershell
.venv\Scripts\python -m future_stress.pipeline --object-store --warehouse
```

dbt로 Silver · Gold를 만들고 테스트합니다. dbt도 Docker로 돌아서 따로 설치할 것이 없습니다. 아래 두 명령은 dbt 결과가 파이썬 Silver · Gold와 같은지 한 칸씩 비교합니다.

```powershell
docker compose run --rm dbt build
```

```powershell
.venv\Scripts\python -m future_stress.warehouse compare-silver
```

```powershell
.venv\Scripts\python -m future_stress.warehouse compare-gold
```

표 · 열 설명과 계보 · ERD가 담긴 [데이터 사전](warehouse/README.md)은 DB와 dbt 결과를 읽어 자동으로 다시 만듭니다.

```powershell
.venv\Scripts\python -m future_stress.warehouse_docs
```

## 5. 매달 돌리기 (Airflow)

메모리를 많이 써서 평소에는 띄우지 않고 필요할 때만 띄웁니다(화면: http://127.0.0.1:58280).

```powershell
docker compose --profile airflow up -d
```

```powershell
docker compose exec airflow airflow dags trigger future_stress_monthly -c '{\"batch_month\":202606}'
```

## 6. 대시보드

warehouse가 떠 있고 dbt build까지 끝난 상태에서 띄웁니다(화면: http://127.0.0.1:58501).

```powershell
.venv\Scripts\streamlit run dashboard/app.py
```

## 7. 상태 점검

서비스와 데이터가 지금 정상인지 한 번에 봅니다. 실패가 있으면 종료 코드 1로 끝납니다.

```powershell
.venv\Scripts\python -m future_stress.health
```

GitHub에서는 PR과 main에 올릴 때마다 [CI](../.github/workflows/ci.yml)가 합성 데이터로 위 과정(테스트 → 파이프라인 → dbt → 파이썬 비교 → 상태 점검)을 처음부터 자동으로 돌립니다.

## 저장소 구성

```text
src/future_stress/  분석 · 파이프라인 패키지
dbt/                SQL 모델 (silver · gold), 기준표(seeds), 테스트
airflow/dags/       월 배치 DAG (일은 src/future_stress/orchestration.py)
dashboard/          조회 화면 (Streamlit, 데이터 읽기는 src/future_stress/dashboard_data.py)
docker/             Airflow 이미지 (Dockerfile)
docker-compose.yml  로컬 서비스: 객체 저장소(SeaweedFS) · PostgreSQL · dbt · Airflow
tests/              단위 테스트와 전체 실행 테스트
docs/               분석 내용, 설계 기록(notes/), 운영 매뉴얼, 데이터 출처, 데이터 사전(warehouse/), 흐름도(diagrams/)
data/               데이터 비공개 사유와 재현 안내 (실행하면 raw · bronze · silver · gold · synthetic이 생기며 모두 git 제외)
notebooks/          실행 출력과 인증정보를 제거한 원래 분석 노트북 (보존용)
results/            발표자료에 사용한 소규모 집계 결과 CSV (재현 비교 기준)
assets/             발표에 쓴 결과 이미지
scripts/            공개용 노트북 정리 스크립트
```
