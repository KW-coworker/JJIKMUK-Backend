-- Stage 4 recommendation health/performance checks (MySQL 8.0).
-- Run after V6 and only against the intended database.

SELECT
    COUNT(*) AS neighbor_source_rows,
    MIN(recommendation_count) AS minimum_neighbors,
    AVG(recommendation_count) AS average_neighbors,
    MAX(recommendation_count) AS maximum_neighbors
FROM product_neighbor_sets;

SELECT COUNT(*) AS neighbor_sources_missing_from_products
FROM product_neighbor_sets n
LEFT JOIN products p ON p.barcode = n.source_barcode
WHERE p.barcode IS NULL;

SELECT
    DATE(created_at) AS recommendation_date,
    COUNT(*) AS requests,
    AVG(result_count) AS average_results,
    AVG(fallback_result_count) AS average_fallback_results,
    SUM(result_mode <> 'VERIFIED') / COUNT(*) AS fallback_or_action_rate,
    SUM(result_mode = 'VERIFICATION_REQUIRED') / COUNT(*) AS verification_required_rate,
    SUM(result_count = 0 AND fallback_result_count = 0) / COUNT(*) AS display_empty_rate,
    AVG(eligible_candidate_count) AS average_eligible_candidates,
    AVG(neighbor_lookup_micros) / 1000 AS average_neighbor_lookup_ms,
    AVG(product_fetch_micros) / 1000 AS average_product_fetch_ms,
    AVG(history_fetch_micros) / 1000 AS average_history_fetch_ms,
    AVG(ranking_micros) / 1000 AS average_ranking_ms,
    AVG(total_latency_micros) / 1000 AS average_total_ms,
    SUM(danger_excluded) AS danger_excluded,
    SUM(unknown_safety_excluded) AS unknown_safety_excluded,
    SUM(diet_mismatch_excluded) AS diet_mismatch_excluded,
    SUM(diet_unknown_excluded) AS diet_unknown_excluded
FROM product_recommendation_logs
GROUP BY DATE(created_at)
ORDER BY recommendation_date DESC;

SELECT
    COALESCE(result_mode, 'LEGACY') AS result_mode,
    COALESCE(fallback_reason, 'NONE') AS fallback_reason,
    COUNT(*) AS requests,
    AVG(fallback_candidate_count) AS average_fallback_candidates,
    AVG(fallback_result_count) AS average_fallback_results,
    SUM(verification_required_result_count) AS verification_required_results
FROM product_recommendation_logs
GROUP BY COALESCE(result_mode, 'LEGACY'), COALESCE(fallback_reason, 'NONE')
ORDER BY requests DESC;

WITH ranked_latency AS (
    SELECT
        total_latency_micros,
        CUME_DIST() OVER (ORDER BY total_latency_micros) AS percentile_rank
    FROM product_recommendation_logs
    WHERE created_at >= NOW() - INTERVAL 7 DAY
)
SELECT MIN(total_latency_micros) / 1000 AS p95_total_latency_ms
FROM ranked_latency
WHERE percentile_rank >= 0.95;

SELECT
    feedback_type,
    COUNT(*) AS events,
    AVG(rank_position) AS average_rank
FROM product_recommendation_feedback
GROUP BY feedback_type
ORDER BY events DESC;

SELECT
    evaluation_run_id,
    dataset_version,
    policy_version,
    case_count,
    hit_rate_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    hard_constraint_violation_rate,
    unknown_safety_rate,
    verification_required_rate,
    fallback_case_rate,
    empty_response_rate,
    catalog_coverage,
    average_latency_micros / 1000 AS average_latency_ms,
    p95_latency_micros / 1000 AS p95_latency_ms,
    passed,
    created_at
FROM product_recommendation_evaluation_runs
ORDER BY evaluation_run_id DESC
LIMIT 20;
