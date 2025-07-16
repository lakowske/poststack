-- Description: Add DNS Records (Unified Project Scenario)
-- This adds DNS records management tables and functions

CREATE TABLE unified.dns_records (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(10) NOT NULL,
    value TEXT NOT NULL,
    ttl INTEGER DEFAULT 3600,
    priority INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE unified.dns_zones (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    serial_number BIGINT NOT NULL DEFAULT 2025071501,
    refresh_interval INTEGER DEFAULT 3600,
    retry_interval INTEGER DEFAULT 1800,
    expire_interval INTEGER DEFAULT 604800,
    minimum_ttl INTEGER DEFAULT 3600,
    primary_ns VARCHAR(255) NOT NULL,
    admin_email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE UNIQUE INDEX idx_dns_records_unique
ON unified.dns_records(domain, name, type)
WHERE is_active = TRUE;

CREATE INDEX idx_dns_records_domain ON unified.dns_records(domain);
CREATE INDEX idx_dns_records_type ON unified.dns_records(type);
CREATE INDEX idx_dns_records_name ON unified.dns_records(name);

CREATE OR REPLACE FUNCTION unified.update_dns_zone_serial()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE unified.dns_zones
    SET serial_number = EXTRACT(epoch FROM CURRENT_TIMESTAMP)::bigint,
        updated_at = CURRENT_TIMESTAMP
    WHERE domain = COALESCE(NEW.domain, OLD.domain);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER dns_record_update_trigger
    AFTER INSERT OR UPDATE OR DELETE ON unified.dns_records
    FOR EACH ROW
    EXECUTE FUNCTION unified.update_dns_zone_serial();

-- Insert some sample DNS records
INSERT INTO unified.dns_zones (domain, primary_ns, admin_email)
VALUES ('example.com', 'ns1.example.com', 'admin@example.com');

INSERT INTO unified.dns_records (domain, name, type, value, ttl, priority) VALUES
('example.com', '@', 'A', '192.168.1.100', 3600, NULL),
('example.com', 'mail', 'A', '192.168.1.100', 3600, NULL),
('example.com', '@', 'MX', 'mail.example.com', 3600, 10),
('example.com', '@', 'TXT', 'v=spf1 a mx include:_spf.google.com ~all', 3600, NULL),
('example.com', '_dmarc', 'TXT', 'v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com', 3600, NULL);