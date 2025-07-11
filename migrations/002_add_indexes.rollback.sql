-- Rollback: Remove performance indexes
-- Author: poststack
-- Date: 2025-01-07
-- Description: Drop all performance indexes

-- Drop system info indexes
DROP INDEX IF EXISTS poststack.idx_system_info_key;

-- Drop services indexes
DROP INDEX IF EXISTS poststack.idx_services_type;
DROP INDEX IF EXISTS poststack.idx_services_status;
DROP INDEX IF EXISTS poststack.idx_services_name;

-- Drop containers indexes
DROP INDEX IF EXISTS poststack.idx_containers_service_id;
DROP INDEX IF EXISTS poststack.idx_containers_status;
DROP INDEX IF EXISTS poststack.idx_containers_container_id;

