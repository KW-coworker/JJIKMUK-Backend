-- Separate sign-up and password-reset OTP state and add one-time verification grants.
ALTER TABLE email_verifications
    ADD COLUMN purpose VARCHAR(32) NOT NULL DEFAULT 'SIGNUP' AFTER email,
    ADD COLUMN sent_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) AFTER expired_at,
    ADD COLUMN send_count INT NOT NULL DEFAULT 1 AFTER sent_at,
    ADD COLUMN failed_attempts INT NOT NULL DEFAULT 0 AFTER send_count;

ALTER TABLE email_verifications
    ADD CONSTRAINT uk_email_verifications_email_purpose UNIQUE (email, purpose);

CREATE TABLE email_verification_grants (
    id BIGINT NOT NULL AUTO_INCREMENT,
    email VARCHAR(255) NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expired_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_email_verification_grants_email_purpose UNIQUE (email, purpose),
    INDEX idx_email_verification_grants_expired_at (expired_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
