-- Apply on staging first; verify conversations.id is signed INT and InnoDB.
CREATE TABLE IF NOT EXISTS chat_turn_requests (
    user_id INT NOT NULL,
    request_key VARCHAR(32) NOT NULL,
    conversation_id INT NOT NULL,
    active_conversation_id INT NULL,
    kind VARCHAR(16) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    state VARCHAR(16) NOT NULL,
    token VARCHAR(32) NOT NULL,
    baseline_message_id INT NOT NULL,
    message_id INT NULL,
    lease_until DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, request_key),
    UNIQUE KEY uq_chat_turn_active_conversation (active_conversation_id),
    INDEX ix_chat_turn_requests_conversation_id (conversation_id),
    CONSTRAINT fk_chat_turn_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
