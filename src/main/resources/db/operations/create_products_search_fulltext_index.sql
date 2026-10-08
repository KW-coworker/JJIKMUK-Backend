-- Run this file manually in a measured maintenance window, after the backfill.
-- Preflight checks
SELECT COUNT(*) AS total_products,
       SUM(search_keywords IS NULL) AS missing_search_keywords,
       SUM(NULLIF(TRIM(search_keywords), '') IS NULL) AS unsearchable_products,
       AVG(CHAR_LENGTH(search_keywords)) AS average_keyword_characters,
       MAX(CHAR_LENGTH(search_keywords)) AS maximum_keyword_characters
FROM products;

SHOW VARIABLES LIKE 'ngram_token_size';

SELECT index_name, index_type
FROM information_schema.statistics
WHERE table_schema = DATABASE()
  AND table_name = 'products'
  AND index_name = 'ft_products_search_keywords';

SELECT column_name, column_type, extra
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'products'
  AND column_name = 'FTS_DOC_ID';

SELECT trx_id, trx_started, trx_state, trx_mysql_thread_id
FROM information_schema.innodb_trx
ORDER BY trx_started;

-- Execute only when the preflight query confirms that the index does not exist.
-- LOCK=SHARED keeps SELECT available but blocks INSERT/UPDATE/DELETE.
CREATE FULLTEXT INDEX ft_products_search_keywords
    ON products(search_keywords)
    WITH PARSER ngram
    ALGORITHM=INPLACE
    LOCK=SHARED;

INSERT INTO system_configs(config_key, config_value, updated_at)
VALUES ('PRODUCT_SEARCH_INDEX_STATUS', 'COMPLETED:NGRAM_2', NOW(6))
ON DUPLICATE KEY UPDATE
    config_value = 'COMPLETED:NGRAM_2',
    updated_at = NOW(6);

-- Postflight verification
SHOW CREATE TABLE products;

EXPLAIN
SELECT barcode
FROM products
WHERE MATCH(search_keywords)
      AGAINST ('+"매운새우깡"' IN BOOLEAN MODE)
LIMIT 20;
