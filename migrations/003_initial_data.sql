-- Migration: Insert initial system data
-- Author: poststack
-- Date: 2025-01-07
-- Description: Insert initial system information and default service configurations

-- Insert system information
INSERT INTO poststack.system_info (key, value) VALUES
    ('schema_version', '1.0.0'),
    ('created_by', 'poststack_migration'),
    ('poststack_version', '0.1.0'),
    ('database_initialized', 'true');

-- Insert default service configurations
INSERT INTO poststack.services (name, type, status, config) VALUES
    ('postgresql', 'database', 'configured', '{"image": "poststack/postgres", "port": 5432}'),
    ('apache', 'web', 'configured', '{"image": "poststack/apache", "ports": [80, 443]}'),
    ('dovecot', 'mail', 'configured', '{"image": "poststack/dovecot", "ports": [143, 993, 110, 995]}'),
    ('bind', 'dns', 'configured', '{"image": "poststack/bind", "ports": [53]}'),
    ('certbot', 'certificate', 'configured', '{"image": "poststack/certbot", "schedule": "0 12 * * *"}');