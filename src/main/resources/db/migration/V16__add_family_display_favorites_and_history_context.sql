-- Apply only through an approved deployment after backup (V15 + product ID issuance required).
-- Emoji columns explicitly support supplementary Unicode characters even on legacy databases.
ALTER TABLE family_profiles
    ADD COLUMN relationship VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
    ADD COLUMN emoji VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL;

ALTER TABLE histories
    ADD COLUMN analysis_mode VARCHAR(16) NOT NULL DEFAULT 'self',
    ADD COLUMN personalization_allowed BOOLEAN NOT NULL DEFAULT TRUE;
-- Reuse V5 idx_histories_user_action_created for view filtering/order; InnoDB includes the PK.
CREATE INDEX idx_history_product_view ON histories(user_id, product_id, barcode, created_at, id);
CREATE INDEX idx_history_personalization ON histories(user_id, personalization_allowed, created_at, id);

-- Do not reference products: catalogue tables are swapped on import.
-- Stable product IDs must never be recycled. Missing products remain removable from favorites.
CREATE TABLE product_favorites (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    barcode VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT uk_favorite_user_product UNIQUE (user_id, product_id),
    INDEX idx_favorite_user_created (user_id, created_at, id),
    CONSTRAINT fk_favorite_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
