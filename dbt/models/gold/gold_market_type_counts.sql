-- [Gold · STEP 5] 지역별 4유형 건수. 유형 목록은 기준표(seed)에서 가져와, 한 건도 없는 유형도 0으로 보입니다.
select types.market_type,
       count(cases.market_type) filter (where cases.province = '서울특별시') as seoul,
       count(cases.market_type) filter (where cases.province = '부산광역시') as busan,
       count(cases.market_type) filter (where cases.province = '경기도') as gyeonggi
from {{ ref('market_types') }} as types
left join {{ ref('gold_market_type') }} as cases on cases.market_type = types.market_type
group by types.market_type, types.sort_order
order by types.sort_order
