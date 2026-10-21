{#
  [Gold · STEP 2 · 3 · 5] 지역별 분석 대상과 4유형 · validate_region() + add_market_type()

  분석 대상: 6개월 모두 결제가 있고, 업종총이용금액이 '그 지역 안' 상위 25%(75분위수) 이상
  현재 성장: 1→6월 증감률 > 0, 월평균 증감률 > 0, 오른 달 ≥ 3 을 모두 만족 · is_strictly_growing()
  4유형:      성장 + Stress 2040 < 0 → 착시성장형 / 성장 + ≥ 0 → 지속성장형
             비성장 + < 0 → 구조취약형 / 비성장 + ≥ 0 → 회복기회형      · classify_market_type()
#}
{% set top_percent = var('size_top_percent') %}

with cases as (
    select * from {{ ref('gold_future_stress') }}
),

size_cutoffs as (
    -- 75분위수: 파이썬 quantile과 같은 '선형 보간' 방식 (percentile_cont)
    select province,
           percentile_cont({{ 1 - top_percent / 100 }}) within group (order by industry_total_amount) as size_cutoff
    from cases
    group by province
),

targets as (
    select cases.*, size_cutoffs.size_cutoff,
           -- 비어 있으면(6개월 미완전) 비교가 거짓 → '성장 아님'
           coalesce(cases.change_first_to_last_month > 0
                    and cases.avg_monthly_change > 0
                    and cases.rising_months >= {{ var('min_rising_months') }}, false) as is_growing,
           coalesce(cases.stress_2040 >= 0, false) as is_stable_2040
    from cases
    join size_cutoffs using (province)
    where cases.is_complete_6_months
      and cases.industry_total_amount >= size_cutoffs.size_cutoff
)

select targets.*,
       case
           when is_growing and not is_stable_2040 then '착시성장형'
           when is_growing and is_stable_2040 then '지속성장형'
           when not is_growing and not is_stable_2040 then '구조취약형'
           else '회복기회형'
       end as market_type
from targets
