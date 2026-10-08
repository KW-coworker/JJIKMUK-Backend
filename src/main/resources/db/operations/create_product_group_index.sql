-- Run after PRODUCT_DATA_MODEL_BACKFILL_STATUS becomes COMPLETED and the
-- missing count is zero. Index creation is separated from application startup.
SELECT COUNT(*) AS missing_product_group_keys
FROM products
WHERE product_group_key IS NULL;

SELECT index_name
FROM information_schema.statistics
WHERE table_schema = DATABASE()
  AND table_name = 'products'
  AND index_name = 'idx_products_product_group_key';

CREATE INDEX idx_products_product_group_key
    ON products(product_group_key);
