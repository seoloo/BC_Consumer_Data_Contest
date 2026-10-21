{#
  여러 열을 합친 값이 겹치지 않는지 확인하는 테스트 (외부 패키지 없이 직접 만든 일반 테스트).
  dbt_utils.unique_combination_of_columns와 같은 일을 합니다. 패키지를 쓰지 않은 이유: 실행할 때마다
  인터넷에서 받아 오는 단계(dbt deps)가 생기고, 이 프로젝트에서는 이것 하나만 필요해서.
#}
{% test unique_combination(model, columns) %}
    select {{ columns | join(', ') }}, count(*) as duplicate_count
    from {{ model }}
    group by {{ columns | join(', ') }}
    having count(*) > 1
{% endtest %}
