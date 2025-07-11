# Poststack

## Overview

Poststack is a Python framework for managing PostgreSQL containers and database schema migrations. It provides a unified CLI for container management and SQL-based schema migration with full rollback support.

## Getting Started

Poststack features a powerful CLI that handles PostgreSQL container building, database setup, and schema management. All operations are logged for transparency and debugging.

### Quick Start

1. **Install Prerequisites**
   - Python 3.9+
   - Podman (or Docker)
   - PostgreSQL client tools (optional)

2. **Install Poststack**
   ```bash
   pip install poststack
   ```

3. **Build and Start PostgreSQL Container**
   ```bash
   # Build PostgreSQL container image
   poststack container build
   
   # Start PostgreSQL container
   poststack container start --postgres-port 5433
   ```

4. **Initialize Database Schema**
   ```bash
   # Initialize database schema
   poststack database create-schema --url "postgresql://poststack:poststack_dev@localhost:5433/poststack"
   
   # Run migrations
   poststack database migrate --url "postgresql://poststack:poststack_dev@localhost:5433/poststack"
   ```

5. **Monitor Progress**
   - All operations log progress to stdout/stderr
   - Detailed logs are written to the `logs/` directory
   - Container builds logged to `logs/containers/`
   - Database operations logged to `logs/database/`

## Core Features

### Container Management
- **PostgreSQL Container**: Purpose-built PostgreSQL container with health checks
- **Base Image**: Debian-based foundation with common tools
- **Lifecycle Management**: Start, stop, remove, status, and health monitoring
- **Auto-detection**: Automatically detects running PostgreSQL containers
- **Custom Naming**: Configure container names per project for isolation

### Schema Migration System
- **SQL-based**: Pure SQL migrations with full rollback support
- **Version Control**: Track applied migrations and schema versions
- **Rollback Support**: Roll back individual migrations or to specific versions
- **Validation**: Comprehensive schema validation and health checks
- **Locking**: Migration locks prevent concurrent schema changes

### CLI Commands

#### Container Commands
```bash
# Build container images
poststack container build [--image postgres|base-debian|all]

# Container lifecycle
poststack container start [--postgres-port PORT]
poststack container stop [--all]
poststack container remove [--force] <container_names>
poststack container status
poststack container health

# Management
poststack container list
poststack container clean
```

#### Database Commands
```bash
# Schema management
poststack database create-schema
poststack database show-schema
poststack database drop-schema

# Migration management
poststack database migrate [--target-version VERSION]
poststack database rollback [--target-version VERSION]
poststack database migration-status
poststack database verify-migrations
poststack database unlock-migrations

# Operations
poststack database test-connection
poststack database backup
```

#### Utility Commands
```bash
# Configuration
poststack config-show
poststack config-validate

# Logs
poststack logs list [--category main|container|database]
poststack logs clean [--days 7]
poststack logs size

# Version
poststack version
```

## Configuration

Poststack uses environment variables and configuration files for setup:

```bash
# Environment variables
export POSTSTACK_DATABASE_URL="postgresql://user:password@localhost:5432/poststack"
export POSTSTACK_LOG_LEVEL="INFO"
export POSTSTACK_CONTAINER_RUNTIME="podman"
export POSTSTACK_POSTGRES_CONTAINER_NAME="my-project-postgres"
export POSTSTACK_POSTGRES_HOST_PORT="5432"

# Or use configuration file
poststack --config-file config.yaml command

# Or use .env file in your project
echo "POSTSTACK_POSTGRES_CONTAINER_NAME=my-project-postgres" > .env
echo "POSTSTACK_POSTGRES_HOST_PORT=5434" >> .env
```

### Configuration Options

- **database_url**: PostgreSQL connection URL
- **log_level**: Logging level (DEBUG, INFO, WARNING, ERROR)
- **log_dir**: Directory for log files (default: logs)
- **container_runtime**: Container runtime (podman or docker)
- **postgres_container_name**: Name for PostgreSQL container (default: poststack-postgres)
- **postgres_host_port**: Host port for PostgreSQL container (default: 5432)
- **migrations_path**: Path to migration files (default: ./migrations)

## Container Customization

### Custom Container Names and Ports

Poststack allows you to customize PostgreSQL container names and host ports for project isolation:

```bash
# Set custom container name and port via environment variables
export POSTSTACK_POSTGRES_CONTAINER_NAME="my-project-postgres"
export POSTSTACK_POSTGRES_HOST_PORT="5434"

# Or use .env file in your project root
echo "POSTSTACK_POSTGRES_CONTAINER_NAME=unified-postgres" > .env
echo "POSTSTACK_POSTGRES_HOST_PORT=5434" >> .env

# Container operations will use the exact name and port you specify
poststack container start    # Creates "my-project-postgres" on port 5434
poststack container status   # Shows "my-project-postgres"
```

### Container Lifecycle Management

Complete container lifecycle management with proper cleanup:

```bash
# Start a container (uses configured name and port)
poststack container start

# Start with custom port override
poststack container start --postgres-port 5435

# Check status
poststack container status

# Stop containers
poststack container stop my-project-postgres

# Remove stopped containers
poststack container remove my-project-postgres

# Force remove running containers
poststack container remove --force my-project-postgres
```

### Multi-Project Support

Run multiple Poststack projects simultaneously with different container names and ports:

```bash
# Project A
cd project-a
echo "POSTSTACK_POSTGRES_CONTAINER_NAME=project-a-postgres" > .env
echo "POSTSTACK_POSTGRES_HOST_PORT=5433" >> .env
poststack container start

# Project B
cd ../project-b
echo "POSTSTACK_POSTGRES_CONTAINER_NAME=project-b-postgres" > .env
echo "POSTSTACK_POSTGRES_HOST_PORT=5434" >> .env
poststack container start

# Both projects now have isolated PostgreSQL containers on different ports
```

## Migration System

### Creating Migrations

Migrations are SQL files in the `migrations/` directory:

```sql
-- migrations/004_add_user_table.sql
CREATE TABLE poststack.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Rollback Files

Each migration should have a corresponding rollback file:

```sql
-- migrations/004_add_user_table.rollback.sql
DROP TABLE IF EXISTS poststack.users;
```

### Migration Commands

```bash
# Apply all pending migrations
poststack database migrate

# Apply migrations up to specific version
poststack database migrate --target-version 004

# Rollback to specific version
poststack database rollback --target-version 003

# Show migration status
poststack database migration-status
```

## Development

### Prerequisites

- Python 3.9+
- Poetry or pip
- Podman/Docker
- PostgreSQL (for testing)

### Setup

```bash
# Clone repository
git clone https://github.com/your-org/poststack.git
cd poststack

# Install dependencies
pip install -e .

# Build containers
poststack container build

# Run tests
pytest tests/
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=poststack

# Run specific test categories
pytest tests/test_database.py
pytest tests/test_schema.py
```

## Architecture

### Components

1. **CLI Layer**: Click-based command-line interface
2. **Container Management**: Podman/Docker container lifecycle
3. **Database Layer**: PostgreSQL connection and operations
4. **Schema Management**: SQL-based migration system
5. **Configuration**: Pydantic-based configuration management
6. **Logging**: Structured logging with file rotation

### Database Schema

Poststack uses these core tables:

- `system_info`: System metadata and configuration
- `services`: Service definitions and status
- `containers`: Container instance tracking
- `schema_migrations`: Migration history and status

## License

[License information]

## Contributing

[Contributing guidelines]

## Support

For support and questions:
- GitHub Issues: [Repository issues]
- Documentation: [Documentation URL]