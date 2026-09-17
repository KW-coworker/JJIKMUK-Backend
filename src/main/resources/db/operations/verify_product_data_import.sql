-- Run after a product-import job and before enabling dependent backfills/indexes.
SELECT config_key, config_value, updated_at
FROM system_configs
WHERE config_key LIKE 'PRODUCT_DB_%'
ORDER BY config_key;

SELECT import_id, import_action, dataset_version, status,
       source_record_count, staged_row_count, active_row_count,
       duplicate_barcode_count, started_at, finished_at, error_message
FROM product_data_import_runs
ORDER BY import_id DESC
LIMIT 10;

SELECT COUNT(*) AS active_products,
       SUM(barcode IS NULL OR TRIM(barcode) = '') AS invalid_barcodes,
       SUM(NULLIF(TRIM(product_name), '') IS NULL
           AND NULLIF(TRIM(clean_product_name), '') IS NULL) AS missing_names
FROM products;

SELECT table_name, table_rows, table_comment
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN ('products', 'products_rollback', 'products_staging');
