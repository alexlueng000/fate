-- Stop staging generations before applying; restart all workers afterwards.
-- Do not invent IDs for legacy records. They remain readable with NULL source.
SET @fate_reading_baseline_ddl = IF(
 (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
  AND TABLE_NAME='consultation_requests' AND COLUMN_NAME='baseline_message_id') > 0,
 'SELECT 1', 'ALTER TABLE consultation_requests ADD COLUMN baseline_message_id INT NULL AFTER reply'
);
PREPARE fate_reading_baseline_stmt FROM @fate_reading_baseline_ddl;
EXECUTE fate_reading_baseline_stmt;
DEALLOCATE PREPARE fate_reading_baseline_stmt;
SET @fate_reading_message_ddl = IF(
 (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
  AND TABLE_NAME='consultation_requests' AND COLUMN_NAME='message_id') > 0,
 'SELECT 1', 'ALTER TABLE consultation_requests ADD COLUMN message_id INT NULL AFTER baseline_message_id'
);
PREPARE fate_reading_message_stmt FROM @fate_reading_message_ddl;
EXECUTE fate_reading_message_stmt;
DEALLOCATE PREPARE fate_reading_message_stmt;
