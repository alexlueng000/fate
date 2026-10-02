-- Additive staging migration. No existing reports/messages are changed.
CREATE TABLE IF NOT EXISTS personal_report_requests (
    profile_id INT UNSIGNED NOT NULL PRIMARY KEY,
    user_id INT UNSIGNED NOT NULL,
    chart_hash VARCHAR(64) NOT NULL,
    state VARCHAR(16) NOT NULL,
    token VARCHAR(32) NOT NULL,
    conversation_id INT NOT NULL,
    lease_until DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX ix_personal_report_requests_user_id (user_id),
    CONSTRAINT fk_personal_report_profile FOREIGN KEY (profile_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
    CONSTRAINT fk_personal_report_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
