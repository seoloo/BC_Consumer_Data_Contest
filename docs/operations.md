# 운영 매뉴얼

이 파이프라인을 띄우고, 매달 돌리고, 멈췄을 때 다시 살리는 방법을 한곳에 모았습니다.
명령은 Windows PowerShell 기준이고 저장소 폴더에서 한 줄씩 실행합니다. 이 문서의 명령은 모두 2026-10-21에 이 PC에서 실제로 돌려 보고 적었습니다.

> **문제가 생기면 먼저 이것부터.** 무엇이 멈췄는지와 할 일을 한 번에 보여 줍니다. 실패가 있으면 종료 코드 1로 끝납니다.
>
> ```powershell
> .venv\Scripts\python -m future_stress.ops.health
> ```

## 1. 구성

| 서비스 | 하는 일 | 주소 (이 PC 안에서만) | 띄우는 방법 | 데이터가 남는 곳 |
|---|---|---|---|---|
| object-store (SeaweedFS) | Bronze 원본 보관 (`bronze` · `bronze-synthetic` 버킷, `batch_month=YYYYMM/`) | 127.0.0.1:59100 | `docker compose up -d` | 볼륨 `object-store-data` |
| warehouse (PostgreSQL 16) | raw · silver · gold 스키마, Airflow 기록 DB(`airflow`) | 127.0.0.1:55532 | `docker compose up -d` | 볼륨 `warehouse-data` |
| dbt | raw → silver → gold + 테스트 49개 | - | `docker compose run --rm dbt build` (돌고 끝남) | DB |
| airflow | 매달 1일 0시(한국 시간)에 지난달 배치 처리 | http://127.0.0.1:58280 | `docker compose --profile airflow up -d` | 볼륨 `airflow-logs` + DB `airflow` |
| 대시보드 (Streamlit) | gold를 읽기 전용으로 보여 줌 | http://127.0.0.1:58501 | `.venv\Scripts\streamlit run dashboard/app.py` | 없음 (읽기만) |

- **계정**은 `.env`에만 있습니다 (git 제외). 처음에 `local_env`가 무작위로 만들고, 화면에 출력하지 않습니다.
- **원본**은 `data/raw/`에 둡니다 (git 제외, 넣는 방법은 [data/README.md](../data/README.md)). 원본 원래 위치(저장소 밖)에도 그대로 있어야 합니다. 아래 '다시 만들기'의 출발점입니다.
- **무엇이 무엇에 기대는지**: 원본 → Bronze(로컬 · 저장소) → raw → dbt silver · gold → 대시보드. 앞이 있으면 뒤는 언제든 다시 만들 수 있습니다.

## 2. 처음 설치

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\python -m pip install -e ".[dev,dashboard]"
```

```powershell
.venv\Scripts\python -m future_stress.storage.local_env
```

```powershell
docker compose up -d
```

```powershell
docker compose ps
```

`docker compose ps`에서 object-store · warehouse가 `healthy`가 될 때까지 기다립니다. 그다음 원본을 `data/raw/`에 넣고 처음부터 끝까지 한 번 돌립니다.

```powershell
.venv\Scripts\python -m future_stress.pipeline --object-store --warehouse --compare
```

```powershell
docker compose run --rm dbt build
```

```powershell
.venv\Scripts\python -m future_stress.storage.warehouse compare-gold
```

```powershell
.venv\Scripts\python -m future_stress.ops.health
```

`--compare`는 공모전 결과표 6/6, `compare-gold`는 dbt = 파이썬 7개 표가 '일치'여야 합니다. `health`는 Airflow를 아직 안 띄웠으면 Airflow만 '경고'입니다.

## 3. 평소 띄우기 · 끄기

| 하고 싶은 일 | 명령 |
|---|---|
| 저장소 · DB 띄우기 | `docker compose up -d` |
| Airflow까지 띄우기 | `docker compose --profile airflow up -d` |
| Airflow만 끄기 (메모리 약 1GB) | `docker compose --profile airflow stop airflow` |
| 모두 끄기 (데이터는 볼륨에 남음) | `docker compose --profile airflow down` |
| 대시보드 | `.venv\Scripts\streamlit run dashboard/app.py` (끄기: 그 창에서 Ctrl+C) |

- object-store · warehouse는 `restart: unless-stopped`라 PC를 다시 켜도 Docker Desktop이 뜨면 함께 뜹니다.
- **Airflow는 자동으로 다시 뜨지 않습니다** (메모리 때문에 일부러). 꺼져 있던 동안의 1일 실행은 생기지 않고, 다시 켜면 **가장 최근 달 하나만** 자동으로 만들어집니다(`catchup=False`, 실제로 켜자마자 10월 1일 실행이 생김). 그 전 달들이 필요하면 5번 '지난달 다시 돌리기'로 돌립니다.

## 4. 매달 할 일

1. **새 원본 넣기.** BC카드 새 파일(`bc_card_<시작월>_<끝월>.csv`)을 `data/raw/`에 넣습니다. 파일 이름의 끝월이 배치 월입니다. 예전 파일은 지우지 않습니다. 모든 파일을 합쳐 읽고, 같은 달이 겹치면 늦게 온 파일을 씁니다. 분석 기간은 마지막 달에서 거꾸로 6개월로 옮겨 갑니다(대시보드 맨 위에 표시).
2. **확인.** `health`의 '새 원본'이 `경고 · 아직 처리 전`으로 바뀝니다.
3. **처리.** Airflow가 떠 있으면 다음 달 1일 0시에 지난달 배치를 처리합니다. 바로 돌리려면 손으로 실행합니다(예: 202607).

```powershell
docker compose exec airflow airflow dags trigger future_stress_monthly -c '{\"batch_month\":202607}'
```

4. **결과 확인.** Airflow 화면(http://127.0.0.1:58280)에서 8단계가 모두 성공인지 보고, `health`를 돌립니다. 대시보드는 5분마다 다시 읽고, 바로 보려면 옆 메뉴의 '새로 읽기'를 누릅니다.

배치 월에 원본이 없으면 첫 단계(`has_new_batch`)에서 나머지가 **건너뜀**으로 끝납니다. 실패가 아니라 정상입니다.

새 원본에 결제 10건 이하 칸이 있으면 `dbt_build`가 `assert_card_cells_meet_minimum_count`로 실패합니다. 원본 제공 방식이 바뀌었는지 확인한 뒤 진행합니다.

확인용으로 `airflow dags test`를 쓸 때는 DAG를 먼저 끕니다(pause). 켜져 있으면 스케줄러도 같은 단계를 함께 돌려 '실패'가 섞여 기록될 수 있습니다.

## 5. 지난달 다시 돌리기 (backfill)

규칙(dbt 모델 · 기준표)을 고쳤거나 원본을 바꿔 넣었을 때 씁니다. 모든 단계가 멱등이라(같은 입력이면 '변경 없음') 몇 번 돌려도 중복이 생기지 않습니다.

| 방법 | 명령 | 언제 |
|---|---|---|
| 한 달만, 바로 | `docker compose exec airflow airflow dags trigger future_stress_monthly -c '{\"batch_month\":202606}'` | 대부분 |
| 기간을 골라서 | `docker compose exec airflow airflow backfill create --dag-id future_stress_monthly --from-date 2026-07-01 --to-date 2026-07-01 --reprocess-behavior completed` | 여러 달을 실행 날짜 기준으로 |
| Airflow 없이 | 2번의 `pipeline` → `dbt build` → `compare-gold` 순서 | Airflow를 안 띄웠을 때 |

backfill의 날짜는 **실행 날짜**입니다. 7월 1일 실행이 6월 배치(202606)를 처리합니다. 이미 성공한 날짜를 다시 돌리려면 `--reprocess-behavior completed`가 있어야 합니다(없으면 건너뜀). 이때 새 실행이 생기지 않고, 같은 날짜의 기존 실행을 지운 뒤 다시 돕니다.

## 6. 실패했을 때

먼저 `health`로 어느 서비스 · 어느 단계인지 봅니다. Airflow 실행이 실패했다면 화면의 그 실행에서 빨간 단계를 눌러 기록(Log)을 봅니다. 기록 파일은 컨테이너 안 `/opt/airflow/logs/dag_id=future_stress_monthly/run_id=.../task_id=.../`에도 남습니다.

| 단계 | 이렇게 보이면 | 원인 | 할 일 |
|---|---|---|---|
| (모든 단계) | `.env 계정 실패` 또는 compose가 '먼저 local_env를 실행해 주세요' | `.env`에 계정 없음 | `python -m future_stress.storage.local_env` |
| `build_bronze` | `FileNotFoundError: ...에 다음 원본이 없습니다` | `data/raw/`에 원본 8종 중 일부가 없음 | 빠진 파일을 넣고 다시 실행 |
| `upload` · `download` | `EndpointConnectionError` (1분 뒤 한 번 더 시도 후 실패), health `객체 저장소 실패` | object-store가 꺼짐 | `docker compose up -d` → 아래 '그 단계부터 다시' |
| `download` | `DataQualityError: 지문이 영수증과 다릅니다` | 저장소의 파일이 올린 것과 다름 (덮어씀 · 손상) | `pipeline --object-store`로 다시 올린 뒤 다시 실행. 계속되면 원본 원래 위치와 비교 |
| `load_raw` | `DataQualityError` (행 수 · 합계 대사) | 적재 중 값이 달라짐 | **이전 표는 그대로 남아 있음**(트랜잭션 되돌림). 원본 파일을 확인한 뒤 다시 실행 |
| `load_raw` · `dbt_build` · `compare` | `OperationalError` / `connection refused` | warehouse가 꺼짐 | `docker compose up -d` |
| `dbt_build` | `dbt build 실패` + `FAIL`/`ERROR` 줄 | dbt 테스트 실패(키 중복 · 관계 · 대사) 또는 SQL 오류 | 기록에서 실패한 테스트 이름을 찾아 `docker compose run --rm dbt build --select <이름>`으로 따로 확인 |
| `python_layers` | `DataQualityError: 계층 사이 대사 실패` | 층 사이 숫자 확인 중 '실패' 항목 | 기록의 표에서 실패 항목 확인 (`data/gold/_quality_report.csv`). 경고는 멈추지 않음 |
| `compare` | `DataQualityError: dbt 결과와 파이썬 결과가 다릅니다` | dbt와 파이썬 규칙이 어긋남 | `python -m future_stress.storage.warehouse compare-gold`로 다른 표 · 칸 확인 |
| 대시보드 | 'PostgreSQL에 연결할 수 없습니다' / 'gold 표가 없습니다' | warehouse 꺼짐 / dbt build 전 | 화면에 나온 안내대로 |

**그 단계부터 다시 (실제로 해 봄: 저장소를 끄고 실행 → `upload` 실패 → 저장소를 켜고 다시)**

1. 원인을 고칩니다 (예: `docker compose up -d`).
2. Airflow 화면에서 실패한 실행 → **Dag 실행 지우기** → **실패한 작업만 지우기** → 확인.
3. 실패한 단계와 그 뒤 단계(6개)만 다시 돕니다. 앞에서 성공한 `has_new_batch` · `build_bronze`는 다시 돌지 않습니다.

화면을 쓸 수 없으면 같은 `batch_month`로 새로 실행해도 됩니다. 앞 단계는 '변경 없음'으로 빨리 지나갑니다.

## 7. 다시 만들기 (복구)

DB와 저장소의 데이터는 모두 원본에서 다시 만들 수 있습니다. 그래서 따로 백업하지 않고, **원본(`data/raw/`와 원래 위치)만 지킵니다.**

| 잃은 것 | 다시 만드는 순서 |
|---|---|
| warehouse 볼륨 (raw · silver · gold · Airflow 기록) | `docker compose up -d` → `pipeline --object-store --warehouse` → `dbt build` → `compare-gold`. Airflow 실행 기록은 되살릴 수 없음 |
| object-store 볼륨 | `docker compose up -d` → `pipeline --object-store` (로컬 Bronze에서 다시 올림, 지문 확인) |
| `data/bronze` · `silver` · `gold` 폴더 | `pipeline --object-store --warehouse` (원본에서 다시) |
| `.env` | `local_env`로 새로 만들면 비밀번호가 바뀌어 **기존 DB에 접속할 수 없음**. 볼륨까지 지우고(`docker compose --profile airflow down -v`) 처음 설치부터 다시 |

PostgreSQL은 비밀번호를 볼륨을 처음 만들 때만 정합니다. 그래서 `.env`의 비밀번호만 바꾸면 접속이 안 되고, 위 마지막 줄처럼 볼륨째 다시 만드는 쪽이 가장 단순합니다(이 PC 전용 계정이라 데이터를 다시 만드는 비용이 작음).

## 8. 가끔 하는 일

표의 `python`은 `.venv\Scripts\python`입니다.

| 일 | 언제 | 명령 |
|---|---|---|
| KOSIS 장래인구 다시 받기 | 통계청이 새 추계를 낼 때 | `python -m future_stress.ingest.kosis collect` → `python -m future_stress.ingest.kosis compare` |
| 데이터 사전 · ERD 다시 만들기 | dbt 모델 · 설명을 고친 뒤 | `docker compose run --rm dbt build` → `python -m future_stress.storage.warehouse_docs` |
| 흐름도 다시 그리기 | `docs/diagrams/*.html`을 고친 뒤 | `python docs\diagrams\render.py` |
| 대시보드 캡처 | 화면을 고친 뒤 (합성 데이터로만 찍음) | `python dashboard\capture.py` (playwright 필요) |
| 합성 데이터로 전체 확인 | 코드를 고친 뒤 (CI와 같은 순서) | [ci.yml](../.github/workflows/ci.yml)의 단계 순서대로, 마지막에 `python -m future_stress.ops.health --synthetic` |

## 9. 매달 점검표

- [ ] `health`가 실패 없이 끝남
- [ ] Airflow 마지막 실행이 성공 (원본이 없는 달은 '건너뜀'이 정상)
- [ ] 대시보드 개요의 '✓ gold_market_type_counts와 같습니다'
- [ ] 원본 원래 위치에 이번 달 파일도 복사해 둠
- [ ] 디스크 여유 (`docker system df`)
