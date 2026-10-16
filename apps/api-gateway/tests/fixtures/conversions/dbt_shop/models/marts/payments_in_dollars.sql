select
    payment_id,
    {{ cents_to_dollars('amount') }} as amount
from {{ ref('raw_payments') }}
