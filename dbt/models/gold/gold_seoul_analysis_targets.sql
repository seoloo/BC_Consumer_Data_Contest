{#
  [Gold · STEP 2 · 3] 발표 기준 서울 분석 대상 · select_analysis_targets(서울, 전국 상위 25%)

  발표자료의 '서울 성장 14건 vs 비성장 100건'은 지역 안이 아니라 '전국' 상위 25%를 기준으로 했습니다
  (지역별 4유형은 지역 안 기준 · gold_market_type). 두 기준을 섞지 않도록 표를 따로 둡니다.
  통계 검정(Fisher · Mann-Whitney)은 SQL에 없어서 파이썬이 이 대상으로 계산합니다.
#}
{% set top_percent = var('size_top_percent') %}

with national_cutoff as (
    select percentile_cont({{ 1 - top_percent / 100 }}) within group (order by industry_total_amount) as size_cutoff
    from {{ ref('gold_region_industry_profile') }}
)

select seoul.*, national_cutoff.size_cutoff,
       coalesce(seoul.change_first_to_last_month > 0
                and seoul.avg_monthly_change > 0
                and seoul.rising_months >= {{ var('min_rising_months') }}, false) as is_growing
from {{ ref('gold_future_stress') }} as seoul
cross join national_cutoff
where seoul.province = '서울특별시'
  and seoul.is_complete_6_months
  and seoul.industry_total_amount >= national_cutoff.size_cutoff
