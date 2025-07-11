# User Container Integration Guide

## Overview

This guide explains how to build and integrate your own containers with poststack's PostgreSQL-focused container management platform. Poststack provides PostgreSQL container management and schema migration capabilities, while allowing you to build custom containers that integrate with the PostgreSQL database.

## Architecture Overview

```text
Your Application Stack
├── PostgreSQL (managed by poststack)
├── Your Web Application Container
├── Your Background Worker Container
├── Your API Container
└── Other Custom Containers
```

## Prerequisites

- Poststack installed and configured
- PostgreSQL container running via poststack
- Basic knowledge of containers (Docker/Podman)
- Understanding of PostgreSQL connections

## Getting Started

### 1. Setup PostgreSQL with Poststack

First, ensure you have PostgreSQL running via poststack:

```bash
# Start PostgreSQL container
poststack database start

# Initialize schema
poststack database create-schema

# Verify connection
poststack database test-connection
```

### 2. Get Database Connection Information

Poststack provides the database connection details:

```bash
# Show current database configuration
poststack config-show

# Example output:
# Database URL: postgresql://poststack:password@localhost:5432/poststack
```

## Container Integration Patterns

### Base Container Pattern

Create containers that can connect to poststack's PostgreSQL:

```dockerfile
FROM debian:bookworm-slim

# Install essential packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create application user
RUN useradd -m -s /bin/bash appuser

# Set up Python environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install your application dependencies
COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

# Copy your application
COPY --chown=appuser:appuser . /app
WORKDIR /app

# Switch to application user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run your application
CMD ["python", "app.py"]
```

### Environment Variables

Your containers should accept these environment variables:

```bash
# Database connection (provided by poststack)
POSTSTACK_DATABASE_URL=postgresql://user:pass@host:port/db

# Application-specific variables
APP_ENV=production
LOG_LEVEL=INFO
PORT=8000
```

### Example Application Container

Here's a complete example of a web application container:

```dockerfile
# Dockerfile for your web application
FROM debian:bookworm-slim

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash webapp

# Python environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python packages
COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

# Copy application
COPY --chown=webapp:webapp . /app
WORKDIR /app

# Switch to app user
USER webapp

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application
CMD ["python", "app.py"]
```

## Database Integration

### Connecting to PostgreSQL

Your application should connect to PostgreSQL using the provided database URL:

```python
# Python example
import os
import psycopg2
from urllib.parse import urlparse

def get_db_connection():
    """Get database connection from poststack configuration"""
    database_url = os.getenv('POSTSTACK_DATABASE_URL')
    if not database_url:
        raise ValueError("POSTSTACK_DATABASE_URL not provided")
    
    # Parse the URL
    parsed = urlparse(database_url)
    
    # Create connection
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path[1:],  # Remove leading /
        user=parsed.username,
        password=parsed.password
    )
    
    return conn

# Usage
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT version()")
print(cursor.fetchone())
```

### Schema Management

Your application should work with poststack's schema management:

```python
# Check if your application tables exist
def check_app_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'users'
    """)
    
    return cursor.fetchone() is not None

# Create application-specific tables
def create_app_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
```

## Running Your Containers

### Development Setup

```bash
# 1. Start PostgreSQL with poststack
poststack database start

# 2. Get database URL
DATABASE_URL=$(poststack config-show | grep "Database URL" | cut -d' ' -f3)

# 3. Build your container
podman build -t myapp:latest .

# 4. Run your container with database connection
podman run -d \
    --name myapp \
    -e POSTSTACK_DATABASE_URL="$DATABASE_URL" \
    -e APP_ENV=development \
    -p 8000:8000 \
    myapp:latest
```

### Production Setup

```bash
# 1. Start PostgreSQL with poststack
poststack database start

# 2. Run your containers with proper configuration
podman run -d \
    --name myapp \
    -e POSTSTACK_DATABASE_URL="postgresql://user:pass@host:5432/db" \
    -e APP_ENV=production \
    -e LOG_LEVEL=INFO \
    -p 8000:8000 \
    --restart=unless-stopped \
    myapp:latest
```

## Container Orchestration

### Docker Compose Example

```yaml
# docker-compose.yml
version: '3.8'

services:
  # PostgreSQL managed by poststack
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: poststack
      POSTGRES_USER: poststack
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U poststack"]
      interval: 30s
      timeout: 10s
      retries: 5

  # Your web application
  webapp:
    build: .
    environment:
      POSTSTACK_DATABASE_URL: postgresql://poststack:${POSTGRES_PASSWORD}@postgres:5432/poststack
      APP_ENV: production
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

  # Your background worker
  worker:
    build: .
    environment:
      POSTSTACK_DATABASE_URL: postgresql://poststack:${POSTGRES_PASSWORD}@postgres:5432/poststack
      APP_ENV: production
    command: ["python", "worker.py"]
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres_data:
```

## Best Practices

### 1. Health Checks

Always implement health checks in your containers:

```python
# Flask example
from flask import Flask, jsonify
import psycopg2

app = Flask(__name__)

@app.route('/health')
def health_check():
    try:
        # Check database connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500
```

### 2. Graceful Shutdown

Handle shutdown signals properly:

```python
import signal
import sys

def signal_handler(sig, frame):
    print('Shutting down gracefully...')
    # Close database connections
    # Stop background tasks
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

### 3. Configuration Management

Use environment variables for configuration:

```python
import os

class Config:
    DATABASE_URL = os.getenv('POSTSTACK_DATABASE_URL')
    APP_ENV = os.getenv('APP_ENV', 'development')
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    PORT = int(os.getenv('PORT', 8000))
    
    # Validate required configuration
    if not DATABASE_URL:
        raise ValueError("POSTSTACK_DATABASE_URL is required")
```

### 4. Logging

Implement structured logging:

```python
import logging
import os

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Log database operations
def create_user(username, email):
    logger.info(f"Creating user: {username}")
    try:
        # Database operation
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email) VALUES (%s, %s)",
            (username, email)
        )
        conn.commit()
        logger.info(f"User created successfully: {username}")
    except Exception as e:
        logger.error(f"Failed to create user {username}: {e}")
        raise
    finally:
        cursor.close()
        conn.close()
```

## Testing Integration

### Unit Tests

```python
import unittest
from unittest.mock import patch, MagicMock
from myapp import create_user

class TestUserCreation(unittest.TestCase):
    
    @patch('myapp.get_db_connection')
    def test_create_user_success(self, mock_get_db):
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Test user creation
        create_user('testuser', 'test@example.com')
        
        # Verify database calls
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
```

### Integration Tests

```python
import pytest
import os
from myapp import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_health_check(client):
    """Test health check endpoint"""
    response = client.get('/health')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data['status'] == 'healthy'
    assert data['database'] == 'connected'

def test_user_creation(client):
    """Test user creation API"""
    response = client.post('/users', json={
        'username': 'testuser',
        'email': 'test@example.com'
    })
    assert response.status_code == 201
```

## Monitoring and Observability

### Metrics

Export metrics for monitoring:

```python
from prometheus_client import Counter, Histogram, generate_latest

# Metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests')
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')

@app.route('/metrics')
def metrics():
    return generate_latest()
```

### Logging Integration

Forward logs to centralized logging:

```python
import logging
from pythonjsonlogger import jsonlogger

# JSON logging for structured logs
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   ```bash
   # Check if PostgreSQL is running
   poststack database status
   
   # Test connection
   poststack database test-connection
   ```

2. **Container Networking**
   ```bash
   # Check if containers can reach each other
   podman exec myapp ping postgres
   ```

3. **Environment Variables**
   ```bash
   # Check environment variables in container
   podman exec myapp env | grep POSTSTACK
   ```

### Debug Commands

```bash
# Check container logs
podman logs myapp

# Execute commands in container
podman exec -it myapp /bin/bash

# Check PostgreSQL logs
poststack database logs
```

## Examples

See the `examples/` directory for complete working examples:

- `examples/web-app/` - Flask web application
- `examples/worker/` - Background worker
- `examples/api/` - REST API service
- `examples/compose/` - Docker Compose setup

## Migration from Other Platforms

If you're migrating from other container platforms:

1. **From Docker Compose**: Update your compose files to use poststack for PostgreSQL
2. **From Kubernetes**: Create ConfigMaps with poststack database URLs
3. **From Manual Setup**: Replace manual PostgreSQL setup with poststack commands

This guide provides the foundation for building containers that integrate with poststack's PostgreSQL management while maintaining flexibility for your specific use cases.
