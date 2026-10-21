{#
  연령 표기(예: '0~4세', '0 - 4세', '95세 이상') → 6개 연령대

  파이썬 age_groups.age_group_from_label()과 같은 규칙입니다.
    - '이상'으로 끝나는 마지막 구간은 항상 60대이상
    - 그 밖에는 구간의 시작 나이만 봅니다 (5세 구간은 한 연령대 안에 완전히 들어가기 때문)
      20 미만 → 20대이하, 60 이상 → 60대이상, 나머지는 10의 자리 (47 → 40대)
#}
{% macro age_group_from_label(label) -%}
    case
        when {{ label }} like '%이상%' then '60대이상'
        when substring(replace({{ label }}, ' ', '') from '^[0-9]+')::int < 20 then '20대이하'
        when substring(replace({{ label }}, ' ', '') from '^[0-9]+')::int >= 60 then '60대이상'
        else (substring(replace({{ label }}, ' ', '') from '^[0-9]+')::int / 10 * 10)::text || '대'
    end
{%- endmacro %}
