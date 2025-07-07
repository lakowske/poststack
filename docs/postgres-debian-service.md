# PostgreSQL Database Service Specification

## Purpose

Define the requirements and implementation for a PostgreSQL database service running in a Debian-based container with persistent storage.

## Scope

- PostgreSQL database server
- Data persistence using volumes
- Database initialization
- Backup and restore capabilities
- Health monitoring
- Connection pooling

## Requirements

### Functional Requirements

1. Run PostgreSQL server with persistent data storage
2. Support database initialization with custom schemas
3. Enable SSL/TLS connections using shared certificates
4. Provide backup and restore mechanisms
5. Support connection pooling for performance

### Non-Functional Requirements

1. Data persistence across container restarts
2. Minimal container size while maintaining functionality
3. Secure default configuration
4. Performance optimization for container environment
5. Compatibility with Poststack configuration system

## Design Decisions

### Data Storage Layout

```
/data/postgres/
├── pgdata/                      # PostgreSQL data directory
│   ├── base/                   # Database files
│   ├── global/                 # Cluster-wide tables
│   ├── pg_wal/                 # Write-ahead logs
│   └── postgresql.conf         # Main configuration
├── backups/                    # Backup storage
│   └── daily/                  # Daily backups
└── ssl/                        # SSL certificates (symlinked)
    ├── server.crt -> /data/certificates/{domain}/fullchain.pem
    └── server.key -> /data/certificates/{domain}/privkey.pem
```

### User Permissions Model

- PostgreSQL runs as postgres user (UID 999)
- Data directory owned by postgres:postgres
- SSL certificates accessed via certgroup membership

## Implementation

### Containerfile Structure

```dockerfile
FROM base-debian:latest

# PostgreSQL version
ENV PG_VERSION=15
ENV PGDATA=/data/postgres/pgdata

# Install PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-${PG_VERSION} \
    postgresql-client-${PG_VERSION} \
    postgresql-contrib-${PG_VERSION} \
    pgbackrest \
    && rm -rf /var/lib/apt/lists/*

# Add postgres user to certgroup for SSL certificate access
RUN usermod -a -G certgroup postgres

# Create data directories
RUN mkdir -p /data/postgres/pgdata /data/postgres/backups/daily /data/postgres/ssl && \
    chown -R postgres:postgres /data/postgres

# Copy configuration templates
COPY config/postgresql.conf.template /etc/postgresql/
COPY config/pg_hba.conf.template /etc/postgresql/

# Copy scripts
COPY scripts/entrypoint.sh /
COPY scripts/init-db.sh /usr/local/bin/
COPY scripts/backup.sh /usr/local/bin/
COPY scripts/health-check.sh /usr/local/bin/
RUN chmod +x /entrypoint.sh /usr/local/bin/*.sh

# PostgreSQL port
EXPOSE 5432

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD /usr/local/bin/health-check.sh

USER postgres
ENTRYPOINT ["/entrypoint.sh"]
CMD ["postgres"]
```

### Entrypoint Script

```bash
#!/bin/bash
set -e

# Configuration
export PGDATA=${PGDATA:-/data/postgres/pgdata}
export POSTGRES_DB=${POSTGRES_DB:-poststack}
export POSTGRES_USER=${POSTGRES_USER:-poststack}

# Initialize database if needed
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL database..."
    /usr/local/bin/init-db.sh
fi

# Setup SSL if certificates exist
if [ -f "/data/certificates/${DOMAIN}/fullchain.pem" ]; then
    echo "Configuring SSL..."
    ln -sf "/data/certificates/${DOMAIN}/fullchain.pem" /data/postgres/ssl/server.crt
    ln -sf "/data/certificates/${DOMAIN}/privkey.pem" /data/postgres/ssl/server.key
    chmod 600 /data/postgres/ssl/server.key
    
    # Enable SSL in postgresql.conf
    echo "ssl = on" >> $PGDATA/postgresql.conf
    echo "ssl_cert_file = '/data/postgres/ssl/server.crt'" >> $PGDATA/postgresql.conf
    echo "ssl_key_file = '/data/postgres/ssl/server.key'" >> $PGDATA/postgresql.conf
fi

# Apply custom configuration
if [ -f "/etc/postgresql/postgresql.conf.template" ]; then
    envsubst < /etc/postgresql/postgresql.conf.template > $PGDATA/postgresql.conf
fi

if [ -f "/etc/postgresql/pg_hba.conf.template" ]; then
    envsubst < /etc/postgresql/pg_hba.conf.template > $PGDATA/pg_hba.conf
fi

# Start PostgreSQL
exec postgres
```

### Database Initialization Script

```bash
#!/bin/bash
# init-db.sh

set -e

echo "Creating initial PostgreSQL cluster..."

# Initialize the database cluster
initdb --encoding=UTF8 --locale=C --auth-local=trust --auth-host=scram-sha-256

# Start temporary PostgreSQL instance
pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w start

# Create database and user
psql -v ON_ERROR_STOP=1 --username postgres <<-EOSQL
    CREATE USER ${POSTGRES_USER} WITH ENCRYPTED PASSWORD '${POSTGRES_PASSWORD}';
    CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};
    GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};
    
    -- Enable required extensions
    \c ${POSTGRES_DB}
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";
EOSQL

# Configure authentication
cat > "$PGDATA/pg_hba.conf" <<EOF
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
host    all             all             0.0.0.0/0               scram-sha-256
hostssl all             all             0.0.0.0/0               scram-sha-256
EOF

# Stop temporary instance
pg_ctl -D "$PGDATA" -m fast -w stop

echo "PostgreSQL initialization complete"
```

### Backup Script

```bash
#!/bin/bash
# backup.sh

set -e

BACKUP_DIR="/data/postgres/backups/daily"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/poststack_${TIMESTAMP}.sql.gz"

echo "Starting PostgreSQL backup..."

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

# Perform backup
pg_dump -h localhost -U ${POSTGRES_USER} ${POSTGRES_DB} | gzip > "${BACKUP_FILE}"

# Keep only last 7 days of backups
find "${BACKUP_DIR}" -name "poststack_*.sql.gz" -mtime +7 -delete

echo "Backup completed: ${BACKUP_FILE}"
```

### Health Check Script

```bash
#!/bin/bash
# health-check.sh

pg_isready -h localhost -p 5432 -U ${POSTGRES_USER} -d ${POSTGRES_DB}
```

### Configuration Templates

#### postgresql.conf.template

```
# PostgreSQL configuration for Poststack

# Connection settings
listen_addresses = '*'
port = 5432
max_connections = 100
superuser_reserved_connections = 3

# Memory settings
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB

# WAL settings
wal_level = replica
max_wal_size = 1GB
min_wal_size = 80MB

# Query tuning
random_page_cost = 1.1
effective_io_concurrency = 200

# Logging
log_destination = 'stderr'
logging_collector = on
log_directory = 'pg_log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 100MB
log_line_prefix = '%t [%p] %u@%d '
log_statement = 'mod'

# Performance monitoring
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all

# Locale settings
lc_messages = 'C'
lc_monetary = 'C'
lc_numeric = 'C'
lc_time = 'C'
```

## Environment Variables

### Required Variables

- `POSTGRES_PASSWORD`: Password for the PostgreSQL user
- `DOMAIN`: Domain name (for SSL certificate lookup)

### Optional Variables

- `POSTGRES_DB`: Database name (default: poststack)
- `POSTGRES_USER`: Database user (default: poststack)
- `POSTGRES_MAX_CONNECTIONS`: Maximum connections (default: 100)
- `POSTGRES_SHARED_BUFFERS`: Shared buffer size (default: 256MB)
- `BACKUP_SCHEDULE`: Cron schedule for backups (default: "0 2 * * *")

## Volume Mounts

```bash
# Create persistent volume
podman volume create postgres-data

# Run PostgreSQL container
podman run -d \
    --name poststack-postgres \
    -v postgres-data:/data/postgres \
    -v certs:/data/certificates:ro \
    -e POSTGRES_PASSWORD=secret \
    -e DOMAIN=example.com \
    -p 5432:5432 \
    postgres-debian:latest
```

## Integration with Poststack

### Schema Management

```bash
# Run schema migrations using poststack CLI
python -m poststack.cli database create-schema
python -m poststack.cli database migrate
```

### Connection String

```
postgresql://poststack:password@localhost:5432/poststack?sslmode=require
```

## Backup and Restore

### Manual Backup

```bash
podman exec poststack-postgres /usr/local/bin/backup.sh
```

### Restore from Backup

```bash
# Stop the container
podman stop poststack-postgres

# Copy backup file
podman cp backup.sql.gz poststack-postgres:/tmp/

# Start container and restore
podman start poststack-postgres
podman exec poststack-postgres bash -c "gunzip < /tmp/backup.sql.gz | psql -U poststack poststack"
```

### Automated Backups

Add a cron job or systemd timer:

```bash
# /etc/systemd/system/poststack-postgres-backup.service
[Unit]
Description=Poststack PostgreSQL Backup
Requires=poststack-postgres.service

[Service]
Type=oneshot
ExecStart=/usr/bin/podman exec poststack-postgres /usr/local/bin/backup.sh

# /etc/systemd/system/poststack-postgres-backup.timer
[Unit]
Description=Daily Poststack PostgreSQL Backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

## Security Considerations

### Database Security

- Use strong passwords generated by the Poststack system
- Enable SSL/TLS for all connections
- Restrict network access via firewall rules
- Regular security updates via container rebuilds

### Container Security

- Run as non-root postgres user
- Minimal attack surface with slim base image
- Read-only root filesystem (except data volumes)
- No unnecessary packages or services

### Data Protection

- Encrypted connections using shared certificates
- Automated backups with retention policy
- Volume snapshots for disaster recovery
- Regular security audits

## Monitoring

### Key Metrics

- Connection count and pool usage
- Query performance (via pg_stat_statements)
- Disk usage and I/O statistics
- Replication lag (if applicable)
- Backup success/failure

### Integration Points

```bash
# Prometheus metrics endpoint
podman exec poststack-postgres \
    psql -U poststack -d poststack -c \
    "SELECT * FROM pg_stat_database WHERE datname = 'poststack'"
```

## Testing Procedures

### Container Build Test

```bash
podman build -t postgres-debian:test -f Containerfile.postgres .
```

### Initialization Test

```bash
# Run with temporary volume
podman run --rm \
    -v postgres-test:/data/postgres \
    -e POSTGRES_PASSWORD=testpass \
    postgres-debian:test
```

### SSL Connection Test

```bash
# With certificates
podman run -d \
    --name postgres-ssl-test \
    -v postgres-test:/data/postgres \
    -v certs:/data/certificates:ro \
    -e POSTGRES_PASSWORD=testpass \
    -e DOMAIN=test.example.com \
    postgres-debian:test

# Test SSL connection
psql "postgresql://poststack:testpass@localhost:5432/poststack?sslmode=require"
```

## Future Enhancements

1. **High Availability**
   - Streaming replication setup
   - Automatic failover with Patroni
   - Read replica support

2. **Performance**
   - Connection pooling with PgBouncer
   - Query optimization advisor
   - Automatic vacuum tuning

3. **Management**
   - Web-based administration UI
   - Automated performance reports
   - Database migration tools

4. **Backup Improvements**
   - Point-in-time recovery
   - Encrypted backups
   - Cloud storage integration