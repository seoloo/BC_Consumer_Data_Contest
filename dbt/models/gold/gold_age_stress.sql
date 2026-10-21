{#
  [Gold · STEP 4] 연령대별 Stress 기여도 = 이용금액 비중 × 그 연령대의 인구증감률 · add_age_stress_contributions()

  서울 · 부산은 전국 소비구조(시군구 단위), 경기는 시 단위 소비구조를 씁니다 (경기 장래인구가 시 단위).
  장래인구가 없는 연령 행은 증감률이 비어 기여도도 비고, 합칠 때 0으로 다룹니다 (매칭 누락은 테스트가 경고).
#}
with structure as (
    select * from {{ ref('gold_age_spending_structure') }}
    where province in ('서울특별시', '부산광역시')
    union all
    select * from {{ ref('gold_gyeonggi_city_age_spending_structure') }}
)

select structure.*,
       {% for year in var('target_years') %}
       population.change_rate_{{ year }},
       {% endfor %}
       {% for year in var('stress_years') %}
       -- 비중(%)을 100으로 나눠 비율로 바꾼 뒤 곱함 → Stress 단위는 인구증감률(%)과 같음
       (structure.amount_share / 100.0::double precision) * population.change_rate_{{ year }} as stress_{{ year }}{{ "," if not loop.last }}
       {% endfor %}
from structure
left join {{ ref('silver_future_population') }} as population
    on population.province = structure.province
   and population.district = structure.district
   and population.age_group = structure.age_group
