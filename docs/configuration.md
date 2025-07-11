# Configuration

All poststack configuration is centrally managed in the PostgreSQL database. This provides a single source of truth for the PostgreSQL container and enables dynamic configuration updates.

## Database Schema

### Core Configuration Table (`system_info`)

```sql
CREATE TABLE poststack.system_info (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### Required Configuration Items

- `schema_version` - Current schema version
- `poststack_version` - Poststack version that created the schema
- `database_initialized` - Database initialization status
- `log_level` - Global logging verbosity (DEBUG, INFO, WARNING, ERROR)

### Container Management Tables

#### Containers (`containers`)

```sql
CREATE TABLE poststack.containers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    container_id VARCHAR(255) UNIQUE,
    image VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    config JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## Environment Variables

Poststack supports configuration through environment variables:

```bash
# Database Configuration
export POSTSTACK_DATABASE_URL="postgresql://user:password@localhost:5432/poststack"

# Logging Configuration
export POSTSTACK_LOG_LEVEL="INFO"
export POSTSTACK_LOG_DIR="logs"
export POSTSTACK_VERBOSE="false"

# Container Configuration
export POSTSTACK_CONTAINER_RUNTIME="podman"

# Migration Configuration
export POSTSTACK_MIGRATIONS_PATH="./migrations"

# Development Configuration
export POSTSTACK_DEBUG="false"
export POSTSTACK_TEST_MODE="false"
```

## Configuration File

Poststack supports YAML configuration files:

```yaml
# config.yaml
database_url: "postgresql://user:password@localhost:5432/poststack"
log_level: "INFO"
log_dir: "logs"
verbose: false
container_runtime: "podman"
migrations_path: "./migrations"
debug: false
test_mode: false
```

Use with:
```bash
poststack --config-file config.yaml [command]
```

## CLI Configuration

Configuration can be overridden via CLI options:

```bash
# Override database URL
poststack --database-url "postgresql://user:pass@host:5432/db" [command]

# Override log level
poststack --log-level DEBUG [command]

# Override log directory
poststack --log-dir /custom/logs [command]

# Enable verbose output
poststack --verbose [command]
```

## Configuration Priority

Configuration is loaded in this order (highest to lowest priority):

1. CLI arguments
2. Environment variables
3. Configuration file (if specified)
4. Default values

## Database Auto-Detection

Poststack can automatically detect running PostgreSQL containers:

```bash
# Auto-detect and connect to running PostgreSQL
poststack database test-connection
```

Auto-detection looks for:
- Containers with names matching `poststack-postgres*`
- Containers running PostgreSQL images
- Standard PostgreSQL ports (5432, 5433)

## Validation

Validate your configuration:

```bash
poststack config-validate
```

This checks:
- Database connectivity
- Required tables exist
- Schema version compatibility
- Log directory permissions

## Troubleshooting

### Database Connection Issues

```bash
# Test database connection
poststack database test-connection

# Check auto-detected database
poststack config-show
```

### Configuration Conflicts

```bash
# Show effective configuration
poststack config-show

# Show configuration sources
poststack --verbose config-show
```

### Log Configuration

```bash
# Check log directory
poststack logs list

# Clean old logs
poststack logs clean --days 7
```