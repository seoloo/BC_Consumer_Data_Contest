{#
  지역 × 업종마다 연령대 비중을 더하면 100%에 가까워야 합니다.
  비중은 소수 첫째 자리로 반올림되어 있어 연령대 6개면 최대 ±0.3 어긋날 수 있으므로, 그보다 크면 실패로 봅니다.
  (비중 계산에서 분모 · 분자를 잘못 묶으면 여기서 바로 드러납니다)
#}
select province, district, industry_code, sum(amount_share) as share_sum
from {{ ref('gold_age_spending_structure') }}
group by province, district, industry_code
having abs(sum(amount_share) - 100) > 0.31
