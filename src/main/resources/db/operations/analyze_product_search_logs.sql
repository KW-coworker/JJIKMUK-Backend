-- Aggregate only sufficiently populated periods; very small samples are misleading.
SELECT DATE(created_at) AS search_date,
       endpoint,
       search_mode,
       COUNT(*) AS searches,
       SUM(result_count = 0) AS zero_result_searches,
       ROUND(100 * AVG(result_count = 0), 2) AS zero_result_rate_percent,
       ROUND(AVG(latency_micros) / 1000, 2) AS average_latency_ms
FROM product_search_logs
WHERE created_at >= CURRENT_DATE - INTERVAL 30 DAY
GROUP BY DATE(created_at), endpoint, search_mode
ORDER BY search_date DESC, endpoint, search_mode;

SELECT normalized_query,
       COUNT(*) AS searches,
       ROUND(AVG(latency_micros) / 1000, 2) AS average_latency_ms
FROM product_search_logs
WHERE result_count = 0
  AND normalized_query IS NOT NULL
  AND created_at >= CURRENT_DATE - INTERVAL 30 DAY
GROUP BY compact_query_hash, normalized_query
ORDER BY searches DESC, normalized_query
LIMIT 100;

SELECT dataset_version, search_mode, case_count,
       passed,
       ROUND(hit_rate_at_k * 100, 2) AS hit_rate_percent,
       ROUND(mean_reciprocal_rank, 4) AS mrr,
       ROUND(zero_result_rate * 100, 2) AS zero_result_rate_percent,
       ROUND(average_latency_micros / 1000, 2) AS average_latency_ms,
       ROUND(p95_latency_micros / 1000, 2) AS p95_latency_ms,
       created_at
FROM product_search_evaluation_runs
ORDER BY evaluation_run_id DESC;

-- Example retention batch. Repeat in a scheduled maintenance job if 90 days is
-- the agreed retention period; do not run without confirming that policy.
-- DELETE FROM product_search_logs
-- WHERE created_at < CURRENT_DATE - INTERVAL 90 DAY
-- ORDER BY search_log_id
-- LIMIT 10000;
