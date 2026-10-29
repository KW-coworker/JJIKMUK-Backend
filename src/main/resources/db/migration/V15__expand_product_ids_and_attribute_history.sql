-- Expand only. Never changes barcode PK, backfills 1M rows or merges identities at startup.
-- Some installations already ran db/operations/add_product_internal_id.sql.
SET @add_product_id = (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE products ADD COLUMN product_id BIGINT NULL, ALGORITHM=INSTANT',
    'SELECT 1') FROM information_schema.columns
    WHERE table_schema=DATABASE() AND table_name='products' AND column_name='product_id');
PREPARE add_product_id_statement FROM @add_product_id;
EXECUTE add_product_id_statement;
DEALLOCATE PREPARE add_product_id_statement;

ALTER TABLE products ADD COLUMN attribute_snapshot_id BIGINT NULL, ALGORITHM=INSTANT;
ALTER TABLE histories ADD COLUMN product_id BIGINT NULL,
    ADD COLUMN attribute_snapshot_id BIGINT NULL, ALGORITHM=INSTANT;

-- This high-water mark is outside the dataset tables and is NEVER swapped/rolled back.
CREATE TABLE product_id_sequence (
    sequence_name VARCHAR(32) NOT NULL PRIMARY KEY,
    next_id BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
INSERT INTO product_id_sequence(sequence_name,next_id) VALUES ('products',1);

-- No FK to products: its table is atomically replaced by the dataset importer.
CREATE TABLE product_attribute_snapshots (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL,
    previous_snapshot_id BIGINT NULL,
    dataset_version VARCHAR(128) NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    observed_by VARCHAR(128) NOT NULL,
    rule_version VARCHAR(64) NOT NULL,
    change_reason VARCHAR(500) NOT NULL,
    changed_fields TEXT NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    payload_json LONGTEXT NOT NULL,
    INDEX idx_attribute_product (product_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
