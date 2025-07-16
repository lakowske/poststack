-- Description: Create basic test schema
-- This is a basic migration for testing the migration system

CREATE SCHEMA IF NOT EXISTS test_basic;

CREATE TABLE test_basic.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE test_basic.sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES test_basic.users(id) ON DELETE CASCADE,
    token VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add some initial data
INSERT INTO test_basic.users (username, email) VALUES 
    ('testuser', 'test@example.com'),
    ('admin', 'admin@example.com');