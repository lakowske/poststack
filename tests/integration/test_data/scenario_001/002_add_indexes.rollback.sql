-- Rollback: Add performance indexes to basic schema
-- This removes the performance indexes

DROP INDEX IF EXISTS test_basic.idx_users_username;
DROP INDEX IF EXISTS test_basic.idx_users_email;
DROP INDEX IF EXISTS test_basic.idx_users_created_at;

DROP INDEX IF EXISTS test_basic.idx_sessions_user_id;
DROP INDEX IF EXISTS test_basic.idx_sessions_token;
DROP INDEX IF EXISTS test_basic.idx_sessions_expires_at;