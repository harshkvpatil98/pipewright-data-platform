{% snapshot customers_snapshot %}
{{ config(target_schema='snapshots', unique_key='id', strategy='check', check_cols=['first_name']) }}
select * from {{ ref('raw_customers') }}
{% endsnapshot %}
