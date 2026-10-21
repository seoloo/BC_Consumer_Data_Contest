{#
  [Silver] BC카드 결제 · 개인 결제만, 코드 → 이름

  파이썬 card_spending.clean_card_spending()과 같은 규칙입니다.
    1. 개인 결제만: 성별 코드 1 · 2, 연령 코드 1~6. 기준표(seed)에 없는 코드(성별 3 · x, 연령 x)는 join에서 빠집니다.
    2. 코드 → 이름: 기준표 bc_gender_codes · bc_age_codes
    3. 지역명 앞뒤 공백, 업종명 안의 공백 지우기 ('편 의 점' → '편의점')
#}
with raw_payments as (
    select * from {{ source('raw', 'card_spending') }}
),

personal_payments as (
    -- inner join: 기준표에 있는 코드만 남습니다. 빠진 행 수 · 금액은 tests/assert_card_silver_reconciles_with_raw.sql이 확인
    select
        raw_payments.*,
        genders.sex,
        ages.age_group
    from raw_payments
    join {{ ref('bc_gender_codes') }} as genders on trim(raw_payments.gender_cd) = genders.gender_cd
    join {{ ref('bc_age_codes') }} as ages on trim(raw_payments.age_cd) = ages.age_cd
)

select
    strd_yymm                                          as base_month,
    trim(sido_nm)                                      as province,
    trim(ccg_nm)                                       as district,
    sex,
    age_group,
    tp_buz_no::integer                                 as industry_code,
    regexp_replace(tp_buz_nm, '\s+', '', 'g')          as industry_name,
    amt                                                as amount,
    cnt                                                as payment_count
from personal_payments
