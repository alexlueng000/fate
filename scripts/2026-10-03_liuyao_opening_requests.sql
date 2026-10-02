-- Apply AFTER chat_turn_requests on staging. Verify liuyao_hexagrams.id is
-- BIGINT UNSIGNED, conversations.id is signed INT, and both use InnoDB.
CREATE TABLE IF NOT EXISTS liuyao_opening_requests (
    hexagram_id BIGINT UNSIGNED NOT NULL,
    user_id INT NOT NULL,
    request_key VARCHAR(32) NOT NULL,
    conversation_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (hexagram_id),
    UNIQUE KEY uq_liuyao_opening_request_key (request_key),
    UNIQUE KEY uq_liuyao_opening_conversation (conversation_id),
    CONSTRAINT fk_liuyao_opening_hexagram FOREIGN KEY (hexagram_id) REFERENCES liuyao_hexagrams(id) ON DELETE CASCADE,
    CONSTRAINT fk_liuyao_opening_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
