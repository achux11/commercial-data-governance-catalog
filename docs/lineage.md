# Lineage

```mermaid
flowchart LR
  raw_accounts[raw_accounts] --> stg_accounts[stg_accounts]
  raw_territories[raw_territories] --> stg_accounts[stg_accounts]
  raw_accounts[raw_accounts] --> account_merge_map[account_merge_map]
  raw_products[raw_products] --> stg_products[stg_products]
  raw_orders[raw_orders] --> stg_orders[stg_orders]
  account_merge_map[account_merge_map] --> stg_orders[stg_orders]
  stg_products[stg_products] --> stg_orders[stg_orders]
  stg_accounts[stg_accounts] --> dim_account[dim_account]
  raw_territories[raw_territories] --> dim_account[dim_account]
  stg_products[stg_products] --> dim_product[dim_product]
  stg_orders[stg_orders] --> fct_orders[fct_orders]
  dim_account[dim_account] --> fct_orders[fct_orders]
  dim_product[dim_product] --> fct_orders[fct_orders]
  raw_orders[raw_orders] --> exceptions[exceptions]
  raw_accounts[raw_accounts] --> exceptions[exceptions]
  fct_orders[fct_orders] --> metric_net_sales_usd[metric:net_sales_usd]
  fct_orders[fct_orders] --> metric_active_accounts[metric:active_accounts]
  fct_orders[fct_orders] --> metric_avg_order_value_usd[metric:avg_order_value_usd]
  fct_orders[fct_orders] --> metric_surgical_share[metric:surgical_share]
  fct_orders[fct_orders] --> metric_latam_share[metric:latam_share]
```

- **net_sales_usd** ← raw_accounts, raw_orders, raw_products, raw_territories
- **active_accounts** ← raw_accounts, raw_orders, raw_products, raw_territories
- **avg_order_value_usd** ← raw_accounts, raw_orders, raw_products, raw_territories
- **surgical_share** ← raw_accounts, raw_orders, raw_products, raw_territories
- **latam_share** ← raw_accounts, raw_orders, raw_products, raw_territories
