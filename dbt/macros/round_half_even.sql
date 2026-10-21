{#
  파이썬(pandas · numpy)과 똑같이 반올림하기

  왜 따로 만들었나요?
    - 파이썬 Series.round(1)은 numpy를 써서 '실수(float)로 계산 → ×10 → 가장 가까운 정수(정확히 .5면 짝수 쪽) → ÷10' 입니다.
      예: 12.25 → 12.2 (122.5의 짝수 쪽은 122)
    - PostgreSQL의 round(numeric, 1)은 '0에서 먼 쪽'이라 12.25 → 12.3 이 됩니다.
    - 비중 · 증감률은 반올림한 값으로 다음 계산(Stress, 성장 판정)을 하므로, 한 칸만 달라도 결과가 바뀔 수 있습니다.
  그래서 계산도 float8(double precision)로 하고, round(float8)을 씁니다.
  PostgreSQL 문서상 round(float8)의 동점 처리는 플랫폼을 따르지만 '짝수 쪽(rint)'이 일반적이고, 공식 이미지(리눅스)도 그렇습니다.
  실제로 같은지는 compare-silver · compare-gold로 확인합니다.
#}
{% macro round_half_even(expression, digits) -%}
    (round(({{ expression }})::double precision * {{ 10 ** digits }}) / {{ 10 ** digits }})
{%- endmacro %}
