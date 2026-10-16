-- A completed order with nothing paid is a fault.
select order_id
from {{ ref('orders') }}
where status = 'completed' and amount is null
