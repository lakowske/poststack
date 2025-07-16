-- Rollback: Add Certificate Management (Unified Project Scenario)
-- This removes all certificate management tables and functions

DROP TRIGGER IF EXISTS trigger_certificate_notifications ON unified.certificates;
DROP FUNCTION IF EXISTS unified.notify_certificate_change();

DROP TABLE IF EXISTS unified.service_certificates;
DROP TABLE IF EXISTS unified.certificate_renewals;
DROP TABLE IF EXISTS unified.certificate_notifications;
DROP TABLE IF EXISTS unified.certificate_files;
DROP TABLE IF EXISTS unified.certificates;