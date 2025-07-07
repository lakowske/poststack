-- Rollback: Remove initial system data
-- Author: poststack
-- Date: 2025-01-07
-- Description: Remove initial system information and default service configurations

-- Remove default services
DELETE FROM poststack.services 
WHERE name IN ('postgresql', 'apache', 'dovecot', 'bind', 'certbot');

-- Remove system information
DELETE FROM poststack.system_info 
WHERE key IN ('schema_version', 'created_by', 'poststack_version', 'database_initialized');