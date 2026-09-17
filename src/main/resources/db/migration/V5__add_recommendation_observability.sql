ALTER TABLE products
    ADD COLUMN food_type VARCHAR(500) NULL,
    ALGORITHM=INSTANT;

CREATE INDEX idx_histories_user_created
    ON histories(user_id, created_at);

CREATE INDEX idx_histories_user_action_created
    ON histories(user_id, action_type, created_at);

CREATE TABLE IF NOT EXISTS product_recommendation_logs (
    request_id CHAR(36) NOT NULL,
    user_id BIGINT NULL,
    reference_barcode VARCHAR(32) NOT NULL,
    policy_version VARCHAR(100) NOT NULL,
    model_version VARCHAR(100) NOT NULL,
    precomputed_candidate_count INT NOT NULL,
    eligible_candidate_count INT NOT NULL,
    result_count INT NOT NULL,
    danger_excluded INT NOT NULL,
    unknown_safety_excluded INT NOT NULL,
    diet_mismatch_excluded INT NOT NULL,
    diet_unknown_excluded INT NOT NULL,
    disliked_ingredient_excluded INT NOT NULL,
    neighbor_lookup_micros BIGINT NOT NULL,
    product_fetch_micros BIGINT NOT NULL,
    history_fetch_micros BIGINT NOT NULL,
    ranking_micros BIGINT NOT NULL,
    total_latency_micros BIGINT NOT NULL,
    result_barcodes TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (request_id),
    INDEX idx_product_recommendation_logs_created (created_at),
    INDEX idx_product_recommendation_logs_reference_created (reference_barcode, created_at),
    INDEX idx_product_recommendation_logs_user_created (user_id, created_at)
);

CREATE TABLE IF NOT EXISTS product_recommendation_feedback (
    feedback_id BIGINT NOT NULL AUTO_INCREMENT,
    request_id CHAR(36) NOT NULL,
    user_id BIGINT NOT NULL,
    product_barcode VARCHAR(32) NOT NULL,
    feedback_type VARCHAR(32) NOT NULL,
    rank_position INT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (feedback_id),
    UNIQUE KEY uk_product_recommendation_feedback_event
        (request_id, user_id, product_barcode, feedback_type),
    INDEX idx_product_recommendation_feedback_created (created_at),
    INDEX idx_product_recommendation_feedback_user_created (user_id, created_at)
);

CREATE TABLE IF NOT EXISTS product_recommendation_evaluation_cases (
    case_id VARCHAR(100) NOT NULL,
    user_id BIGINT NOT NULL,
    reference_barcode VARCHAR(32) NOT NULL,
    expected_relevant_barcodes TEXT NOT NULL,
    notes VARCHAR(1000) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (case_id),
    INDEX idx_product_recommendation_eval_cases_active (active)
);

CREATE TABLE IF NOT EXISTS product_recommendation_evaluation_runs (
    evaluation_run_id BIGINT NOT NULL AUTO_INCREMENT,
    dataset_version VARCHAR(100) NOT NULL,
    policy_version VARCHAR(100) NOT NULL,
    case_count INT NOT NULL,
    hit_rate_at_k DOUBLE NOT NULL,
    mean_reciprocal_rank DOUBLE NOT NULL,
    ndcg_at_k DOUBLE NOT NULL,
    hard_constraint_violation_rate DOUBLE NOT NULL,
    unknown_safety_rate DOUBLE NOT NULL,
    catalog_coverage DOUBLE NOT NULL,
    average_result_count DOUBLE NOT NULL,
    average_latency_micros DOUBLE NOT NULL,
    p95_latency_micros BIGINT NOT NULL,
    passed BOOLEAN NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (evaluation_run_id),
    INDEX idx_product_recommendation_eval_runs_created (created_at)
);

CREATE TABLE IF NOT EXISTS product_recommendation_evaluation_results (
    evaluation_result_id BIGINT NOT NULL AUTO_INCREMENT,
    evaluation_run_id BIGINT NOT NULL,
    case_id VARCHAR(100) NOT NULL,
    first_relevant_rank INT NULL,
    result_count INT NOT NULL,
    hard_constraint_violations INT NOT NULL,
    unknown_safety_items INT NOT NULL,
    latency_micros BIGINT NOT NULL,
    result_barcodes TEXT NOT NULL,
    PRIMARY KEY (evaluation_result_id),
    UNIQUE KEY uk_product_recommendation_eval_run_case (evaluation_run_id, case_id),
    CONSTRAINT fk_product_recommendation_eval_result_run
        FOREIGN KEY (evaluation_run_id)
        REFERENCES product_recommendation_evaluation_runs(evaluation_run_id)
        ON DELETE CASCADE
);
