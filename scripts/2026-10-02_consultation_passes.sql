-- Additive tables: order and user references are enforced by the service so the
-- migration works with legacy installations that use different signed ID types.
CREATE TABLE IF NOT EXISTS consultation_passes (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 order_id BIGINT UNSIGNED NOT NULL UNIQUE,
 user_id BIGINT UNSIGNED NOT NULL,
 conversation_id BIGINT UNSIGNED NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
 duration_hours INT NOT NULL,
 reply_limit INT NOT NULL,
 replies_used INT NOT NULL DEFAULT 0,
 starts_at DATETIME NULL,
 expires_at DATETIME NULL,
 INDEX ix_consultation_pass_user (user_id),
 INDEX ix_consultation_pass_conversation (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS consultation_requests (
 id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 pass_id INT NOT NULL,
 user_id BIGINT UNSIGNED NOT NULL,
 conversation_id BIGINT UNSIGNED NOT NULL,
 request_key VARCHAR(64) NOT NULL,
 input_hash VARCHAR(64) NOT NULL,
 user_message TEXT NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
 reply MEDIUMTEXT NULL,
 created_at DATETIME NOT NULL,
 completed_at DATETIME NULL,
 UNIQUE KEY uq_consult_request(user_id, request_key),
 INDEX ix_consultation_request_pass (pass_id),
 INDEX ix_consultation_request_conversation (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Intentionally no live product or price is inserted. Configure a consultation
-- product with features.consultation.duration_hours and reply_limit; no grants.
