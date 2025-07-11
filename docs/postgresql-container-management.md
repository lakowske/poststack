# PostgreSQL Container Management Guide

## Overview

This guide covers poststack's PostgreSQL container management capabilities. Poststack provides a focused platform for managing PostgreSQL containers with schema migration support, allowing you to build applications that leverage a robust PostgreSQL foundation.

## Core Features

- **PostgreSQL Container Management**: Start, stop, and manage PostgreSQL containers
- **Schema Migration System**: SQL-based migrations with rollback support
- **Auto-detection**: Automatically detect and connect to running PostgreSQL containers
- **Configuration Management**: Centralized configuration in the database
- **Health Monitoring**: Built-in health checks and status monitoring

## Quick Start

### Installation

```bash
# Install poststack
pip install poststack

# Or install from source
git clone https://github.com/lakowske/poststack.git
cd poststack
pip install -e .
```

### Basic Usage

```bash
# Start PostgreSQL container
poststack database start

# Initialize schema
poststack database create-schema

# Check status
poststack database status

# Test connection
poststack database test-connection
```

## Container Management

### Starting PostgreSQL

```bash
# Start with default configuration
poststack database start

# Start with custom configuration
poststack database start --postgres-password mypassword

# Start with specific PostgreSQL version
poststack database start --postgres-version 15
```

### Managing Containers

```bash
# List running containers
poststack container list

# Stop PostgreSQL container
poststack database stop

# Check container status
poststack database status

# View container logs
poststack database logs

# Follow logs in real-time
poststack database logs --follow
```

### Container Configuration

Poststack creates PostgreSQL containers with:

- **Name**: `poststack-postgres`
- **Image**: `postgres:15` (or specified version)
- **Port**: `5432` (mapped to host)
- **Data Volume**: `poststack-postgres-data`
- **User**: `poststack`
- **Database**: `poststack`

## Database Operations

### Schema Management

```bash
# Initialize database schema
poststack database create-schema

# Apply pending migrations
poststack database migrate

# Check migration status
poststack database migration-status

# Rollback to specific version
poststack database rollback 001 --confirm

# Drop and recreate schema
poststack database drop-schema --confirm
poststack database create-schema
```

### Connection Management

```bash
# Test database connection
poststack database test-connection

# Show database connection details
poststack config-show

# Connect with psql
psql $(poststack config-show | grep "Database URL" | cut -d' ' -f3)
```

## Configuration

### Environment Variables

```bash
# Database configuration
export POSTSTACK_DATABASE_URL="postgresql://user:pass@host:5432/poststack"

# Container configuration
export POSTSTACK_CONTAINER_RUNTIME="podman"  # or "docker"

# Logging
export POSTSTACK_LOG_LEVEL="INFO"
export POSTSTACK_LOG_DIR="logs"
```

### Configuration File

Create `poststack.yaml`:

```yaml
database_url: "postgresql://poststack:password@localhost:5432/poststack"
container_runtime: "podman"
log_level: "INFO"
log_dir: "logs"
migrations_path: "./migrations"
```

Use with:

```bash
poststack --config-file poststack.yaml database start
```

## Auto-detection

Poststack can automatically detect running PostgreSQL containers:

```bash
# Auto-detect and connect
poststack database test-connection

# Show detected configuration
poststack config-show
```

Auto-detection looks for:
- Containers named `poststack-postgres*`
- Containers running PostgreSQL images
- Standard PostgreSQL ports (5432, 5433)

## Migration System

### Creating Migrations

Create migration files in `./migrations/`:

```sql
-- 001_create_users.sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```sql
-- 001_create_users.rollback.sql
DROP TABLE IF EXISTS users;
```

### Applying Migrations

```bash
# Apply all pending migrations
poststack database migrate

# Apply migrations to specific version
poststack database migrate --target 003

# Check what migrations will be applied
poststack database migration-status
```

### Rolling Back

```bash
# Rollback to specific version
poststack database rollback 001 --confirm

# Drop all and recreate
poststack database drop-schema --confirm
poststack database create-schema
```

## Data Management

### Backup and Restore

```bash
# Create backup
pg_dump $(poststack config-show | grep "Database URL" | cut -d' ' -f3) > backup.sql

# Restore from backup
psql $(poststack config-show | grep "Database URL" | cut -d' ' -f3) < backup.sql
```

### Volume Management

```bash
# List volumes
podman volume ls | grep poststack

# Backup volume
podman run --rm -v poststack-postgres-data:/data -v $(pwd):/backup alpine \
    tar czf /backup/postgres-backup.tar.gz -C /data .

# Restore volume
podman run --rm -v poststack-postgres-data:/data -v $(pwd):/backup alpine \
    tar xzf /backup/postgres-backup.tar.gz -C /data
```

## Monitoring and Health Checks

### Health Monitoring

```bash
# Check container health
poststack database status

# Test connection
poststack database test-connection

# View detailed status
poststack database status --verbose
```

### Logs and Debugging

```bash
# View container logs
poststack database logs

# Follow logs
poststack database logs --follow

# Debug connection issues
poststack database test-connection --verbose
```

## Integration with Applications

### Connection String

Get the connection string for your applications:

```bash
# Show connection details
poststack config-show

# Get just the URL
poststack config-show | grep "Database URL" | cut -d' ' -f3
```

### Environment Variables for Apps

```bash
# Set environment variable for your app
export DATABASE_URL=$(poststack config-show | grep "Database URL" | cut -d' ' -f3)

# Run your application
python app.py
```

### Container Integration

```bash
# Run your app container with database connection
podman run -d \
    --name myapp \
    -e DATABASE_URL="$(poststack config-show | grep 'Database URL' | cut -d' ' -f3)" \
    -p 8000:8000 \
    myapp:latest
```

## Development Workflow

### Local Development

```bash
# Start development environment
poststack database start

# Initialize schema
poststack database create-schema

# Run your application
python app.py

# Make schema changes
# Edit migrations/002_add_feature.sql
# Edit migrations/002_add_feature.rollback.sql

# Apply changes
poststack database migrate
```

### Testing

```bash
# Create test database
poststack database start --postgres-password testpass

# Run tests
pytest tests/

# Clean up
poststack database stop
```

## Production Deployment

### Production Setup

```bash
# Production configuration
export POSTSTACK_DATABASE_URL="postgresql://user:securepass@dbhost:5432/prod"
export POSTSTACK_LOG_LEVEL="INFO"

# Start production PostgreSQL
poststack database start --postgres-password ${POSTGRES_PASSWORD}

# Initialize schema
poststack database create-schema

# Start your application
systemctl start myapp
```

### Systemd Integration

Create `/etc/systemd/system/poststack-postgres.service`:

```ini
[Unit]
Description=Poststack PostgreSQL Container
After=network.target

[Service]
Type=forking
ExecStart=/usr/local/bin/poststack database start
ExecStop=/usr/local/bin/poststack database stop
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl enable poststack-postgres
systemctl start poststack-postgres
```

## Advanced Configuration

### Custom PostgreSQL Configuration

Create custom PostgreSQL configuration:

```bash
# Create custom config directory
mkdir -p config/postgres

# Create postgresql.conf
cat > config/postgres/postgresql.conf << EOF
# Custom PostgreSQL configuration
max_connections = 200
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
EOF

# Mount custom config
poststack database start --config-dir ./config/postgres
```

### Performance Tuning

```bash
# Start with performance settings
poststack database start \
    --postgres-password mypassword \
    --postgres-args "-c shared_buffers=512MB -c max_connections=200"
```

### SSL Configuration

```bash
# Enable SSL
poststack database start \
    --postgres-password mypassword \
    --enable-ssl \
    --cert-path /path/to/certs
```

## Troubleshooting

### Common Issues

1. **Container won't start**
   ```bash
   # Check logs
   poststack database logs
   
   # Check if port is in use
   netstat -tulpn | grep :5432
   
   # Check container status
   podman ps -a | grep poststack
   ```

2. **Connection refused**
   ```bash
   # Check if PostgreSQL is running
   poststack database status
   
   # Test connection
   poststack database test-connection
   
   # Check firewall
   sudo ufw status
   ```

3. **Migration failures**
   ```bash
   # Check migration status
   poststack database migration-status
   
   # View migration logs
   poststack database logs | grep migration
   
   # Rollback and retry
   poststack database rollback 001 --confirm
   poststack database migrate
   ```

### Debug Commands

```bash
# Show all configuration
poststack config-show --verbose

# Test database connection with details
poststack database test-connection --verbose

# Show container details
podman inspect poststack-postgres

# Check volume contents
podman run --rm -v poststack-postgres-data:/data alpine ls -la /data
```

## Best Practices

### 1. Regular Backups

```bash
# Create daily backup script
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump $(poststack config-show | grep "Database URL" | cut -d' ' -f3) > backup_$DATE.sql
gzip backup_$DATE.sql

# Keep only last 7 days
find . -name "backup_*.sql.gz" -mtime +7 -delete
```

### 2. Monitoring

```bash
# Check database size
psql $(poststack config-show | grep "Database URL" | cut -d' ' -f3) \
    -c "SELECT pg_size_pretty(pg_database_size('poststack'));"

# Monitor connections
psql $(poststack config-show | grep "Database URL" | cut -d' ' -f3) \
    -c "SELECT count(*) FROM pg_stat_activity;"
```

### 3. Security

```bash
# Use strong passwords
export POSTGRES_PASSWORD=$(openssl rand -base64 32)

# Restrict network access
poststack database start --bind-address 127.0.0.1

# Use SSL in production
poststack database start --enable-ssl
```

### 4. Performance

```bash
# Tune for your workload
poststack database start \
    --postgres-args "-c shared_buffers=25% -c effective_cache_size=75%"

# Monitor slow queries
psql $(poststack config-show | grep "Database URL" | cut -d' ' -f3) \
    -c "SELECT query, calls, total_time, mean_time FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"
```

## Migration from Other Systems

### From Docker Compose

Replace your PostgreSQL service with poststack:

```yaml
# Before
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myuser
      POSTGRES_PASSWORD: mypass
    volumes:
      - postgres_data:/var/lib/postgresql/data

# After - let poststack manage PostgreSQL
services:
  app:
    build: .
    environment:
      DATABASE_URL: postgresql://poststack:password@localhost:5432/poststack
```

### From Kubernetes

Replace PostgreSQL deployment with poststack:

```yaml
# ConfigMap for database URL
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  DATABASE_URL: postgresql://poststack:password@postgres-service:5432/poststack
```

This guide provides comprehensive coverage of poststack's PostgreSQL container management capabilities, from basic usage to advanced production deployments.