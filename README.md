Poststack

# Overview

Poststack coordinates a set of servers (e.g. postgres, apache, dovecot/postfix, bind, nginx, etc...). It uses Python and Postgres to manage configuration
such as users, passwords and other configuration.

# Getting Started

Poststack features an automatic bootstrap process that guides you through setting up your database and services from scratch. No complex configuration files or manual database setup required!

## Quick Start

1. **Install Prerequisites**
   - Python 3.9+
   - Podman (or Docker)
   - PostgreSQL client tools (optional)

2. **Start the Server**
   ```bash
   python poststack.py
   ```

3. **Follow the Bootstrap Wizard**
   - If no database is configured, you'll be automatically directed to http://localhost:8080/bootstrap
   - Enter your PostgreSQL connection details
   - The system will test the connection and guide you through any issues

4. **Initialize the Schema**
   - If your database is empty, Poststack will offer to create all necessary tables
   - Review the pending changes before applying
   - The schema is managed by Liquibase for safe, versioned updates

5. **Configure Your Services**
   - Once the database is ready, configure your domain and services
   - Enable the services you need (Apache, Mail, DNS, etc.)
   - All configuration is stored centrally in PostgreSQL

## Bootstrap Process

The bootstrap process handles three scenarios automatically:

### No Database Configuration
- Starts a minimal web server on port 8080
- Provides a form to enter PostgreSQL connection details
- Validates and saves the configuration

### Empty Database
- Detects missing schema
- Offers to initialize all tables using Liquibase
- Shows exactly what will be created before proceeding

### Schema Updates Available
- Detects pending schema changes
- Shows a preview of changes
- Allows you to update or skip

## Environment Variables

For automated deployments, you can skip the interactive bootstrap:

```bash
# Set database URL
export DATABASE_URL="postgresql://user:password@localhost:5432/poststack"

# Start the server
python poststack.py
```

## Next Steps

After bootstrap completes:

1. Access the main dashboard at http://localhost:8000
2. Configure your primary domain and Let's Encrypt email
3. Enable and configure the services you need
4. Deploy your containers using the generated configurations

For detailed configuration options, see [Configuration Documentation](docs/configuration.md).
For architectural details, see [Core Architecture](docs/core-architecture.md).
