-- Additive, backward-compatible metadata only. Existing rows remain explicitly
-- unverified until their lineage can be reconstructed from source data.
ALTER TABLE products
    ADD COLUMN product_group_key CHAR(64) NULL,
    ADD COLUMN allergy_evidence_level VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN allergy_data_confidence DOUBLE NULL,
    ADD COLUMN nutrition_data_origin VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN nutrition_data_confidence DOUBLE NULL,
    ADD COLUMN dietary_data_origin VARCHAR(32) NOT NULL DEFAULT 'INFERRED',
    ADD COLUMN dietary_data_confidence DOUBLE NULL,
    ALGORITHM=INSTANT;
