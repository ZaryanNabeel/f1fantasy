-- Database accounts. Replace both CHANGE_ME_* placeholders before running.
-- Load AFTER schema.sql and seed_2026.sql.

CREATE USER IF NOT EXISTS 'f1app'@'%'  IDENTIFIED BY 'CHANGE_ME_APP';
GRANT SELECT, INSERT, UPDATE, DELETE ON f1fantasy.* TO 'f1app'@'%';

CREATE USER IF NOT EXISTS 'grader'@'%' IDENTIFIED BY 'CHANGE_ME_GRADER';
GRANT SELECT ON f1fantasy.* TO 'grader'@'%';   -- read-only account for the evaluation script

FLUSH PRIVILEGES;

-- Verify the grader is read-only (expect only: GRANT USAGE ... / GRANT SELECT ON `f1fantasy`.*):
--   SHOW GRANTS FOR 'grader'@'%';
-- Then, logged in as grader, this must fail with "INSERT command denied":
--   INSERT INTO f1fantasy.sync_log (season, summary) VALUES (2026, 'should fail');
