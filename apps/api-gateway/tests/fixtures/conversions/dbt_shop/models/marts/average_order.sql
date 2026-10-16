select
    customer_id,
    count(*) as orders,
    sum(order_id) / count(*) as mean_order_id
from {{ ref('stg_orders') }}
group by customer_id
