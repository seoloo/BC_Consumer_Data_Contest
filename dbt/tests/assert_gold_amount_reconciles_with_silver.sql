{#
  대사: 집계 전후 금액이 같은가 (파이썬 대사 5 · 6번)
    5. 전국 소비구조 금액 합계 = Silver 결제 금액 합계
    6. 경기 시 단위 소비구조 금액 합계 = Silver 경기 결제 금액 합계 (일반구를 시로 합쳐도 금액이 새지 않았나)
#}
with totals as (
    select
        (select sum(amount) from {{ ref('silver_card_spending') }}) as silver_amount,
        (select sum(amount) from {{ ref('gold_age_spending_structure') }}) as national_amount,
        (select sum(amount) from {{ ref('silver_card_spending') }} where province = '경기도') as silver_gyeonggi_amount,
        (select sum(amount) from {{ ref('gold_gyeonggi_city_age_spending_structure') }}) as gyeonggi_city_amount
)

select *
from totals
where silver_amount <> national_amount
   or silver_gyeonggi_amount <> gyeonggi_city_amount
