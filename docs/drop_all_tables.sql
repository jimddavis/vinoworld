-- Drop all Vinoworld managed tables before running the Environment Setup job.
-- Run this manually in the Databricks SQL editor against the target catalog.
-- Safe to re-run — IF EXISTS prevents errors if a table is already gone.
--
-- Target catalog: vinoworld
-- Run order: gold → silver → bronze → audit (reverse dependency order)

-- Gold
DROP TABLE IF EXISTS vinoworld.gold.sales_fact;

-- Silver
DROP TABLE IF EXISTS vinoworld.silver.sales;
DROP TABLE IF EXISTS vinoworld.silver.dim_product;
DROP TABLE IF EXISTS vinoworld.silver.dim_territory;
DROP TABLE IF EXISTS vinoworld.silver.dim_store;
DROP TABLE IF EXISTS vinoworld.silver.dim_region;
DROP TABLE IF EXISTS vinoworld.silver.dim_exchange_rate;
DROP TABLE IF EXISTS vinoworld.silver.dim_date;
DROP TABLE IF EXISTS vinoworld.silver.dim_currency;

-- Bronze
DROP TABLE IF EXISTS vinoworld.bronze.products;
DROP TABLE IF EXISTS vinoworld.bronze.sales_verde;
DROP TABLE IF EXISTS vinoworld.bronze.sales_celeste;
DROP TABLE IF EXISTS vinoworld.bronze.sales_arancione;

-- Audit (drop last — pipeline logs reference these during runs)
DROP TABLE IF EXISTS vinoworld.audit.ingestion_log;
DROP TABLE IF EXISTS vinoworld.audit.transform_detail_log;
DROP TABLE IF EXISTS vinoworld.audit.pipeline_step_log;
DROP TABLE IF EXISTS vinoworld.audit.pipeline_log;
