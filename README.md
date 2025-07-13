# Poststack

## Overview

Poststack is a Python framework for managing PostgreSQL containers and database schema migrations with comprehensive multi-environment orchestration. It provides a unified CLI for environment management, container orchestration, and SQL-based schema migration with full rollback support.

**Key Features:**
- **Environment Management**: Multi-environment deployment (dev/staging/production) with automatic database provisioning
- **Variable Substitution**: Template-based configuration for Docker Compose and Podman Pod files  
- **PostgreSQL Integration**: Automatic database setup and configuration injection per environment
- **Standard Deployment Files**: Use familiar deployment formats with poststack's database management
- **Schema Migrations**: SQL-based migrations with full rollback support

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

3. **Initialize Your Project**
   ```bash
   # Interactive mode - prompts for configuration
   poststack init --all
   
   # Non-interactive mode - uses defaults
   poststack init --all --no-interactive
   
   # Custom configuration
   poststack init --all --project-name myapp --db-port 5435 --no-interactive
   ```
   
   The `init` command will:
   - Create `.poststack.yml` if it doesn't exist (with interactive prompts or defaults)
   - Copy PostgreSQL container configuration files to `containers/postgres/`
   - Create deployment template in `containers/postgres/postgres-pod.yaml`
   - Generate documentation in `containers/postgres/docs/`

4. **Review Generated Configuration** (.poststack.yml):
   ```yaml
   environment: dev  # Currently selected environment
   
   project:
     name: myproject
   
   environments:
     dev:
       postgres:
         database: myproject_dev
         port: 5433
         user: myproject_dev_user
         password: auto_generated
       deployment:
         pod: containers/app/app-pod.yaml
       variables:
         LOG_LEVEL: debug
         APP_PORT: "8080"
   ```

5. **Create Application Deployment File** (containers/app/app-pod.yaml):
   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: myproject-${POSTSTACK_ENVIRONMENT}
   spec:
     containers:
     - name: app
       image: myapp:latest
       env:
       - name: DATABASE_URL
         value: "${POSTSTACK_DATABASE_URL}"
       - name: LOG_LEVEL
         value: "${LOG_LEVEL}"
   ```

6. **Build and Deploy**
   ```bash
   # Build all images (base, postgres, project containers)
   poststack build
   
   # Start development environment (uses current environment from config)
   poststack env start
   
   # Check status
   poststack env status
   
   # Switch environments
   poststack env switch staging
   poststack env start
   ```

### Monitoring and Logs

All operations provide comprehensive logging:
- Operations log progress to stdout/stderr
- Detailed logs written to the `logs/` directory  
- Container builds logged to `logs/containers/`
- Database operations logged to `logs/database/`
- Environment operations include structured status reporting

## Core Features

### Project Initialization

The `poststack init` command helps you get started quickly:

- **Automatic Configuration**: Creates `.poststack.yml` with sensible defaults if it doesn't exist
- **Interactive Mode**: Prompts for project details (name, database settings, etc.)
- **Non-Interactive Mode**: Uses defaults or command-line flags for automation
- **Template Files**: Copies PostgreSQL configuration templates that you can customize
- **Documentation**: Generates helpful documentation about the configuration

#### Init Command Options

```bash
poststack init [OPTIONS]

Options:
  --postgres           Include PostgreSQL container files only
  --deploy             Include deployment files only  
  --all                Include all files (recommended)
  --force              Overwrite existing files
  --project-name TEXT  Project name (defaults to current directory)
  --description TEXT   Project description
  --env-name TEXT      Environment name (default: dev)
  --db-name TEXT       Database name (defaults to {project}__{env})
  --db-port INTEGER    Database port (default: 5433)
  --db-user TEXT       Database user (defaults to {project}_user)
  --no-interactive     Skip prompts, use defaults/flags
```

### Container Management
- **PostgreSQL Container**: Purpose-built PostgreSQL container with health checks
- **Base Image**: Debian-based foundation with common tools
- **Project-Level Containers**: Build and manage custom application containers with full lifecycle support
- **Lifecycle Management**: Start, stop, remove, status, and health monitoring for all containers
- **Auto-detection**: Automatically detects running PostgreSQL containers and project containers
- **Custom Naming**: Configure container names per project for isolation

### Environment Management (Recommended Approach)
- **Multi-Environment Support**: Define dev/staging/production environments in .poststack.yml
- **Database Isolation**: Automatic PostgreSQL provisioning with per-environment databases
- **Variable Substitution**: Template-based configuration with ${VAR} syntax for Docker Compose/Podman Pod files
- **Standard Deployment Files**: Use familiar Docker Compose and Podman Pod formats with variable injection
- **Init/Deploy Workflow**: Proper initialization (migrations, setup) before application deployment
- **Dry-Run Debugging**: Preview variable substitutions and validate configurations before deployment
- **Environment Status**: Comprehensive status reporting for databases and containers per environment

### Schema Migration System
- **SQL-based**: Pure SQL migrations with full rollback support
- **Version Control**: Track applied migrations and schema versions
- **Rollback Support**: Roll back individual migrations or to specific versions
- **Validation**: Comprehensive schema validation and health checks
- **Locking**: Migration locks prevent concurrent schema changes

### CLI Commands

#### Environment Management Commands (Recommended)
```bash
# Environment lifecycle
poststack env list                          # Show available environments
poststack env start <env>                   # Start environment (init + deployment)
poststack env stop <env>                    # Stop environment
poststack env restart <env>                 # Restart environment
poststack env status [env]                  # Show environment status

# Phase-specific operations
poststack env init <env>                    # Run only init phase
poststack env deploy <env>                  # Run only deploy phase (assumes init done)

# Debugging and inspection
poststack env dry-run <env>                 # Preview variable substitutions
poststack env config <env>                  # Show effective configuration
poststack env logs <env> [service]          # Show environment logs
```

#### Essential Commands
```bash
# Initialize a new project
poststack init --all                  # Interactive mode (creates .poststack.yml if needed)
poststack init --postgres             # Copy only PostgreSQL container files
poststack init --deploy               # Copy only deployment files
poststack init --all --no-interactive # Non-interactive with defaults
poststack init --all --project-name myapp --db-port 5435 --no-interactive

# Build all images (base, postgres, project containers)
poststack build [--no-cache]

# Environment management  
poststack env list                    # List environments (* = current)
poststack env start [environment]     # Start environment (default: current)
poststack env stop [environment]      # Stop environment
poststack env restart [environment]   # Restart environment
poststack env status [environment]    # Show environment status
poststack env switch <environment>    # Change current environment

# Database operations (environment-aware)
poststack db create-schema            # Create schema in current environment
poststack db migrate                  # Run migrations
poststack db test-connection          # Test database connection
poststack db show-schema              # Show current schema
poststack db backup                   # Backup database

# Configuration and utilities
poststack config-show                 # Display current configuration
poststack config-validate             # Validate configuration
poststack version                     # Show version information
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
- **project_containers_path**: Path to project container definitions (default: ./containers)
- **project_container_prefix**: Prefix for project container names (auto-detected from directory if empty)
- **project_container_network**: Network mode for project containers (default: bridge)
- **project_container_restart_policy**: Restart policy for project containers (default: unless-stopped)

## Environment-First Approach

Poststack is designed around environments as the primary way to manage your projects. Instead of managing individual containers and databases, you define environments in `.poststack.yml` and let poststack handle the rest.

### Multi-Project Support

Each project has its own `.poststack.yml` with isolated environments:

```bash
# Project A
cd project-a
# .poststack.yml defines dev environment with database project_a_dev on port 5433
poststack env start

# Project B  
cd ../project-b
# .poststack.yml defines dev environment with database project_b_dev on port 5434
poststack env start

# Both projects run isolated environments automatically
```

## Project-Level Custom Containers

Poststack supports project-level custom containers, allowing you to build and manage application-specific containers alongside the PostgreSQL database. This is ideal for web servers, application services, or any custom containers your project needs.

### Setting Up Custom Containers

1. **Create a containers directory** in your project root:
   ```bash
   mkdir containers
   ```

2. **Create container subdirectories** with Dockerfiles:
   ```bash
   # Example: Apache web server with PHP
   mkdir containers/apache
   cat > containers/apache/Dockerfile << 'EOF'
   FROM poststack/base-debian:latest
   
   # Install Apache and PHP
   RUN apt-get update && apt-get install -y \
       apache2 \
       php8.2 \
       php8.2-pgsql \
       php8.2-cli \
       php8.2-common \
       && rm -rf /var/lib/apt/lists/*
   
   # Copy configuration
   COPY containers/apache/apache2.conf.template /etc/apache2/apache2.conf.template
   COPY containers/apache/sites-available/ /etc/apache2/sites-available/
   COPY containers/apache/entrypoint.sh /entrypoint.sh
   
   RUN chmod +x /entrypoint.sh
   
   EXPOSE 80
   ENTRYPOINT ["/entrypoint.sh"]
   CMD ["apache2ctl", "-D", "FOREGROUND"]
   EOF
   ```

3. **Configure container discovery** (optional):
   ```bash
   # Set custom containers path in .env (default: ./containers)
   echo "POSTSTACK_PROJECT_CONTAINERS_PATH=./containers" >> .env
   ```

### Building Project Containers

Use the `container build-project` command to build your custom containers:

```bash
# Build all discovered project containers
poststack container build-project

# Build a specific project container
poststack container build-project --container apache

# Build with no cache (force rebuild)
poststack container build-project --no-cache
```

### Container Discovery

Poststack automatically discovers containers in your `containers/` directory:

- Each subdirectory with a `Dockerfile` becomes a buildable container
- Container name matches the directory name
- Image tag follows the pattern: `{project_name}/{container_name}`
- Build context is the project root directory

Example project structure:
```
my-project/
├── containers/
│   ├── apache/
│   │   ├── Dockerfile
│   │   ├── entrypoint.sh
│   │   └── config/
│   ├── worker/
│   │   ├── Dockerfile
│   │   └── scripts/
│   └── redis/
│       └── Dockerfile
├── migrations/
├── .env
└── README.md
```

### Example: Full Web Application Stack

Here's a complete example of setting up an Apache web server with PHP and PostgreSQL integration:

1. **Create Apache container configuration**:
   ```bash
   mkdir -p containers/apache/sites-available
   
   # Main Dockerfile
   cat > containers/apache/Dockerfile << 'EOF'
   FROM poststack/base-debian:latest
   
   RUN apt-get update && apt-get install -y \
       apache2 \
       php8.2 \
       php8.2-pgsql \
       php8.2-cli \
       php8.2-common \
       gettext-base \
       && rm -rf /var/lib/apt/lists/*
   
   COPY containers/apache/apache2.conf.template /etc/apache2/apache2.conf.template
   COPY containers/apache/sites-available/ /etc/apache2/sites-available/
   COPY containers/apache/entrypoint.sh /entrypoint.sh
   
   RUN chmod +x /entrypoint.sh && \
       a2enmod rewrite && \
       a2dissite 000-default
   
   EXPOSE 80
   ENTRYPOINT ["/entrypoint.sh"]
   CMD ["apache2ctl", "-D", "FOREGROUND"]
   EOF
   
   # Apache configuration template
   cat > containers/apache/apache2.conf.template << 'EOF'
   ServerRoot "/etc/apache2"
   Listen 80
   
   LoadModule authz_core_module modules/mod_authz_core.so
   LoadModule dir_module modules/mod_dir.so
   LoadModule mime_module modules/mod_mime.so
   LoadModule rewrite_module modules/mod_rewrite.so
   LoadModule php_module modules/libphp8.2.so
   
   <Directory />
       Options FollowSymLinks
       AllowOverride None
       Require all denied
   </Directory>
   
   <Directory "/var/www/html">
       Options Indexes FollowSymLinks
       AllowOverride All
       Require all granted
   </Directory>
   
   DirectoryIndex index.php index.html
   
   IncludeOptional sites-enabled/*.conf
   EOF
   
   # Site configuration template
   cat > containers/apache/sites-available/unified.conf.template << 'EOF'
   <VirtualHost *:80>
       ServerName localhost
       DocumentRoot /var/www/html
       
       <Directory /var/www/html>
           AllowOverride All
           Require all granted
       </Directory>
       
       # Environment variables for database connection
       SetEnv DB_HOST ${DB_HOST}
       SetEnv DB_PORT ${DB_PORT}
       SetEnv DB_NAME ${DB_NAME}
       SetEnv DB_USER ${DB_USER}
       SetEnv DB_PASS ${DB_PASS}
       
       ErrorLog /var/log/apache2/error.log
       CustomLog /var/log/apache2/access.log combined
   </VirtualHost>
   EOF
   
   # Entrypoint script
   cat > containers/apache/entrypoint.sh << 'EOF'
   #!/bin/bash
   set -e
   
   # Substitute environment variables in configuration templates
   envsubst < /etc/apache2/apache2.conf.template > /etc/apache2/apache2.conf
   envsubst < /etc/apache2/sites-available/unified.conf.template > /etc/apache2/sites-available/unified.conf
   
   # Enable the site
   a2ensite unified.conf
   
   # Execute the main command
   exec "$@"
   EOF
   ```

2. **Set up environment variables**:
   ```bash
   cat >> .env << 'EOF'
   # Database connection for Apache container
   DB_HOST=localhost
   DB_PORT=5434
   DB_NAME=poststack
   DB_USER=poststack
   DB_PASS=poststack_dev
   EOF
   ```

3. **Build and run the stack**:
   ```bash
   # Build PostgreSQL container
   poststack container build
   
   # Build project containers
   poststack container build-project
   
   # Start PostgreSQL
   poststack container start
   
   # Run Apache container (manual docker/podman command for now)
   podman run -d \
     --name my-project-apache \
     -p 8080:80 \
     -v $(pwd)/public:/var/www/html \
     --env-file .env \
     my-project/apache
   ```

### Integration with Database

Your custom containers can easily connect to the Poststack-managed PostgreSQL database:

```php
<?php
// Example PHP connection using environment variables
$host = $_ENV['DB_HOST'] ?? 'localhost';
$port = $_ENV['DB_PORT'] ?? '5432';
$dbname = $_ENV['DB_NAME'] ?? 'poststack';
$user = $_ENV['DB_USER'] ?? 'poststack';
$password = $_ENV['DB_PASS'] ?? 'poststack_dev';

$pdo = new PDO("pgsql:host=$host;port=$port;dbname=$dbname", $user, $password);
?>
```

### Best Practices

1. **Use the base image**: Build from `poststack/base-debian:latest` for consistency
2. **Template configurations**: Use environment variable substitution for flexible deployments
3. **Volume mounting**: Mount your application code from the host for development
4. **Environment files**: Use `.env` files for container configuration
5. **Build context**: Remember that the build context is your project root, not the container directory

### Container Lifecycle Management

#### Starting Project Containers

```bash
# Start all discovered project containers with default settings
poststack container start-project

# Start specific container
poststack container start-project --container apache

# Start with custom host port
poststack container start-project --container apache --port 9090

# Start with environment file and volume mounts
poststack container start-project \
  --container apache \
  --env-file .env.production \
  --volume ./public:/var/www/html \
  --volume ./logs:/var/log/apache2

# Wait for container to be ready before returning
poststack container start-project --container apache --wait
```

#### Stopping Project Containers

```bash
# Stop specific project container
poststack container stop-project --container apache

# Stop all project containers
poststack container stop-project --all-project
```

#### Container Status and Management

```bash
# Check status of all containers (includes project containers)
poststack container status

# Remove project containers
poststack container remove my-project-apache

# Check container logs
podman logs my-project-apache
```

### Container Customization with Environment Variables

You can customize project container behavior using environment variables:

```bash
# Custom container names
export POSTSTACK_APACHE_CONTAINER_NAME="my-custom-apache"
export POSTSTACK_WORKER_CONTAINER_NAME="background-worker"

# Custom ports
export POSTSTACK_APACHE_PORT="9090"
export POSTSTACK_API_PORT="8000"

# Container-specific environment variables (passed to container)
export POSTSTACK_APACHE_ENV_DB_HOST="localhost"
export POSTSTACK_APACHE_ENV_DB_PORT="5434"
export POSTSTACK_APACHE_ENV_DEBUG="true"

# Or use .env file
cat >> .env << EOF
POSTSTACK_APACHE_CONTAINER_NAME=production-apache
POSTSTACK_APACHE_PORT=8080
POSTSTACK_APACHE_ENV_ENVIRONMENT=production
EOF
```

### Container Management Commands

```bash
# Build project containers
poststack container build-project [--container NAME] [--no-cache]

# Start project containers
poststack container start-project [--container NAME] [--port PORT] [--env-file FILE]

# Stop project containers  
poststack container stop-project [--container NAME] [--all-project]

# Check status (includes project containers)
poststack container status

# Remove containers
poststack container remove <container_names>
```

## Environment Management

Poststack's environment management system provides professional multi-environment deployment workflows with automatic database provisioning and variable substitution. This is the **recommended approach** for new projects.

### Quick Start with Environment Management

1. **Create Environment Configuration** (.poststack.yml):
   ```yaml
   project:
     name: myapp
     description: "My application with multi-environment deployment"

   environments:
     dev:
       postgres:
         database: myapp_dev
         port: 5433
         user: myapp_dev_user
         password: auto_generated
       deployment:
         pod: containers/app/app-pod.yaml
       variables:
         LOG_LEVEL: debug
         DEBUG_MODE: "true"
         APP_PORT: "8080"

     production:
       postgres:
         database: myapp_prod
         port: 5435
         user: myapp_prod_user
         password: auto_generated
       deployment:
         compose: containers/app/app-compose.yml
       variables:
         LOG_LEVEL: warn
         DEBUG_MODE: "false"
         APP_PORT: "80"
   ```

2. **Create Deployment Files** with variable substitution:
   ```yaml
   # containers/app/app-pod.yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: myapp-${POSTSTACK_ENVIRONMENT}
   spec:
     containers:
     - name: web
       image: myapp/web:latest
       ports:
       - containerPort: 80
         hostPort: ${APP_PORT}
       env:
       - name: DATABASE_URL
         value: "${POSTSTACK_DATABASE_URL}"
       - name: ENVIRONMENT
         value: "${POSTSTACK_ENVIRONMENT}"
       - name: LOG_LEVEL
         value: "${LOG_LEVEL}"
   ```

3. **Deploy Environments**:
   ```bash
   # Preview what will be deployed
   poststack env dry-run dev
   
   # Start development environment
   poststack env start dev
   
   # Check status
   poststack env status dev
   
   # Start production environment  
   poststack env start production
   ```

### Environment Configuration (.poststack.yml)

The `.poststack.yml` file defines your project's environments and deployment configuration:

```yaml
project:
  name: myapp
  description: "Application description"

environments:
  <environment_name>:
    postgres:
      database: <database_name>       # Environment-specific database
      port: <host_port>               # Host port for PostgreSQL
      user: <username>                # Database user
      password: auto_generated        # Auto-generate secure password
      host: localhost                 # Database host
    
    init:                             # Optional: Initialization containers
      - compose: containers/init/init.yml      # Run before main deployment
      - pod: containers/migrations/migrations.yaml   # Init containers must exit cleanly
    
    deployment:                       # Main application deployment
      compose: containers/app/app.yml         # Docker Compose file
      # OR
      pod: containers/app/app.yaml           # Podman Pod file
    
    variables:                        # Environment-specific variables
      LOG_LEVEL: info
      DEBUG_MODE: "false"
      CUSTOM_VAR: "value"
```

### Variable Substitution

Poststack automatically provides these variables to your deployment files:

#### Built-in Variables (Automatically Provided)
- `${POSTSTACK_DATABASE_URL}` - Complete PostgreSQL connection string
- `${POSTSTACK_ENVIRONMENT}` - Environment name (dev, staging, production)
- `${DB_HOST}` - Database host
- `${DB_PORT}` - Database port  
- `${DB_NAME}` - Database name
- `${DB_USER}` - Database user
- `${DB_PASSWORD}` - Database password

#### Custom Variables
Define your own variables in the environment configuration:

```yaml
environments:
  dev:
    variables:
      LOG_LEVEL: debug
      APP_PORT: "8080"
      REDIS_URL: "redis://localhost:6379"
```

#### Variable Syntax
```yaml
# Basic substitution
value: "${VARIABLE_NAME}"

# With default values
value: "${VARIABLE_NAME:-default_value}"

# Example usage
env:
- name: DATABASE_URL
  value: "${POSTSTACK_DATABASE_URL}"
- name: LOG_LEVEL  
  value: "${LOG_LEVEL:-info}"
- name: PORT
  value: "${APP_PORT:-3000}"
```

### Environment Workflow

#### Development Workflow
```bash
# List available environments
poststack env list

# Preview configuration for development
poststack env dry-run dev

# Start development environment
poststack env start dev
# → Creates postgres database (myapp_dev on port 5433)
# → Runs init containers (migrations, setup)
# → Starts application containers with injected variables

# Check what's running
poststack env status dev

# View logs
poststack env logs dev

# Stop when done
poststack env stop dev
```

#### Production Deployment
```bash
# Preview production configuration
poststack env dry-run production

# Deploy to production
poststack env start production
# → Creates postgres database (myapp_prod on port 5435)
# → Runs production init containers
# → Deploys with production configuration

# Monitor status
poststack env status production
```

### Init Phase

The init phase runs containers that must complete successfully before the main deployment:

```yaml
environments:
  dev:
    init:
      - compose: containers/migrations/migrations.yml    # Database migrations
      - pod: containers/seed-data/seed-data.yaml       # Seed test data
    deployment:
      pod: containers/app/app.yaml              # Main application
```

**Init Phase Rules:**
- Init containers run sequentially in the order listed
- Each init container must exit with code 0 (success)
- If any init container fails, deployment is aborted
- Logs from failed init containers are displayed for debugging

### Debugging and Troubleshooting

#### Dry-Run Mode
Preview what variables will be substituted without actually deploying:

```bash
# Show all variables for an environment
poststack env dry-run dev

# Show variables used in a specific file
poststack env dry-run dev --file containers/app/app-pod.yaml
```

#### Status and Logs
```bash
# Show status of all environments
poststack env status

# Show detailed status for one environment
poststack env status dev

# View logs for environment
poststack env logs dev

# View logs for specific service
poststack env logs dev web
```

#### Common Issues

**Port Conflicts:**
```bash
# Error: port already in use
# Solution: Change port in .poststack.yml or stop conflicting container
```

**Init Container Failures:**
```bash
# Check init container logs
poststack env logs dev migrations

# Re-run just the init phase
poststack env init dev
```

**Variable Substitution Issues:**
```bash
# Preview variables before deployment
poststack env dry-run dev --file containers/app/app.yaml

# Check for undefined variables (shows as "UNDEFINED")
```

### Migration from Container Commands

If you're currently using `poststack container` commands, here's how to migrate:

#### Before (Container Commands)
```bash
# Old approach
poststack container build
poststack container start --postgres-port 5433
poststack container start-project --container apache --port 8080
```

#### After (Environment Management)
```bash
# New approach - create .poststack.yml first, then:
poststack env start dev
```

### Best Practices

1. **Environment Parity**: Keep environments as similar as possible, varying only necessary configuration
2. **Version Control**: Commit .poststack.yml and deployment files to version control
3. **Secrets Management**: Use auto_generated passwords for databases, manage other secrets externally
4. **Port Management**: Use different ports per environment to avoid conflicts
5. **Database Naming**: Include environment name in database names for clarity
6. **Testing**: Use dry-run mode to validate configurations before deployment

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