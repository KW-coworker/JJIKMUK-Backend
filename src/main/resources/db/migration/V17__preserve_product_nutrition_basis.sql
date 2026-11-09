-- Additive only: no mass UPDATE or guessed 100g default at startup.
ALTER TABLE products ADD COLUMN nutrition_basis_raw VARCHAR(255) NULL, ALGORITHM=INSTANT;

-- Existing rollback tables must remain readable after a dataset swap.
SET @nutrition_staging = (SELECT IF(COUNT(*) > 0,
    'ALTER TABLE products_staging ADD COLUMN nutrition_basis_raw VARCHAR(255) NULL, ALGORITHM=INSTANT',
    'SELECT 1') FROM information_schema.tables
    WHERE table_schema=DATABASE() AND table_name='products_staging');
PREPARE nutrition_staging_statement FROM @nutrition_staging;
EXECUTE nutrition_staging_statement;
DEALLOCATE PREPARE nutrition_staging_statement;

SET @nutrition_rollback = (SELECT IF(COUNT(*) > 0,
    'ALTER TABLE products_rollback ADD COLUMN nutrition_basis_raw VARCHAR(255) NULL, ALGORITHM=INSTANT',
    'SELECT 1') FROM information_schema.tables
    WHERE table_schema=DATABASE() AND table_name='products_rollback');
PREPARE nutrition_rollback_statement FROM @nutrition_rollback;
EXECUTE nutrition_rollback_statement;
DEALLOCATE PREPARE nutrition_rollback_statement;
