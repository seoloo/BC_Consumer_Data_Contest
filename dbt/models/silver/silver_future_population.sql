{#
  [Silver] 장래인구 · 시도 × 시군구 × 연령대, 2026년 대비 증감률

  파이썬 population.load_seoul_future_population() · load_kosis_future_population()과 같은 규칙입니다.
  원본마다 형식이 달라 고르는 조건이 다릅니다.
    서울(CSV)          남녀 합계('계'), 서울 합계 행 제외, 5세 구간 목록(seed)에 있는 표기만, 빈 값은 0
    부산 · 경기(엑셀)   남녀 합계, 시도 합계 행 제외, 연령별(2)가 '소계'인 5세 구간 행만, 연령 '계' 제외
  재현용 버릇: 서울 목록의 마지막이 원본에 없는 '90세 이상'이라 서울 90세 이상 인구는 빠집니다 (seeds.yml 참고).
  증감률 = (그 해 인구 − 2026년 인구) ÷ 2026년 인구 × 100, 소수 첫째 자리 반올림
#}
{% set base_year = var('base_year') %}
{% set years = [base_year] + var('target_years') %}

with raw_population as (
    select * from {{ source('raw', 'future_population') }}
    where year in ({{ years | join(', ') }})
),

seoul_five_year as (
    select province, region as district, age_label, year, coalesce(population, 0) as population
    from raw_population
    where province = '서울특별시'
      and sex = '계'
      and region <> '합계'
      and age_label in (select age_label from {{ ref('seoul_five_year_age_labels') }})
),

kosis_five_year as (
    select province, region as district, replace(age_label, ' ', '') as age_label, year, population
    from raw_population
    where province in ('부산광역시', '경기도')
      and sex = '계'
      and age_detail = '소계'
      and region <> province
      and replace(age_label, ' ', '') <> '계'
),

five_year as (
    select * from seoul_five_year
    union all
    select * from kosis_five_year
),

by_age_group as (
    select
        province,
        district,
        {{ age_group_from_label('age_label') }} as age_group,
        {% for year in years %}
        sum(population) filter (where year = {{ year }}) as population_{{ year }}{{ "," if not loop.last }}
        {% endfor %}
    from five_year
    group by 1, 2, 3
)

select
    province,
    district,
    age_group,
    {% for year in years %}
    population_{{ year }},
    {% endfor %}
    {% for year in var('target_years') %}
    round((population_{{ year }} - population_{{ base_year }}) * 100.0 / nullif(population_{{ base_year }}, 0), 1)
        as change_rate_{{ year }}{{ "," if not loop.last }}
    {% endfor %}
from by_age_group
