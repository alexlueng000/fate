-- Add the nullable original body to an existing staging request table.
-- Backfill requires an explicitly retried hash-matching request; old bodies
-- cannot be reconstructed from hashes. Fresh installations already have it.
SET @fate_payload_ddl = IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'chat_turn_requests'
       AND COLUMN_NAME = 'request_payload') > 0,
    'SELECT 1',
    'ALTER TABLE chat_turn_requests ADD COLUMN request_payload JSON NULL AFTER payload_hash'
);
PREPARE fate_payload_statement FROM @fate_payload_ddl;
EXECUTE fate_payload_statement;
DEALLOCATE PREPARE fate_payload_statement;
-- Preserve ordering of different failed questions submitted within one second.
ALTER TABLE chat_turn_requests MODIFY COLUMN updated_at DATETIME(6) NOT NULL;
