-- Migration: Add refund and reversible entitlement audit tables
-- Date: 2026-07-20
-- Purpose: Track WeChat refunds and make quota/membership grants attributable
--          to a specific order before refund business logic is enabled.

CREATE TABLE refunds (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    out_refund_no VARCHAR(64) NOT NULL,
    wechat_refund_id VARCHAR(64) NULL,
    refund_cents INT NOT NULL,
    total_cents INT NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
    reason VARCHAR(256) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREATED',
    requested_by BIGINT UNSIGNED NULL,
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    success_at DATETIME NULL,
    raw_request TEXT NULL,
    raw_response TEXT NULL,
    failure_code VARCHAR(64) NULL,
    failure_message VARCHAR(512) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT ck_refunds_refund_cents_positive CHECK (refund_cents > 0),
    CONSTRAINT ck_refunds_total_covers_refund CHECK (total_cents >= refund_cents),
    CONSTRAINT uk_refunds_out_refund_no UNIQUE (out_refund_no),
    CONSTRAINT uk_refunds_wechat_refund_id UNIQUE (wechat_refund_id),
    CONSTRAINT fk_refunds_order FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE RESTRICT,
    CONSTRAINT fk_refunds_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_refunds_requested_by FOREIGN KEY (requested_by) REFERENCES users (id) ON DELETE SET NULL,
    INDEX ix_refunds_order_status (order_id, status),
    INDEX ix_refunds_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE quota_ledger (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    quota_type VARCHAR(50) NOT NULL,
    delta INT NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    order_id BIGINT UNSIGNED NULL,
    refund_id BIGINT UNSIGNED NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    note TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT ck_quota_ledger_delta_nonzero CHECK (delta <> 0),
    CONSTRAINT uk_quota_ledger_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT fk_quota_ledger_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_quota_ledger_order FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE RESTRICT,
    CONSTRAINT fk_quota_ledger_refund FOREIGN KEY (refund_id) REFERENCES refunds (id) ON DELETE RESTRICT,
    INDEX ix_quota_ledger_user_type_created (user_id, quota_type, created_at),
    INDEX ix_quota_ledger_order_id (order_id),
    INDEX ix_quota_ledger_refund_id (refund_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE membership_grants (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    order_id BIGINT UNSIGNED NOT NULL,
    product_id INT NOT NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    refund_id BIGINT UNSIGNED NULL,
    revoked_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT ck_membership_grants_valid_period CHECK (ends_at > starts_at),
    CONSTRAINT uk_membership_grants_order_id UNIQUE (order_id),
    CONSTRAINT fk_membership_grants_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_membership_grants_order FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE RESTRICT,
    CONSTRAINT fk_membership_grants_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE RESTRICT,
    CONSTRAINT fk_membership_grants_refund FOREIGN KEY (refund_id) REFERENCES refunds (id) ON DELETE RESTRICT,
    INDEX ix_membership_grants_user_status_end (user_id, status, ends_at),
    INDEX ix_membership_grants_refund_id (refund_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
