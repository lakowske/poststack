-- Description: Add performance indexes to basic schema
-- This migration adds indexes for better query performance

CREATE INDEX idx_users_username ON test_basic.users(username);
CREATE INDEX idx_users_email ON test_basic.users(email);
CREATE INDEX idx_users_created_at ON test_basic.users(created_at);

CREATE INDEX idx_sessions_user_id ON test_basic.sessions(user_id);
CREATE INDEX idx_sessions_token ON test_basic.sessions(token);
CREATE INDEX idx_sessions_expires_at ON test_basic.sessions(expires_at);