%sql
SELECT 'pipeline_log row count = '      || CAST(COUNT(*) AS STRING) FROM vinoworld.audit.pipeline_log
UNION ALL
SELECT 'silver.dim_roduct row count = '      || CAST(COUNT(*) AS STRING) FROM vinoworld.silver.dim_product
UNION ALL
SELECT 'silver.dim_region row count = '      || CAST(COUNT(*) AS STRING) FROM vinoworld.silver.dim_region
UNION ALL
SELECT 'dev_pipeline_log row count = '      || CAST(COUNT(*) AS STRING) FROM dev_vinoworld.audit.pipeline_log
UNION ALL
SELECT 'dev_silver_dim_product row count = '      || CAST(COUNT(*) AS STRING) FROM dev_vinoworld.silver.dim_product
UNION ALL
SELECT 'dev_silver_dim_region row count = '      || CAST(COUNT(*) AS STRING) FROM dev_vinoworld.silver.dim_region

