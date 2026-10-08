CREATE TABLE IF NOT EXISTS product_food_category_memberships (
    barcode VARCHAR(255) NOT NULL,
    category_id VARCHAR(32) NOT NULL,
    PRIMARY KEY (barcode, category_id)
);

CREATE INDEX IF NOT EXISTS idx_product_food_category_lookup
    ON product_food_category_memberships(category_id, barcode);

CREATE TABLE IF NOT EXISTS product_allergy_classification_memberships (
    barcode VARCHAR(255) NOT NULL,
    allergy_id VARCHAR(32) NOT NULL,
    PRIMARY KEY (barcode, allergy_id)
);

CREATE INDEX IF NOT EXISTS idx_product_allergy_classification_lookup
    ON product_allergy_classification_memberships(allergy_id, barcode);
