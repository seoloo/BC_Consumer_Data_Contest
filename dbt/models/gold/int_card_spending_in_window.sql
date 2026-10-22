{#
  [중간 단계] 분석 기간(최근 6개월)의 결제만 · 파이썬 build_gold()의 첫 줄과 같은 거르기
  Silver에는 도착한 모든 달이 쌓이고, 소비구조 · 성장 · Stress는 이 기간의 결제로만 계산합니다.
  ephemeral: 표로 저장하지 않고, 이 모델을 쓰는 곳에 SQL로 끼워 넣습니다.
#}
{{ config(materialized='ephemeral') }}

select *
from {{ ref('silver_card_spending') }}
where base_month in ({{ analysis_months() | join(', ') }})
