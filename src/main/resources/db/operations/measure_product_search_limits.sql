SELECT VERSION() AS mysql_version,
       @@ngram_token_size AS ngram_token_size,
       @@innodb_ft_enable_stopword AS stopword_enabled;

SELECT COUNT(*) AS products,
       SUM(search_keywords IS NULL) AS missing_keywords,
       SUM(NULLIF(TRIM(search_keywords), '') IS NULL) AS unsearchable_products
FROM products;

SELECT table_rows, data_length, index_length,
       ROUND(index_length / 1024 / 1024, 2) AS total_index_mib
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'products';

-- Compare plans and measured execution time on the same compact query.
EXPLAIN ANALYZE
SELECT barcode
FROM products
WHERE MATCH(search_keywords)
      AGAINST ('+"매운새우깡"' IN BOOLEAN MODE)
ORDER BY MATCH(search_keywords)
         AGAINST ('매운새우깡' IN NATURAL LANGUAGE MODE) DESC
LIMIT 50;

EXPLAIN ANALYZE
SELECT barcode
FROM products
WHERE LOCATE(
          '매운새우깡',
          REGEXP_REPLACE(
              LOWER(COALESCE(product_name, '')),
              '[^0-9a-z가-힣]+',
              ''
          )
      ) > 0
LIMIT 50;

-- ngram_token_size=2 cannot index a single-character query. The public API
-- therefore rejects queries shorter than two characters.
SELECT MATCH(search_keywords)
       AGAINST ('+"콩"' IN BOOLEAN MODE) AS one_character_score
FROM products
LIMIT 5;
