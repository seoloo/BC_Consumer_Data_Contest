# 흐름도 시리즈

주제별로 나눈 흐름도입니다. `docs/diagrams/*.html`을 고친 뒤 `python docs\diagrams\render.py`로 다시 그립니다.
'나눠 보기'는 게시용으로 2 ~ 4장씩 나눈 그림이고(`parts/`), 전체 한 장은 보관 · 전체 보기용입니다.

| # | 흐름도 (전체 한 장) | 나눠 보기 | 내용 |
|---|---|---|---|
| 00 | [목표 · 기술 선택](00_goal_and_stack.png) | [1](parts/00_goal_and_stack_1.png) · [2](parts/00_goal_and_stack_2.png) · [3](parts/00_goal_and_stack_3.png) · [4](parts/00_goal_and_stack_4.png) | 최종 목적, 기술 스택과 선택 이유, 쓰지 않는 기술 |
| 01 | [한눈에 보기](01_overview.png) | [1](parts/01_overview_1.png) · [2](parts/01_overview_2.png) | 문제의식, 핵심 결과, 4유형 |
| 02 | [데이터](02_data.png) | [1](parts/02_data_1.png) · [2](parts/02_data_2.png) · [3](parts/02_data_3.png) | 원본 8종의 까다로운 점과 처리 함수, 표준화 기준표 |
| 03 | [분석 파이프라인](03_pipeline.png) | [1](parts/03_pipeline_1.png) · [2](parts/03_pipeline_2.png) · [3](parts/03_pipeline_3.png) | STEP 1~5 상세와 서울 실제 건수 |
| 04 | [검증](04_validation.png) | [1](parts/04_validation_1.png) · [2](parts/04_validation_2.png) | 통계 검정, 규모 민감도, 외부유입 보정, 재현 검증 |
| 05 | [전략](05_strategy.png) | [1](parts/05_strategy_1.png) · [2](parts/05_strategy_2.png) · [3](parts/05_strategy_3.png) | 방어형 고객, 고객 구성 최적화, 메뉴 · 상품 전략 |
| 06 | [코드 구조](06_code_structure.png) | [1](parts/06_code_structure_1.png) · [2](parts/06_code_structure_2.png) · [3](parts/06_code_structure_3.png) | 리팩토링 결과, 모듈 지도, 테스트 |
| 07 | [메달리온 아키텍처](07_medallion.png) | [1](parts/07_medallion_1.png) · [2](parts/07_medallion_2.png) · [3](parts/07_medallion_3.png) | Bronze → Silver → Gold 계층, 계층 사이 대사 |
| 08 | [목표 아키텍처](08_target_architecture.png) | [1](parts/08_target_architecture_1.png) · [2](parts/08_target_architecture_2.png) · [3](parts/08_target_architecture_3.png) | 지금 구조: 전체 흐름, 파이썬 함수 ↔ dbt 모델, Airflow 단계, 자동으로 확인하는 것 |
| 09 | [로드맵](09_roadmap.png) | [1](parts/09_roadmap_1.png) · [2](parts/09_roadmap_2.png) | 단계별 할 일과 완료 기준, 진행 기록 |
| 10 | [데이터 웨어하우스](10_warehouse.png) | [1](parts/10_warehouse_1.png) · [2](parts/10_warehouse_2.png) | raw · ref · silver · gold 스키마, 파이썬 결과와 비교 |

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| Phase 0 | 공모전 분석 (노트북) | 완료 |
| Phase 1 | 리팩토링: 노트북 → `src/future_stress` 모듈 + 테스트, 발표 결과 6/6 재현 ([리팩토링 노트](../refactoring_notes.md)) | 완료 |
| Phase 1.5 | 메달리온 아키텍처: Bronze → Silver → Gold, 층 사이 대사 10개 | 완료 |
| Phase 2 | 합성 데이터 생성기 · KOSIS 수집기 · SeaweedFS Bronze 저장소 · Docker Compose | 완료 |
| Phase 3 | PostgreSQL + dbt 데이터 마트 · 품질 검사 · 데이터 사전 · ERD · 출처 문서 | 완료 |
| Phase 4 | Airflow 월 배치 · Streamlit 대시보드 · [운영 매뉴얼](../operations.md) · CI 설정 · 새 달 원본 처리 | 완료 |

![전환 로드맵 1/2](parts/09_roadmap_1.png)

![전환 로드맵 2/2](parts/09_roadmap_2.png)
