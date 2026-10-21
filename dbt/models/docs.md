{# 
  열 설명 모음 (dbt docs 블록)

  같은 열(시도, 시군구, 비중 …)이 여러 표에 나와서, 설명을 여기 한 번만 쓰고 schema.yml에서 {{ doc('이름') }}으로 가져다 씁니다.
  dbt_project.yml의 persist_docs 설정으로 이 설명이 PostgreSQL에도 COMMENT로 저장되고,
  python -m future_stress.warehouse_docs 가 그 설명으로 데이터 사전(docs/warehouse/README.md)을 만듭니다.
#}

{% docs col_province %}시도 이름 (서울특별시 · 부산광역시 · 경기도 …){% enddocs %}

{% docs col_district %}시군구 이름. 서울 · 부산은 자치구, 경기는 표에 따라 일반구(예: 수원시 장안구) 또는 시(예: 수원시){% enddocs %}

{% docs col_industry_code %}BC카드 업종 코드 (예: 8001){% enddocs %}

{% docs col_industry_name %}업종 이름. 원본의 공백을 지운 값 (예: '편 의 점' → '편의점'){% enddocs %}

{% docs col_age_group %}6개 연령대 중 하나 (20대이하 · 20대 · 30대 · 40대 · 50대 · 60대이상, 기준표 ref.age_groups){% enddocs %}

{% docs col_sex %}성별 (남성 · 여성). 원본 성별 코드 1 · 2를 바꾼 값{% enddocs %}

{% docs col_base_month %}기준년월 (예: 202601){% enddocs %}

{% docs col_amount %}이용금액 (원){% enddocs %}

{% docs col_payment_count %}이용건수{% enddocs %}

{% docs col_industry_total_amount %}같은 시도 · 시군구 · 업종의 6개월 전체 연령 이용금액 합계 (원). '상위 25%' 규모 기준에 씀{% enddocs %}

{% docs col_amount_share %}이 연령대가 업종 이용금액에서 차지하는 비중 (%). 소수 첫째 자리, 파이썬과 같은 짝수 쪽 반올림. Future Stress 공식의 '연령별 이용금액 비중'{% enddocs %}

{% docs col_main_age_group %}핵심 고객 연령대 = 이용금액 비중이 가장 큰 연령대{% enddocs %}

{% docs col_main_age_share %}핵심 고객 연령대의 이용금액 비중 (%){% enddocs %}

{% docs col_age_concentration %}연령 집중도 HHI = Σ(비중)². 한 연령대에 몰릴수록 1에 가깝고, 6개에 고르게 퍼지면 1/6에 가까움{% enddocs %}

{% docs col_months_with_data %}6개월 중 결제가 있었던 달 수{% enddocs %}

{% docs col_is_complete_6_months %}6개월 모두 결제가 있었는지. 아니면 성장 지표를 비워 판정에서 뺌{% enddocs %}

{% docs col_avg_monthly_change %}월평균 증감률 (%) = 전월 대비 증감률 5개의 평균, 소수 첫째 자리. 6개월 완전일 때만{% enddocs %}

{% docs col_change_first_to_last_month %}1월 대비 6월 증감률 (%), 소수 첫째 자리. 6개월 완전일 때만{% enddocs %}

{% docs col_rising_months %}전월보다 이용금액이 늘어난 달 수 (0 ~ 5). 6개월 완전일 때만{% enddocs %}

{% docs col_change_rate %}2026년 대비 그 해의 인구 증감률 (%), 소수 첫째 자리. 양수면 늘고 음수면 줄어듦{% enddocs %}

{% docs col_population %}그 해의 장래 추계 인구 (명){% enddocs %}

{% docs col_stress %}Future Stress = Σ(연령별 이용금액 비중 × 그 연령대의 인구 증감률). 음수면 현재 고객 구성이 인구 감소에 노출(취약), 0 이상이면 안정{% enddocs %}

{% docs col_stress_contribution %}이 연령대의 Stress 기여도 = 비중 ÷ 100 × 인구 증감률. 지역 × 업종으로 더하면 Future Stress{% enddocs %}

{% docs col_size_cutoff %}분석 대상 규모 기준 = 업종총이용금액의 75분위수 (상위 25%){% enddocs %}

{% docs col_is_growing %}현재 성장 = 1→6월 증감률 > 0, 월평균 증감률 > 0, 오른 달 ≥ 3 을 모두 만족{% enddocs %}

{% docs col_market_type %}4유형: 착시성장형(성장 · 취약) · 지속성장형(성장 · 안정) · 구조취약형(비성장 · 취약) · 회복기회형(비성장 · 안정). Stress 2040 기준{% enddocs %}
