-- [Gold] 분석 기간 한 줄 · 파이썬 Gold analysis_window. 화면 · 비교 · 대사가 같은 기간을 보게 합니다.
{% set months = analysis_months() %}

select {{ months[0] }} as start_month,
       {{ months[-1] }} as end_month,
       {{ months | length }} as month_count,
       (select count(distinct base_month) from {{ ref('int_card_spending_in_window') }}) as months_with_payments
