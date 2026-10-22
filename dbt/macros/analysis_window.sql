{#
  분석 기간 = raw 결제의 마지막 달에서 거꾸로 6개월 (파이썬 card_spending.analysis_months와 같은 규칙)

  새 달 원본이 오면 기간이 한 달씩 옮겨 갑니다 (예: 7월이 오면 2 ~ 7월).
  손으로 기간을 정하고 싶으면 --vars "{analysis_months: [202601, ..., 202606]}" 처럼 넘깁니다.

  dbt는 SQL을 만들기 전(parse)에 한 번, 실행할 때(execute) 한 번 이 매크로를 부릅니다.
  parse 때는 DB를 읽을 수 없어서 길이만 맞는 자리표시 값을 돌려주고, 실행할 때 raw에서 마지막 달을 읽습니다.
#}
{% macro analysis_months() %}
    {% set given = var('analysis_months', none) %}
    {% if given %}
        {{ return(given) }}
    {% endif %}
    {% set length = var('analysis_length') %}
    {% if not execute %}
        {{ return(range(length) | list) }}
    {% endif %}

    {% set result = run_query("select max(strd_yymm) from " ~ source('raw', 'card_spending')) %}
    {% set end_month = result.columns[0].values()[0] | int %}
    {% set end_index = (end_month // 100) * 12 + (end_month % 100 - 1) %}
    {% set months = [] %}
    {% for index in range(end_index - length + 1, end_index + 1) %}
        {% do months.append((index // 12) * 100 + index % 12 + 1) %}
    {% endfor %}
    {{ return(months) }}
{% endmacro %}
