{#
  여러 열을 합친 열쇠가 다른 표에 반드시 있는지 확인하는 테스트 (dbt 기본 relationships는 열 하나만 됨)

  예: 연령대별 기여도(gold_age_stress)의 '시도 · 시군구 · 업종코드 · 업종명'은 Future Stress 표에 반드시 있어야 합니다.
      없으면 기여도가 어떤 지역 × 업종에도 더해지지 않고 사라진다는 뜻입니다.
  이 테스트는 검사이면서, 데이터 사전의 ERD(표 사이 연결선)를 그리는 근거로도 씁니다 (warehouse_docs.py).
#}
{% test composite_relationships(model, columns, to) %}
    select {% for column in columns %}child.{{ column }}{{ ", " if not loop.last }}{% endfor %}
    from {{ model }} as child
    left join {{ to }} as parent
        on {% for column in columns %}child.{{ column }} = parent.{{ column }}{{ " and " if not loop.last }}{% endfor %}
    where parent.{{ columns[0] }} is null
{% endtest %}
