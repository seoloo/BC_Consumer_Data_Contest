# 미래 소비기반 스트레스 테스트

[![CI](https://github.com/seoloo/BC_Consumer_Data_Contest/actions/workflows/ci.yml/badge.svg)](https://github.com/seoloo/BC_Consumer_Data_Contest/actions/workflows/ci.yml)

"지금 매출이 늘고 있는 상권은 2040년에도 버틸까?"를 BC카드 결제 데이터와 장래인구로 진단한 공모전 분석을, **매달 같은 결과가 나오는 데이터 파이프라인**으로 다시 만든 프로젝트입니다.

## 무엇을 풀었나

- **분석:** 서울 상위 25% 상권 114건 중 지금 성장하는 14건이 **모두** 2035년 인구 변화에 취약했습니다(비성장 74%, Fisher p = 0.021). 성장 지표만 보면 놓치는 위험이라 '착시성장'이라고 부르고 4가지 유형별 전략을 냈습니다. → [분석 내용](docs/analysis.md)
- **문제:** 공모전 때는 노트북 3개(셀 555개)로 분석했습니다. 원본 8종이 파일마다 형식이 달랐고, 결과표 일부는 손으로 옮겨 다시 돌렸을 때 맞는지 확신하기 어려웠습니다.
- **파이프라인:** 원본 보관 → 정제 → 분석 → 검증 → 조회를 단계로 나누고, 매 단계에서 숫자를 맞춰 보게 만들었습니다. 옮긴 뒤에도 **발표 숫자 6개 표가 그대로** 나옵니다.

## 구조

![전체 흐름](docs/diagrams/parts/08_target_architecture_1.png)

매달 도는 단계와 파이썬 함수 ↔ dbt 모델 대응은 [아키텍처 흐름도](docs/diagrams/08_target_architecture.png)에 있습니다.

## 핵심 설계

| 설계 | 왜 | 확인한 것 |
|---|---|---|
| **같은 결과를 SQL(dbt)과 파이썬으로 두 번 만들어 비교** | 규칙을 SQL로 옮기면서 결과가 바뀌지 않았다고 말하려면 직접 맞춰 봐야 함 | Silver 321,494칸 · Gold 125,807칸 차이 0. 반올림 방식 차이(PostgreSQL vs 파이썬)까지 찾아 맞춤 |
| **다시 돌려도 같은 결과 (멱등)** | 매달 돌리고 지난달을 다시 돌려도 중복이 생기면 안 됨 | 원본 지문(SHA-256)이 같으면 '변경 없음', DB 적재는 트랜잭션으로 되돌림, 같은 달 원본은 늦게 온 파일로 통째 교체 |
| **원본 없이도 전체가 돎** | 원본은 공개할 수 없음 | 원본과 형식이 같은 합성 데이터로 테스트 94개 · CI · 대시보드 캡처 |
| **조용히 틀리지 않게** | 실패보다 '성공처럼 끝나는 틀린 결과'가 더 위험 | 층 사이 대사, dbt 테스트, 화면 안 맞춰 보기, 상태 점검 명령. 새 달 원본을 처리하지 못하고 성공으로 끝나던 배치를 찾아 고침 ([기록](docs/notes/21_monthly_batch.md)) |

일부러 쓰지 않은 기술도 있습니다. 결제 데이터가 24만 행이고 월 단위로 들어와 Spark · Kafka는 쓰지 않았습니다([13 앞으로 쓸 기술](docs/notes/13_planned.md)).

## 기술

Python · pandas · SciPy / SeaweedFS (S3) · PostgreSQL · Parquet / dbt / Airflow / Streamlit / pytest · GitHub Actions / Docker Compose

## 직접 돌려 보기 (원본 없이)

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
```

```powershell
.venv\Scripts\python -m future_stress.pipeline --synthetic
```

Docker 서비스 · dbt · Airflow · 대시보드까지 돌리는 방법은 [시작하기](docs/getting_started.md)에 있습니다.

![대시보드 · 한 건 자세히 (합성 데이터)](docs/dashboard/04_detail.png)

## 더 보기

| 문서 | 내용 |
|---|---|
| [분석 내용](docs/analysis.md) | 분석 질문 · 공식 · 4유형 · 결과 · 검증 |
| [설계 기록](docs/notes/README.md) | 기술마다 왜 썼고 써 보니 무엇이 좋아졌는지, 부딪힌 문제 (21편) |
| [시작하기](docs/getting_started.md) | 설치 · 실행 · 저장소 구성 |
| [운영 매뉴얼](docs/operations.md) | 매달 할 일 · 지난달 다시 돌리기 · 실패했을 때 |
| [데이터 사전 · ERD](docs/warehouse/README.md) | DB의 표 · 열 · 계보 (자동 생성) |
| [데이터 출처](docs/data_sources.md) | 원본마다 제공처 · 기간 · 형식 |
| [흐름도](docs/diagrams/README.md) | 주제별 그림 11장과 진행 단계 |
| [리팩토링 노트](docs/refactoring_notes.md) | 노트북을 옮기며 찾은 문제 11가지 |

## 데이터 공개 범위

공모전에서 제공한 BC카드 원본과 상세 파생 데이터는 저장소에 넣지 않습니다. `results/`에는 발표자료에 이미 실은 집계 결과만 있습니다. 원본은 결제 10건 이하 칸을 빼고 제공되며, 새 원본도 이 기준을 지키는지 검사합니다.
