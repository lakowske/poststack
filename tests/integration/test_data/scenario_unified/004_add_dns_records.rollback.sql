-- Rollback: Add DNS Records (Unified Project Scenario)
-- This removes all DNS records management tables and functions

DROP TRIGGER IF EXISTS dns_record_update_trigger ON unified.dns_records;
DROP FUNCTION IF EXISTS unified.update_dns_zone_serial();

DROP TABLE IF EXISTS unified.dns_records;
DROP TABLE IF EXISTS unified.dns_zones;