Poststack

# Overview

Poststack coordinates a set of servers (e.g. postgres, apache, dovecot/postfix, bind, nginx, etc...). It uses Python and Postgres to manage configuration
such as users, passwords and other configuration.

# Getting Started

Poststack features a powerful CLI bootstrap tool that handles container image building, database setup, and schema management. All operations are logged for transparency and debugging.

## Quick Start

1. **Install Prerequisites**
   - Python 3.9+
   - Podman (or Docker)
   - PostgreSQL client tools (optional)

2. **Run the Bootstrap CLI**
   ```bash
   # Full setup process (recommended for first-time setup)
   python poststack-bootstrap.py setup --build-images --url "postgresql://user:password@localhost:5432/poststack"
   
   # Or run individual commands
   python poststack-bootstrap.py build-images
   python poststack-bootstrap.py verify-db --url "postgresql://user:password@localhost:5432/poststack"
   python poststack-bootstrap.py init-schema --url "postgresql://user:password@localhost:5432/poststack"
   ```

3. **Monitor Progress**
   - All operations log progress to stdout/stderr
   - Detailed logs are written to the `logs/` directory
   - Container builds logged to `logs/containers/`
   - Database operations logged to `logs/database/`

4. **Start the Server**
   ```bash
   # After bootstrap completes
   python poststack.py
   ```

5. **Configure Your Services**
   - Access the web interface at http://localhost:8000
   - Configure your domain and services
   - Enable the services you need (Apache, Mail, DNS, etc.)
   - All configuration is stored centrally in PostgreSQL

## Bootstrap CLI Commands

The bootstrap CLI provides individual commands for different operations:

### Image Building
```bash
# Build all container images
python poststack-bootstrap.py build-images

# Build images in parallel (faster)
python poststack-bootstrap.py build-images --parallel
```

### Database Operations
```bash
# Verify database connectivity
python poststack-bootstrap.py verify-db --url "postgresql://user:password@localhost:5432/poststack"

# Initialize empty database schema
python poststack-bootstrap.py init-schema --url "postgresql://user:password@localhost:5432/poststack"

# Update existing database schema
python poststack-bootstrap.py update-schema --url "postgresql://user:password@localhost:5432/poststack"
```

### Full Setup
```bash
# Complete bootstrap process
python poststack-bootstrap.py setup --build-images --url "postgresql://user:password@localhost:5432/poststack"
```

## Environment Variables

For automated deployments, you can use environment variables instead of command-line arguments:

```bash
# Set database URL
export DATABASE_URL="postgresql://user:password@localhost:5432/poststack"

# Run bootstrap commands (DATABASE_URL will be used automatically)
python poststack-bootstrap.py build-images
python poststack-bootstrap.py verify-db
python poststack-bootstrap.py init-schema

# Or run full setup
python poststack-bootstrap.py setup --build-images

# Start the server
python poststack.py
```

## Next Steps

After bootstrap completes successfully:

1. **Start the main server**: `python poststack.py`
2. **Access the web interface**: http://localhost:8000
3. **Configure your domain**: Set your primary domain and Let's Encrypt email
4. **Enable services**: Turn on the services you need (Apache, Mail, DNS, etc.)
5. **Deploy containers**: Use the generated configurations to deploy your services

## Logging and Debugging

All bootstrap operations create detailed logs:

- **Console Output**: Progress and summary information
- **Main Logs**: `logs/bootstrap_YYYYMMDD_HHMMSS.log`
- **Container Builds**: `logs/containers/[image]_build_YYYYMMDD_HHMMSS.log`
- **Database Operations**: `logs/database/schema_[operation]_YYYYMMDD_HHMMSS.log`

Use `--verbose` flag for more detailed console output.

For detailed configuration options, see [Configuration Documentation](docs/configuration.md).
For architectural details, see [Core Architecture](docs/core-container-architecture.md).
For bootstrap implementation details, see [Bootstrap CLI Documentation](docs/bootstrap.md).
