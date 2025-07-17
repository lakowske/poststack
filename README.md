# Poststack

## Overview

Poststack is a focused PostgreSQL database and schema migration management tool. It provides a streamlined CLI for database operations and SQL-based schema migrations with full rollback support.

**Key Features:**
- **Database Operations**: Connection testing, schema validation, and database management  
- **Schema Migrations**: SQL-based migrations with full rollback support
- **Migration Diagnostics**: Comprehensive migration system integrity checks
- **External PostgreSQL Support**: Works with any PostgreSQL instance (local, containerized, or cloud)
- **Docker Compose Integration**: Designed to work alongside Docker Compose for orchestration

## Philosophy

Poststack follows the principle: **build what makes you unique (database expertise), adopt what makes you efficient (Docker Compose for orchestration)**. 

Previously a complex orchestration system, Poststack has been simplified to focus solely on database operations while delegating container orchestration to proven tools like Docker Compose.

## Getting Started

### Prerequisites

- Python 3.9+
- PostgreSQL (local installation, Docker container, or cloud instance)
- Optional: `psycopg2-binary` for database connectivity

### Installation

```bash
pip install poststack
```

### Basic Usage

1. **Configure Database Connection**
   
   Set environment variables:
   ```bash
   export DATABASE_URL="postgresql://user:password@localhost:5432/mydb"
   ```
   
   Or use individual PostgreSQL environment variables:
   ```bash
   export POSTGRES_HOST=localhost
   export POSTGRES_PORT=5432
   export POSTGRES_DB=mydb
   export POSTGRES_USER=myuser
   export POSTGRES_PASSWORD=mypassword
   ```

2. **Test Database Connection**
   ```bash
   poststack db test-connection
   ```

3. **Initialize Migration System**
   ```bash
   poststack db migrate --yes
   ```

4. **Run Project Migrations**
   ```bash
   mkdir migrations
   # Add your migration files (001_initial.sql, 002_add_users.sql, etc.)
   poststack db migrate-project
   ```

## CLI Commands

### Database Operations (`poststack db`)

- `test-connection` - Test database connectivity
- `migrate` - Run core poststack migrations  
- `migrate-project` - Run project-specific migrations
- `migration-status` - Show current migration status
- `rollback <version>` - Rollback to specific migration version
- `shell` - Open PostgreSQL shell (psql)
- `diagnose` - Run comprehensive migration diagnostics
- `validate` - Validate migration system integrity

### Volume Operations (`poststack volumes`)

- `list` - List Docker/Podman volumes
- `info <volume>` - Show volume details
- `prune` - Remove unused volumes

### Shell Completion (`poststack completion`)

- `install` - Install shell completion for current or specified shell
- `show` - Display completion script for manual installation

## Migration Files

Poststack uses SQL-based migration files with the following structure:

```
migrations/
├── 001_initial_schema.sql
├── 001_initial_schema.rollback.sql
├── 002_add_users.sql
├── 002_add_users.rollback.sql
└── ...
```

### Migration File Format

**Forward Migration** (`001_initial_schema.sql`):
```sql
-- Create initial schema
CREATE SCHEMA IF NOT EXISTS myapp;

CREATE TABLE myapp.users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Rollback Migration** (`001_initial_schema.rollback.sql`):
```sql
-- Rollback initial schema
DROP TABLE IF EXISTS myapp.users;
DROP SCHEMA IF EXISTS myapp CASCADE;
```

## Shell Completion

Poststack supports tab-completion for bash, zsh, and fish shells:

```bash
# Install completion for your current shell (auto-detected)
poststack completion install

# Install for specific shell
poststack completion install --shell bash

# Show completion script for manual installation
poststack completion show --shell bash
```

For more details, see [docs/shell-completion.md](docs/shell-completion.md).

## Configuration

Poststack uses environment variables for configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Full PostgreSQL connection URL | None |
| `POSTGRES_HOST` | PostgreSQL hostname | localhost |
| `POSTGRES_PORT` | PostgreSQL port | 5432 |
| `POSTGRES_DB` | Database name | postgres |
| `POSTGRES_USER` | Database user | postgres |
| `POSTGRES_PASSWORD` | Database password | (empty) |
| `POSTSTACK_LOG_LEVEL` | Logging level | INFO |
| `POSTSTACK_MIGRATIONS_PATH` | Migration files directory | ./migrations |

## Docker Compose Integration

Poststack works seamlessly with Docker Compose for container orchestration:

```yaml
# docker-compose.yml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myuser
      POSTGRES_PASSWORD: mypassword
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myuser -d myapp"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Your application services here
  app:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://myuser:mypassword@postgres:5432/myapp

volumes:
  postgres_data:
```

## Migration Diagnostics

Poststack includes comprehensive migration diagnostics:

```bash
# Check migration system health
poststack db diagnose

# Validate migration integrity
poststack db validate

# Show detailed migration status
poststack db migration-status --verbose
```

## Error Recovery

If migrations fail or become inconsistent:

```bash
# Diagnose issues
poststack db diagnose

# Attempt automatic repair
poststack db repair

# Manual recovery (advanced)
poststack db recover --from-version 005
```

## Development

For development and testing:

```bash
# Clone repository
git clone https://github.com/lakowske/poststack.git
cd poststack

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .
ruff format .
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/lakowske/poststack/issues)
- **Documentation**: [GitHub Wiki](https://github.com/lakowske/poststack/wiki)
- **Discussions**: [GitHub Discussions](https://github.com/lakowske/poststack/discussions)