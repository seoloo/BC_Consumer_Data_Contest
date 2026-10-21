{#
  [중간 단계] 경기 결제의 일반구를 시로 바꿈 (예: 수원시 장안구 → 수원시) · merge_gyeonggi_districts_into_cities()
  경기 장래인구 · 유동인구가 시 단위라서 결제도 같은 단위로 맞춥니다.
  ephemeral: 표로 저장하지 않고, 이 모델을 쓰는 곳에 SQL로 끼워 넣습니다 (파이썬도 저장하지 않는 중간 결과).
#}
{{ config(materialized='ephemeral') }}

select base_month, province, {{ to_parent_city('district') }} as district,
       sex, age_group, industry_code, industry_name, amount, payment_count
from {{ ref('silver_card_spending') }}
where province = '경기도'
