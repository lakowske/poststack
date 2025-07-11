-- Migration: Initial schema creation
-- Author: poststack
-- Date: 2025-01-07
-- Description: Create poststack schema and core tables

-- Create schema
CREATE SCHEMA IF NOT EXISTS poststack;

-- Create system_info table
CREATE TABLE poststack.system_info (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create services table
CREATE TABLE poststack.services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'stopped',
    config JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create containers table
CREATE TABLE poststack.containers (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL,
    container_id VARCHAR(255) UNIQUE,
    image VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    config JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_containers_service_id FOREIGN KEY (service_id) 
        REFERENCES poststack.services(id) ON DELETE CASCADE
);

