select
    order_id,
    customer_id,
    amount
from {{ ref('orders') }}
where amount >= {{ var('min_order_amount') }}
