{#
  스키마 이름을 정하는 규칙 (dbt 기본 규칙을 바꿈)

  dbt는 기본으로 '접속 스키마_사용자 스키마'(예: public_silver)를 만듭니다.
  이 프로젝트는 층 이름이 곧 스키마 이름이어야 읽기 쉬워서, 원본은 silver · ref 그대로,
  합성 데이터(target: synthetic)는 synthetic_silver · synthetic_ref로 만들어 원본 결과와 섞이지 않게 합니다.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name == 'synthetic' -%}
        synthetic_{{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
