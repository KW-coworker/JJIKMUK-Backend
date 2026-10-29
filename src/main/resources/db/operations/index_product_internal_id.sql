-- Explicit maintenance, AFTER V15. Inspect first; do NOT run if a unique product_id index exists.
-- Creating the index can consume IO/disk and briefly acquire metadata locks.
SELECT index_name, non_unique, column_name
FROM information_schema.statistics
WHERE table_schema=DATABASE() AND table_name='products' AND column_name='product_id';

SELECT product_id, COUNT(*) FROM products WHERE product_id IS NOT NULL
GROUP BY product_id HAVING COUNT(*) > 1 LIMIT 20;

-- Stop if duplicates exist. Do not rebuild this index automatically at application startup.
ALTER TABLE products ADD UNIQUE INDEX uk_products_product_id (product_id), ALGORITHM=INPLACE, LOCK=NONE;
