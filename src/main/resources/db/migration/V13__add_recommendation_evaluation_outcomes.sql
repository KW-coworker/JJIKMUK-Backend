-- Old cases retain positive-recommendation semantics. Historical new metrics are NULL (not measured).
ALTER TABLE product_recommendation_evaluation_cases
    ADD COLUMN expected_outcome VARCHAR(32) NOT NULL DEFAULT 'RECOMMENDATION',
    ADD COLUMN forbidden_barcodes TEXT NULL;

ALTER TABLE product_recommendation_evaluation_runs
    ADD COLUMN ranking_case_count INT NULL,
    ADD COLUMN abstention_case_count INT NULL,
    ADD COLUMN verification_case_count INT NULL,
    ADD COLUMN outcome_match_rate DOUBLE NULL,
    ADD COLUMN correct_abstention_rate DOUBLE NULL,
    ADD COLUMN unexpected_empty_response_rate DOUBLE NULL,
    ADD COLUMN presentation_violation_count INT NULL,
    ADD COLUMN verification_fallback_hit_rate DOUBLE NULL,
    ADD COLUMN evaluation_k INT NULL;

ALTER TABLE product_recommendation_evaluation_results
    ADD COLUMN expected_outcome VARCHAR(32) NULL,
    ADD COLUMN outcome_matched BOOLEAN NULL,
    ADD COLUMN unexpected_empty BOOLEAN NULL,
    ADD COLUMN presentation_violations INT NULL,
    ADD COLUMN fallback_relevant BOOLEAN NULL,
    ADD COLUMN ndcg_at_k DOUBLE NULL;
