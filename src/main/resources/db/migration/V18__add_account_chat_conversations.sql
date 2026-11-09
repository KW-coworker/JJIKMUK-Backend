-- Account-visible conversation storage is separate from AI diagnostic chatbot_logs.
-- Deploy only after backup/approval; no migration of ownerless device history.
CREATE TABLE chat_conversations (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    owner_id BIGINT NOT NULL,
    client_conversation_id VARCHAR(36) NOT NULL,
    title VARCHAR(100) NOT NULL,
    active_turn_id BIGINT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT uk_chat_conversation_owner_client UNIQUE (owner_id, client_conversation_id),
    INDEX idx_chat_conversation_owner_updated (owner_id, updated_at, id),
    CONSTRAINT fk_chat_conversation_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chat_turns (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    client_message_id VARCHAR(36) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    context_hash VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    barcode VARCHAR(255) NULL,
    status VARCHAR(16) NOT NULL,
    response_body LONGTEXT NULL,
    error_code VARCHAR(80) NULL,
    created_at DATETIME(6) NOT NULL,
    completed_at DATETIME(6) NULL,
    expires_at DATETIME(6) NOT NULL,
    CONSTRAINT uk_chat_turn_conversation_client UNIQUE (conversation_id, client_message_id),
    INDEX idx_chat_turn_conversation_id (conversation_id, id),
    INDEX idx_chat_turn_context (conversation_id, context_hash, status, id),
    CONSTRAINT fk_chat_turn_conversation FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
