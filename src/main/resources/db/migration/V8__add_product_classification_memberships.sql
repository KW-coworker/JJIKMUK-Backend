-- Indexed many-to-many projections used by category/allergen filters.
-- No foreign keys are intentional: the products importer atomically renames
-- the live/staging/rollback tables as one dataset.
CREATE TABLE product_food_category_memberships (
    barcode VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
    category_id VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (barcode, category_id),
    INDEX idx_product_food_category_lookup (category_id, barcode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE product_allergy_classification_memberships (
    barcode VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
    allergy_id VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (barcode, allergy_id),
    INDEX idx_product_allergy_classification_lookup (allergy_id, barcode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
