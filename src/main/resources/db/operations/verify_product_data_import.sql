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
           AND NULLIF(TRIM(clean_product_name), '') IS NULL) AS missing_names,
       SUM(NULLIF(TRIM(food_categories), '') IS NULL) AS missing_food_categories,
       SUM(NULLIF(TRIM(allergy_classification), '') IS NULL) AS missing_allergy_classification,
       SUM(food_categories = '미분류') AS unclassified_food,
       SUM(allergy_classification = '미검출') AS allergy_not_detected,
       SUM(allergy_classification = '정보없음') AS allergy_no_information,
       SUM(food_categories LIKE '%|%') AS multi_food_category,
       SUM(allergy_classification LIKE '%|%') AS multi_allergy_classification
FROM products;

SELECT
    (SELECT COUNT(*) FROM product_food_category_memberships) AS food_category_memberships,
    (SELECT COUNT(*) FROM product_allergy_classification_memberships) AS allergy_memberships,
    (SELECT COUNT(*)
       FROM product_food_category_memberships membership
       LEFT JOIN products product ON product.barcode = membership.barcode
      WHERE product.barcode IS NULL) AS orphan_food_category_memberships,
    (SELECT COUNT(*)
       FROM product_allergy_classification_memberships membership
       LEFT JOIN products product ON product.barcode = membership.barcode
      WHERE product.barcode IS NULL) AS orphan_allergy_memberships;

SELECT table_name, table_rows, table_comment
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN (
      'products', 'products_rollback', 'products_staging',
      'product_food_category_memberships', 'product_food_category_memberships_rollback',
      'product_allergy_classification_memberships',
      'product_allergy_classification_memberships_rollback'
  );
