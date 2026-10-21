{#
  [Gold · STEP 4] 지역 × 업종 Future Stress = 연령대별 기여도의 합 · build_region_result()
  Future Stress(연도) = Σ (연령대별 이용금액 비중 × 그 연령대의 인구증감률). 음수면 현재 고객 구성이 인구 감소에 노출.
#}
with profile as (
    select * from {{ ref('gold_region_industry_profile') }}
    where province in ('서울특별시', '부산광역시')
    union all
    select * from {{ ref('gold_gyeonggi_city_region_industry_profile') }}
),

stress_by_case as (
    select province, district, industry_code, industry_name,
           {% for year in var('stress_years') %}
           -- 파이썬 groupby.sum처럼 빈 값은 건너뛰고, 모두 비면 0
           coalesce(sum(stress_{{ year }}), 0) as stress_{{ year }}{{ "," if not loop.last }}
           {% endfor %}
    from {{ ref('gold_age_stress') }}
    group by 1, 2, 3, 4
)

select profile.*,
       {% for year in var('stress_years') %}
       stress_by_case.stress_{{ year }}{{ "," if not loop.last }}
       {% endfor %}
from profile
left join stress_by_case using (province, district, industry_code, industry_name)
