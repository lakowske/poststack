-- Description: Create User Table (Unified Project Scenario)
-- This replicates the unified project's user table migration

CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE unified.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    domain VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    system_uid INTEGER DEFAULT 5000,
    system_gid INTEGER DEFAULT 5000,
    home_directory VARCHAR(500),
    mailbox_format VARCHAR(20) DEFAULT 'maildir',
    is_active BOOLEAN DEFAULT true,
    is_locked BOOLEAN DEFAULT false,
    email_verified BOOLEAN DEFAULT false,
    email_verification_token VARCHAR(255) NULL,
    email_verification_expires_at TIMESTAMP NULL,
    password_reset_token VARCHAR(255) NULL,
    password_reset_expires_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL,
    failed_login_attempts INTEGER DEFAULT 0,
    last_failed_login_at TIMESTAMP NULL,
    CONSTRAINT domain_matches_email CHECK (email LIKE '%@' || domain)
);

CREATE TABLE unified.user_passwords (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES unified.users(id) ON DELETE CASCADE,
    service VARCHAR(50) NOT NULL,
    password_hash TEXT NOT NULL,
    hash_scheme VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    must_change_on_next_login BOOLEAN DEFAULT false,
    UNIQUE(user_id, service)
);

CREATE TABLE unified.user_roles (
    user_id INTEGER REFERENCES unified.users(id) ON DELETE CASCADE,
    role_name VARCHAR(50) NOT NULL,
    service VARCHAR(50) NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER REFERENCES unified.users(id),
    PRIMARY KEY (user_id, service)
);

CREATE TABLE unified.audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES unified.users(id),
    service VARCHAR(50),
    action VARCHAR(100),
    resource VARCHAR(500),
    ip_address INET,
    user_agent TEXT,
    success BOOLEAN,
    error_message TEXT,
    additional_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);