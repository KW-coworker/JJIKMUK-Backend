CREATE TABLE IF NOT EXISTS product_search_logs (
    search_log_id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NULL,
    endpoint VARCHAR(20) NOT NULL,
    normalized_query VARCHAR(200) NULL,
    compact_query_hash CHAR(64) NULL,
    applied_filters VARCHAR(500) NULL,
    match_mode VARCHAR(10) NULL,
    search_mode VARCHAR(20) NOT NULL,
    result_count BIGINT NOT NULL,
    latency_micros BIGINT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (search_log_id),
    INDEX idx_product_search_logs_created_at (created_at),
    INDEX idx_product_search_logs_query_created (compact_query_hash, created_at),
    INDEX idx_product_search_logs_zero_result (result_count, created_at),
    INDEX idx_product_search_logs_user_created (user_id, created_at)
);

CREATE TABLE IF NOT EXISTS product_search_evaluation_runs (
    evaluation_run_id BIGINT NOT NULL AUTO_INCREMENT,
    dataset_version VARCHAR(100) NOT NULL,
    search_mode VARCHAR(20) NOT NULL,
    mysql_version VARCHAR(100) NOT NULL,
    ngram_token_size INT NULL,
    case_count INT NOT NULL,
    hit_rate_at_k DOUBLE NOT NULL,
    mean_reciprocal_rank DOUBLE NOT NULL,
    zero_result_rate DOUBLE NOT NULL,
    average_latency_micros DOUBLE NOT NULL,
    p95_latency_micros BIGINT NOT NULL,
    average_result_count DOUBLE NOT NULL,
    passed BOOLEAN NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (evaluation_run_id),
    INDEX idx_product_search_eval_created (created_at),
    INDEX idx_product_search_eval_mode_version (search_mode, dataset_version)
);

CREATE TABLE IF NOT EXISTS product_search_evaluation_results (
    evaluation_result_id BIGINT NOT NULL AUTO_INCREMENT,
    evaluation_run_id BIGINT NOT NULL,
    case_id VARCHAR(100) NOT NULL,
    query_text VARCHAR(200) NOT NULL,
    top_k INT NOT NULL,
    first_relevant_rank INT NULL,
    result_count INT NOT NULL,
    latency_micros BIGINT NOT NULL,
    passed BOOLEAN NOT NULL,
    top_barcodes TEXT NOT NULL,
    top_product_names TEXT NOT NULL,
    PRIMARY KEY (evaluation_result_id),
    UNIQUE KEY uk_product_search_eval_run_case (evaluation_run_id, case_id),
    CONSTRAINT fk_product_search_eval_result_run
        FOREIGN KEY (evaluation_run_id)
        REFERENCES product_search_evaluation_runs(evaluation_run_id)
        ON DELETE CASCADE
);
