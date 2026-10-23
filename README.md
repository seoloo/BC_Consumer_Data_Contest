# 미래 소비기반 스트레스 테스트

[![CI](https://github.com/seoloo/BC_Consumer_Data_Contest/actions/workflows/ci.yml/badge.svg)](https://github.com/seoloo/BC_Consumer_Data_Contest/actions/workflows/ci.yml)

"지금 매출이 늘고 있는 상권은 2040년에도 버틸까?"를 BC카드 결제 데이터와 장래인구로 진단한 공모전 분석을, **매달 같은 결과가 나오는 데이터 파이프라인**으로 다시 만든 프로젝트입니다.

## 무엇을 풀었나

- **분석:** 서울 · 부산 · 경기에서 지역별 이용금액 상위 25% 상권 176건을 '지금 성장하는가 × 2040년 인구 변화에 취약한가'로 나눴습니다. 지금 성장하는 26건 중 **17건(65.4%)이 미래에는 취약한 '착시성장형'**이었습니다. 서울은 성장군의 Stress가 비성장군보다 뚜렷하게 낮았고(2040 중앙값 -9.46 vs -5.69, Mann-Whitney U p = 0.0014), 경기는 두 집단 모두 안정이었습니다. 그래서 지금의 성장만으로는 미래 소비기반을 판단할 수 없고, 지역마다 따로 봐야 한다는 결론을 내고 4가지 유형별 전략을 제안했습니다. → [분석 내용](docs/analysis.md)
- **문제:** 공모전 때는 노트북 3개(셀 555개)로 분석했습니다. 원본 8종이 파일마다 형식이 달랐고, 결과표 일부는 손으로 옮겨 다시 돌렸을 때 맞는지 확신하기 어려웠습니다.
- **파이프라인:** 원본 보관 → 정제 → 분석 → 검증 → 조회를 단계로 나누고, 매 단계에서 숫자를 맞춰 보게 만들었습니다. 옮긴 뒤에도 **제출한 발표자료의 핵심 숫자**(176건, 4유형 17 · 9 · 92 · 58, 지역별 검정)와 공모전 때 낸 결과표 6개가 그대로 나옵니다.

![한눈에 보기 1/2](docs/diagrams/parts/01_overview_1.png)

![한눈에 보기 2/2](docs/diagrams/parts/01_overview_2.png)

## 구조

![전체 흐름](docs/diagrams/parts/08_target_architecture_1.png)

원본은 Bronze(그대로 보관) → Silver(정제) → Gold(분석) 세 층을 거치고, 층 사이마다 건수 · 금액을 맞춰 봅니다.

![메달리온 아키텍처](docs/diagrams/parts/07_medallion_1.png)

## 핵심 설계

| 설계 | 왜 | 확인한 것 |
|---|---|---|
| **같은 결과를 SQL(dbt)과 파이썬으로 두 번 만들어 비교** | 규칙을 SQL로 옮기면서 결과가 바뀌지 않았다고 말하려면 직접 맞춰 봐야 함 | Silver 321,494칸 · Gold 125,807칸 차이 0. 반올림 방식 차이(PostgreSQL vs 파이썬)까지 찾아 맞춤 |
| **다시 돌려도 같은 결과 (멱등)** | 매달 돌리고 지난달을 다시 돌려도 중복이 생기면 안 됨 | 원본 지문(SHA-256)이 같으면 '변경 없음', DB 적재는 트랜잭션으로 되돌림, 같은 달 원본은 늦게 온 파일로 통째 교체 |
| **원본 없이도 전체가 돎** | 원본은 공개할 수 없음 | 원본과 형식이 같은 합성 데이터로 테스트 94개 · CI · 대시보드 캡처 |
| **조용히 틀리지 않게** | 실패보다 '성공처럼 끝나는 틀린 결과'가 더 위험 | 층 사이 대사, dbt 테스트, 화면 안 맞춰 보기, 상태 점검 명령. 새 달 원본을 처리하지 못하고 성공으로 끝나던 배치를 찾아 고침 ([기록](docs/notes/21_monthly_batch.md)) |

일부러 쓰지 않은 기술도 있습니다. 결제 데이터가 24만 행이고 월 단위로 들어와 Spark · Kafka는 쓰지 않았습니다([13 앞으로 쓸 기술](docs/notes/13_planned.md)).

## 분석은 이렇게

다섯 단계로 대상을 고르고 판정합니다. 서울은 241건 → 6개월이 다 있는 236건 → 서울 안 상위 25% 61건 → 지금 성장 9건입니다.

![분석 파이프라인 1/3](docs/diagrams/parts/03_pipeline_1.png)

![분석 파이프라인 2/3](docs/diagrams/parts/03_pipeline_2.png)

![분석 파이프라인 3/3](docs/diagrams/parts/03_pipeline_3.png)

결과가 우연이 아닌지 통계 검정, 기준 바꿔 보기, 방문객 보정으로 확인했습니다.

![검증 1/2](docs/diagrams/parts/04_validation_1.png)

![검증 2/2](docs/diagrams/parts/04_validation_2.png)

## 데이터 마트 (PostgreSQL + dbt)

raw · ref · silver · gold 스키마로 나누고, dbt 모델 결과가 파이썬 결과와 한 칸씩 같은지 비교합니다. 표 · 열 설명은 [데이터 사전](docs/warehouse/README.md)으로 자동 생성합니다.

![데이터 웨어하우스 1/2](docs/diagrams/parts/10_warehouse_1.png)

![데이터 웨어하우스 2/2](docs/diagrams/parts/10_warehouse_2.png)

## 왜 이 기술을

Python · pandas · SciPy / SeaweedFS (S3) · PostgreSQL · Parquet / dbt / Airflow / Streamlit / pytest · GitHub Actions / Docker Compose. 기술마다 고른 이유와 일부러 쓰지 않은 기술입니다.

![목표 · 기술 선택 1/4](docs/diagrams/parts/00_goal_and_stack_1.png)

![목표 · 기술 선택 2/4](docs/diagrams/parts/00_goal_and_stack_2.png)

![목표 · 기술 선택 3/4](docs/diagrams/parts/00_goal_and_stack_3.png)

![목표 · 기술 선택 4/4](docs/diagrams/parts/00_goal_and_stack_4.png)

## 대시보드

gold 스키마만 읽기 전용으로 읽어, 지역 · 업종별 Stress와 4유형을 골라 봅니다(캡처는 합성 데이터라 숫자에 뜻이 없음).

| 지역 · 업종 순위 | 한 건 자세히 |
|---|---|
| ![순위](docs/dashboard/02_ranking.png) | ![한 건 자세히](docs/dashboard/04_detail.png) |

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

## 진행 과정

공모전 노트북(Phase 0)에서 리팩토링 · 합성 데이터 · 데이터 마트 · 자동화(Phase 1 ~ 4)까지 옮겨 온 과정입니다.

![로드맵 1/2](docs/diagrams/parts/09_roadmap_1.png)

![로드맵 2/2](docs/diagrams/parts/09_roadmap_2.png)

<details>
<summary><b>흐름도 더 보기</b> · 데이터 · 전략 · 코드 구조 · 메달리온 · 아키텍처 나머지</summary>

#### 02 데이터: 원본 8종의 까다로운 점과 처리 함수

![데이터 1/3](docs/diagrams/parts/02_data_1.png)

![데이터 2/3](docs/diagrams/parts/02_data_2.png)

![데이터 3/3](docs/diagrams/parts/02_data_3.png)

#### 05 전략: 방어형 고객, 고객 구성 최적화, 메뉴 · 상품 전략 (방어형 고객 계산은 중간 분석 14건 기준)

![전략 1/3](docs/diagrams/parts/05_strategy_1.png)

![전략 2/3](docs/diagrams/parts/05_strategy_2.png)

![전략 3/3](docs/diagrams/parts/05_strategy_3.png)

#### 06 코드 구조: Phase 1 리팩토링 때의 모듈 지도와 테스트

![코드 구조 1/3](docs/diagrams/parts/06_code_structure_1.png)

![코드 구조 2/3](docs/diagrams/parts/06_code_structure_2.png)

![코드 구조 3/3](docs/diagrams/parts/06_code_structure_3.png)

#### 07 메달리온: 층별 표와 층 사이 대사

![메달리온 2/3](docs/diagrams/parts/07_medallion_2.png)

![메달리온 3/3](docs/diagrams/parts/07_medallion_3.png)

#### 08 아키텍처: 파이썬 함수 ↔ dbt 모델, Airflow 단계, 자동으로 확인하는 것

![아키텍처 2/3](docs/diagrams/parts/08_target_architecture_2.png)

![아키텍처 3/3](docs/diagrams/parts/08_target_architecture_3.png)

</details>

## 더 보기

| 문서 | 내용 |
|---|---|
| [분석 내용](docs/analysis.md) | 분석 질문 · 공식 · 4유형 · 결과 · 검증 |
| [설계 기록](docs/notes/README.md) | 기술마다 왜 썼고 써 보니 무엇이 좋아졌는지, 부딪힌 문제 (21편) |
| [시작하기](docs/getting_started.md) | 설치 · 실행 · 저장소 구성 |
| [운영 매뉴얼](docs/operations.md) | 매달 할 일 · 지난달 다시 돌리기 · 실패했을 때 |
| [데이터 사전 · ERD](docs/warehouse/README.md) | DB의 표 · 열 · 계보 (자동 생성) |
| [데이터 출처](docs/data_sources.md) | 원본마다 제공처 · 기간 · 형식 |
| [흐름도](docs/diagrams/README.md) | 주제별 그림 11장(전체 한 장 · 나눠 보기)과 진행 단계 |
| [리팩토링 노트](docs/refactoring_notes.md) | 노트북을 옮기며 찾은 문제 11가지 |
| [최종 제출 발표자료](contest/bc_card_future_consumer_stress.pptx) | 공모전 제출본 (14장) |

## 데이터 공개 범위

공모전에서 제공한 BC카드 원본과 상세 파생 데이터는 저장소에 넣지 않습니다. `contest/results/`에는 공모전 분석 과정에서 낸 집계 결과만 있습니다(외부유입 검증 · 4유형 전략은 제출 발표자료에 실린 표이고, 나머지는 서울 전국 기준 중간 분석). 원본은 결제 10건 이하 칸을 빼고 제공되며, 새 원본도 이 기준을 지키는지 검사합니다.
