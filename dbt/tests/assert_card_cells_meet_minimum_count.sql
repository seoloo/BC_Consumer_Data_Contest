{#
  원본의 모든 칸(시군구 × 성별 × 연령 × 업종 × 월)이 결제 11건 이상인가 (config.MIN_CARD_PAYMENT_COUNT)

  원본 제공처는 결제 10건 이하인 칸을 빼고 제공합니다. 작은 칸에서는 몇 사람의 결제가 드러날 수 있기 때문입니다.
  새 달 원본이 이 기준을 어기고 들어오면(제공 방식이 바뀌었거나 다른 파일이 섞임) 여기서 멈춰 사람이 확인하게 합니다.
#}
select strd_yymm, sido_nm, ccg_nm, tp_buz_nm, cnt, source_file
from {{ source('raw', 'card_spending') }}
where cnt < {{ var('min_card_payment_count') }}
