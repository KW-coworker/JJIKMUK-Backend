ALTER TABLE product_recommendation_logs
    ADD COLUMN result_mode VARCHAR(32) NULL,
    ADD COLUMN fallback_candidate_count INT NOT NULL DEFAULT 0,
    ADD COLUMN fallback_result_count INT NOT NULL DEFAULT 0,
    ADD COLUMN verification_required_result_count INT NOT NULL DEFAULT 0,
    ADD COLUMN fallback_reason VARCHAR(100) NULL,
    ADD COLUMN fallback_barcodes TEXT NULL,
    ALGORITHM=INSTANT;

ALTER TABLE product_recommendation_evaluation_runs
    ADD COLUMN verification_required_rate DOUBLE NOT NULL DEFAULT 0,
    ADD COLUMN fallback_case_rate DOUBLE NOT NULL DEFAULT 0,
    ADD COLUMN empty_response_rate DOUBLE NOT NULL DEFAULT 0,
    ALGORITHM=INSTANT;

ALTER TABLE product_recommendation_evaluation_results
    ADD COLUMN fallback_result_count INT NOT NULL DEFAULT 0,
    ADD COLUMN verification_required_items INT NOT NULL DEFAULT 0,
    ADD COLUMN empty_response BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN result_mode VARCHAR(32) NULL,
    ALGORITHM=INSTANT;
