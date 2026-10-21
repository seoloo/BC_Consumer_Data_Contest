{#
  대사: raw 결제 = Silver 결제 + 개인이 아닌 결제 (행 수 · 금액 모두)

  파이썬 medallion.run_quality_checks()의 '카드 행 수 대사' · '카드 금액 대사'를 SQL 테스트로 옮긴 것입니다.
  dbt 테스트는 '문제가 되는 행'을 돌려주고, 0행이면 통과입니다.
#}
with raw_totals as (
    select
        count(*) as raw_rows,
        sum(amt) as raw_amount,
        count(*) filter (where trim(gender_cd) not in (select gender_cd from {{ ref('bc_gender_codes') }})
                            or trim(age_cd) not in (select age_cd from {{ ref('bc_age_codes') }})) as excluded_rows,
        coalesce(sum(amt) filter (where trim(gender_cd) not in (select gender_cd from {{ ref('bc_gender_codes') }})
                                     or trim(age_cd) not in (select age_cd from {{ ref('bc_age_codes') }})), 0) as excluded_amount
    from {{ source('raw', 'card_spending') }}
),

silver_totals as (
    select count(*) as silver_rows, sum(amount) as silver_amount
    from {{ ref('silver_card_spending') }}
)

select *
from raw_totals cross join silver_totals
where raw_rows <> silver_rows + excluded_rows
   or raw_amount <> silver_amount + excluded_amount
