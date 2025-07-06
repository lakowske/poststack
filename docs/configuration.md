# Configuration

All service configuration is centrally managed in the PostgreSQL database. This provides a single source of truth for all container services and enables dynamic configuration updates.

## Database Schema

### Core Configuration Table (`config`)

```sql
CREATE TABLE config (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    service VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Required Configuration Items

- `domain_name` - Primary domain for all services
- `le_email` - Let's Encrypt notification email
- `cert_path` - Override path for certificates (default: `/data/certificates`)
- `log_level` - Global logging verbosity (DEBUG, INFO, WARNING, ERROR)

### Service-Specific Tables

#### Domains (`domains`)

```sql
CREATE TABLE domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) UNIQUE NOT NULL,
    type VARCHAR(50) NOT NULL, -- 'primary', 'alias', 'subdomain'
    parent_domain_id INTEGER REFERENCES domains(id),
    ssl_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Services (`services`)

```sql
CREATE TABLE services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    container_name VARCHAR(255),
    port INTEGER,
    health_check_url VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Service Configuration (`service_config`)

```sql
CREATE TABLE service_config (
    id SERIAL PRIMARY KEY,
    service_id INTEGER REFERENCES services(id),
    key VARCHAR(255) NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(service_id, key)
);
```

#### Users (`users`)

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### User Permissions (`user_permissions`)

```sql
CREATE TABLE user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    service_id INTEGER REFERENCES services(id),
    permission VARCHAR(50) NOT NULL, -- 'admin', 'user', 'readonly'
    UNIQUE(user_id, service_id)
);
```

## Configuration Access

Services access configuration through environment variables populated from the database at container startup:

1. **Base configuration** - Common settings loaded for all services
2. **Service-specific configuration** - Additional settings per service
3. **Dynamic updates** - Services can watch for configuration changes

### Example Service Startup

```bash
# Configuration is injected as environment variables
DOMAIN_NAME=example.com
LE_EMAIL=admin@example.com
SERVICE_PORT=8080
# ... additional service-specific config
```

## Configuration Management API

A Python-based API manages all configuration:

```python
# Example usage
from poststack.config import ConfigManager

config = ConfigManager()
config.set('domain_name', 'example.com')
config.get_service_config('apache')
config.update_user_permissions('john', 'mail', 'admin')
```