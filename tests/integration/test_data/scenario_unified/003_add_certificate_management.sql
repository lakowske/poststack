-- Description: Add Certificate Management (Unified Project Scenario)
-- This adds certificate management tables and functions

CREATE TABLE unified.certificates (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    certificate_type VARCHAR(50) NOT NULL,
    subject_alt_names TEXT[],
    issuer VARCHAR(500),
    subject VARCHAR(500),
    not_before TIMESTAMP NOT NULL,
    not_after TIMESTAMP NOT NULL,
    certificate_path VARCHAR(500) NOT NULL,
    private_key_path VARCHAR(500) NOT NULL,
    chain_path VARCHAR(500),
    fullchain_path VARCHAR(500),
    is_active BOOLEAN DEFAULT true,
    auto_renew BOOLEAN DEFAULT true,
    renewal_attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(domain, certificate_type)
);

CREATE TABLE unified.certificate_files (
    id SERIAL PRIMARY KEY,
    certificate_id INTEGER REFERENCES unified.certificates(id) ON DELETE CASCADE,
    file_type VARCHAR(50) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    file_checksum VARCHAR(64) NOT NULL,
    file_permissions VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(certificate_id, file_type)
);

CREATE TABLE unified.certificate_notifications (
    id SERIAL PRIMARY KEY,
    certificate_id INTEGER REFERENCES unified.certificates(id) ON DELETE CASCADE,
    notification_type VARCHAR(50) NOT NULL,
    message TEXT,
    data JSONB,
    processed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE unified.certificate_renewals (
    id SERIAL PRIMARY KEY,
    certificate_id INTEGER REFERENCES unified.certificates(id) ON DELETE CASCADE,
    scheduled_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    renewal_method VARCHAR(50) NOT NULL,
    success BOOLEAN NULL,
    error_message TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE unified.service_certificates (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(100) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    certificate_type VARCHAR(50) NOT NULL,
    ssl_enabled BOOLEAN DEFAULT false,
    certificate_path VARCHAR(500),
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    UNIQUE(service_name, domain)
);

CREATE OR REPLACE FUNCTION unified.notify_certificate_change()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'certificate_change',
        json_build_object(
            'certificate_id', COALESCE(NEW.id, OLD.id),
            'domain', COALESCE(NEW.domain, OLD.domain),
            'operation', TG_OP,
            'timestamp', CURRENT_TIMESTAMP
        )::text
    );
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_certificate_notifications
    AFTER INSERT OR UPDATE OR DELETE ON unified.certificates
    FOR EACH ROW
    EXECUTE FUNCTION unified.notify_certificate_change();