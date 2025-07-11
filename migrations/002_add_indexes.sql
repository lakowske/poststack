-- Migration: Add performance indexes
-- Author: poststack
-- Date: 2025-01-07
-- Description: Add indexes for commonly queried columns

-- System info indexes
CREATE INDEX idx_system_info_key ON poststack.system_info(key);

-- Services indexes
CREATE INDEX idx_services_type ON poststack.services(type);
CREATE INDEX idx_services_status ON poststack.services(status);
CREATE INDEX idx_services_name ON poststack.services(name);

-- Containers indexes
CREATE INDEX idx_containers_service_id ON poststack.containers(service_id);
CREATE INDEX idx_containers_status ON poststack.containers(status);
CREATE INDEX idx_containers_container_id ON poststack.containers(container_id);

