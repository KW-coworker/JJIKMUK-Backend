-- Apply through a controlled deployment after backup. Never run as an ad-hoc production script.
ALTER TABLE users ADD COLUMN google_subject VARCHAR(255) NULL,
    ADD COLUMN has_profile_photo BOOLEAN NOT NULL DEFAULT FALSE,
    ADD CONSTRAINT uk_users_google_subject UNIQUE (google_subject);

CREATE TABLE auth_sessions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    token_version INT NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    INDEX idx_auth_sessions_user (user_id),
    CONSTRAINT fk_auth_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE refresh_credentials (
    token_hash VARCHAR(64) NOT NULL PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    consumed_at DATETIME(6) NULL,
    INDEX idx_refresh_session (session_id),
    CONSTRAINT fk_refresh_session FOREIGN KEY (session_id) REFERENCES auth_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE google_link_grants (
    token_hash VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    google_subject VARCHAR(255) NOT NULL,
    token_version INT NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    consumed_at DATETIME(6) NULL,
    INDEX idx_link_user (user_id),
    CONSTRAINT fk_link_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE family_profiles (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    nickname VARCHAR(20) NOT NULL,
    allergies VARCHAR(1000) NULL,
    special_diet VARCHAR(1000) NULL,
    diseases VARCHAR(1000) NULL,
    disliked_ingredients VARCHAR(1000) NULL,
    version BIGINT NOT NULL DEFAULT 0,
    INDEX idx_family_owner (owner_id),
    CONSTRAINT fk_family_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
CREATE TABLE profile_photos (
    user_id BIGINT NOT NULL PRIMARY KEY,
    content LONGBLOB NOT NULL,
    content_type VARCHAR(32) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_photo_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;
