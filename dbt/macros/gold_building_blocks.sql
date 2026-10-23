{#
  Gold 공통 계산 · 전국(시군구 단위)과 경기(시 단위)가 같은 규칙을 쓰므로 한 곳에 둡니다.
  파이썬 card_spending.py의 같은 이름 함수와 한 줄씩 대응합니다.
#}

{# 지역 × 업종 안에서 연령대별 이용금액과 비중 · build_age_spending_structure() #}
{% macro age_spending_structure(card_relation) -%}
    with grouped as (
        select province, district, industry_code, industry_name, age_group,
               sum(amount) as amount,
               sum(payment_count) as payment_count
        from {{ card_relation }}
        group by 1, 2, 3, 4, 5
    ),

    with_total as (
        -- 업종총이용금액은 업종명 없이 (시도, 시군구, 업종코드)로 묶습니다. 파이썬과 같은 기준입니다.
        select grouped.*,
               sum(amount) over (partition by province, district, industry_code) as industry_total_amount
        from grouped
    )

    select province, district, industry_code, industry_name, age_group, amount, payment_count, industry_total_amount,
           -- 비중(%)을 소수 첫째 자리로 반올림한 값으로 Stress를 계산합니다 (공모전 결과표 재현). 파이썬과 같은 반올림.
           {{ round_half_even('amount::double precision / industry_total_amount::double precision * 100', 1) }} as amount_share
    from with_total
{%- endmacro %}


{# 지역 × 업종 한 건마다 핵심 연령대 · 연령 집중도 · 현재 성장 지표 · build_region_industry_profile() #}
{% macro region_industry_profile(card_relation, structure_relation) -%}
    {% set months = analysis_months() %}   {# 최근 6개월 · macros/analysis_window.sql #}
    with main_customer as (
        -- 비중이 가장 큰 연령대 = 핵심 고객. 비중이 같으면 파이썬 idxmax처럼 '먼저 나온 행'(업종명 · 연령대의 문자 코드 순)을 고릅니다.
        -- collate "C": 글자를 문자 코드 순서로 비교 (파이썬 문자열 정렬과 같음). 기본 정렬은 언어 규칙을 따라 다를 수 있음.
        select province, district, industry_code, industry_name,
               age_group as main_age_group, amount_share as main_age_share, industry_total_amount
        from (
            select structure.*,
                   row_number() over (
                       partition by province, district, industry_code
                       order by amount_share desc, industry_name collate "C", age_group collate "C"
                   ) as rank_in_case
            from {{ structure_relation }} as structure
        ) as ranked
        where rank_in_case = 1
    ),

    age_concentration as (
        -- HHI = Σ (비중)², 한 연령대에 몰릴수록 1에 가까움 · calculate_age_concentration()
        select province, district, industry_code, industry_name,
               sum((amount_share / 100.0::double precision) * (amount_share / 100.0::double precision)) as age_concentration
        from {{ structure_relation }}
        group by 1, 2, 3, 4
    ),

    monthly_amount as (
        select province, district, industry_code, industry_name, base_month, sum(amount)::double precision as amount
        from {{ card_relation }}
        group by 1, 2, 3, 4, 5
    ),

    by_month as (
        -- 달마다 열 하나 (m1 = 첫 달 … m6 = 마지막 달). 결제가 없는 달은 빈 값
        select province, district, industry_code, industry_name,
               count(*) as months_with_data,
               {% for month in months %}
               max(amount) filter (where base_month = {{ month }}) as m{{ loop.index }}{{ "," if not loop.last }}
               {% endfor %}
        from monthly_amount
        group by 1, 2, 3, 4
    ),

    month_over_month as (
        -- 전월 대비 증감률(%) 5개: c1 = 2월/1월 … c5 = 6월/5월
        select by_month.*,
               {% for index in range(2, months | length + 1) %}
               (m{{ index }} / m{{ index - 1 }} - 1) * 100 as c{{ index - 1 }}{{ "," if not loop.last }}
               {% endfor %}
        from by_month
    ),

    monthly_growth as (
        -- 6개월이 다 있지 않으면 성장 지표를 비워 판정에서 빠지게 합니다 · calculate_monthly_growth()
        -- 평균은 파이썬(numpy)과 같은 순서로 더합니다: ((((c1 + c2) + c3) + c4) + c5) / 5
        -- 실수 덧셈은 순서에 따라 마지막 자리가 달라질 수 있어, 반올림 경계에서 결과가 바뀌지 않게 순서를 맞춥니다.
        {% set change_sum = namespace(expression='c1') %}
        {% for index in range(2, months | length) %}
            {% set change_sum.expression = '(' ~ change_sum.expression ~ ' + c' ~ index ~ ')' %}
        {% endfor %}
        select province, district, industry_code, industry_name, months_with_data,
               months_with_data = {{ months | length }} as is_complete_6_months,
               case when months_with_data = {{ months | length }} then
                   {{ round_half_even(change_sum.expression ~ ' / ' ~ (months | length - 1), 1) }}
               end as avg_monthly_change,
               case when months_with_data = {{ months | length }} then
                   {{ round_half_even('(m' ~ (months | length) ~ ' - m1) / m1 * 100', 1) }}
               end as change_first_to_last_month,
               case when months_with_data = {{ months | length }} then
                   ({% for index in range(1, months | length) %}(c{{ index }} > 0)::int{{ " + " if not loop.last }}{% endfor %})::double precision
               end as rising_months
        from month_over_month
    )

    select main_customer.province, main_customer.district, main_customer.industry_code, main_customer.industry_name,
           main_customer.main_age_group, main_customer.main_age_share, main_customer.industry_total_amount,
           age_concentration.age_concentration,
           monthly_growth.months_with_data, monthly_growth.is_complete_6_months,
           monthly_growth.avg_monthly_change, monthly_growth.change_first_to_last_month, monthly_growth.rising_months
    from main_customer
    left join age_concentration using (province, district, industry_code, industry_name)
    left join monthly_growth using (province, district, industry_code, industry_name)
{%- endmacro %}


{# 경기 일반구 → 시 (예: '수원시 장안구' → '수원시') · regions.to_parent_city() #}
{% macro to_parent_city(district) -%}
    case
        when position(' ' in {{ district }}) > 0 and split_part({{ district }}, ' ', 1) like '%시'
            then split_part({{ district }}, ' ', 1)
        else {{ district }}
    end
{%- endmacro %}
