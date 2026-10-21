-- Staging: clean and standardize raw CRM tables. Mart: governed tables for reporting and AI.

DROP TABLE IF EXISTS stg_accounts;
CREATE TABLE stg_accounts AS
WITH ranked AS (
  SELECT a.*,
         MIN(account_id) OVER (PARTITION BY account_name, postal_code) AS survivor_id
  FROM raw_accounts a
)
SELECT r.account_id, r.account_name, r.account_type, r.territory_id,
       t.country_code,                              -- country taken from territory master
       r.postal_code, r.created_date, r.owner_rep_id
FROM ranked r
LEFT JOIN raw_territories t ON t.territory_id = r.territory_id
WHERE r.account_id = r.survivor_id                  -- drop duplicate account records
  AND r.territory_id IS NOT NULL;                   -- unassigned accounts go to the exceptions queue

DROP TABLE IF EXISTS account_merge_map;
CREATE TABLE account_merge_map AS
SELECT account_id,
       MIN(account_id) OVER (PARTITION BY account_name, postal_code) AS survivor_id
FROM raw_accounts;

DROP TABLE IF EXISTS stg_products;
CREATE TABLE stg_products AS
SELECT sku, product_name,
       CASE LOWER(category) WHEN 'surgical' THEN 'Surgical'
                            WHEN 'vision care' THEN 'Vision Care'
                            ELSE category END AS category,              -- map to the governed list
       list_price_usd
FROM raw_products;

DROP TABLE IF EXISTS stg_orders;
CREATE TABLE stg_orders AS
SELECT o.order_id, m.survivor_id AS account_id, o.order_date, o.sku, o.quantity,
       o.net_amount_usd, o.rep_id
FROM raw_orders o
JOIN account_merge_map m ON m.account_id = o.account_id          -- drops orphan orders
JOIN stg_products p ON p.sku = o.sku                              -- drops unknown SKUs
WHERE o.quantity > 0
  AND o.order_date <= '2025-12-31';

DROP TABLE IF EXISTS exceptions;
CREATE TABLE exceptions AS
SELECT 'orders' AS source, order_id AS record_id,
       CASE WHEN m.account_id IS NULL THEN 'orphan account'
            WHEN p.sku IS NULL THEN 'unknown SKU'
            WHEN o.quantity <= 0 THEN 'non-positive quantity'
            WHEN o.order_date > '2025-12-31' THEN 'future order date'
            ELSE 'account has no territory' END AS reason
FROM raw_orders o
LEFT JOIN account_merge_map m ON m.account_id = o.account_id
LEFT JOIN raw_products p ON p.sku = o.sku
LEFT JOIN stg_accounts s ON s.account_id = m.survivor_id
WHERE m.account_id IS NULL OR p.sku IS NULL OR o.quantity <= 0 OR o.order_date > '2025-12-31'
   OR s.account_id IS NULL
UNION ALL
SELECT 'accounts', account_id, 'missing territory' FROM raw_accounts WHERE territory_id IS NULL;

-- Mart
DROP TABLE IF EXISTS dim_account;
CREATE TABLE dim_account AS
SELECT a.account_id, a.account_name, a.account_type, a.territory_id, t.territory_name,
       t.region, a.country_code, a.owner_rep_id
FROM stg_accounts a JOIN raw_territories t ON t.territory_id = a.territory_id;

DROP TABLE IF EXISTS dim_product;
CREATE TABLE dim_product AS SELECT * FROM stg_products;

DROP TABLE IF EXISTS fct_orders;
CREATE TABLE fct_orders AS
SELECT o.order_id, o.account_id, o.order_date, SUBSTR(o.order_date, 1, 4) AS order_year,
       o.sku, p.category, o.quantity, o.net_amount_usd, a.region, a.territory_id, o.rep_id
FROM stg_orders o
JOIN dim_account a ON a.account_id = o.account_id
JOIN dim_product p ON p.sku = o.sku;
