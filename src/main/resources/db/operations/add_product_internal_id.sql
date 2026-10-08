-- Stage 1 expand migration. Run only in a measured maintenance window.
-- This can rebuild the 1M+ row table; it is intentionally not a Flyway startup migration.

SELECT COUNT(*) AS product_count FROM products;

SELECT column_name, column_type, column_key, extra
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'products'
  AND column_name IN ('product_id', 'barcode');

-- Keep barcode as the current primary/API key during the transition. The new
-- product_id is populated for old rows and generated for future inserts.
ALTER TABLE products
    ADD COLUMN product_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    ADD UNIQUE KEY uk_products_product_id (product_id);

SELECT COUNT(*) AS missing_product_ids
FROM products
WHERE product_id IS NULL;

SELECT COUNT(*) AS duplicate_product_ids
FROM (
    SELECT product_id
    FROM products
    GROUP BY product_id
    HAVING COUNT(*) > 1
) duplicates;

-- Do not switch the primary key or make barcode nullable in this stage.
-- That contract migration must follow the staging-table importer conversion.
