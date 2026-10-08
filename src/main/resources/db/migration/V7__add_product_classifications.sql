-- Consumer-facing multi-category and normalized allergy classifications.
-- They are nullable during the migration; the versioned CSV staging import
-- fills every row before the atomic products table swap.
ALTER TABLE products
    ADD COLUMN food_categories VARCHAR(500) NULL,
    ADD COLUMN allergy_classification VARCHAR(500) NULL,
    ALGORITHM=INSTANT;
