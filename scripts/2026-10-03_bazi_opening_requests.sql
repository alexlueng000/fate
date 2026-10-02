-- Apply AFTER chat_turn_requests and its request_payload migration on staging.
-- Verify conversations.id is signed INT and uses InnoDB. No old data is deleted.
CREATE TABLE IF NOT EXISTS bazi_opening_requests (
    user_id INT NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    request_key VARCHAR(32) NOT NULL,
    conversation_id INT NOT NULL,
    request_payload JSON NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, source_hash),
    UNIQUE KEY uq_bazi_opening_request_key (request_key),
    UNIQUE KEY uq_bazi_opening_conversation (conversation_id),
    CONSTRAINT fk_bazi_opening_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
