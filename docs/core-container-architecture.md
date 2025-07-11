# Container Management Architecture

## Purpose

This document defines the core architectural principles and patterns for building containers that integrate with poststack's PostgreSQL-focused container management platform.

## Scope

- Container integration patterns with poststack
- PostgreSQL-aware container design
- Resource management and shared patterns
- User-extensible container architecture

## Requirements

### Functional Requirements

1. Integrate with poststack's PostgreSQL container management
2. Support user-defined containers that can access PostgreSQL
3. Provide consistent build and deployment patterns
4. Support both development and production environments

### Non-Functional Requirements

1. Minimal container image sizes
2. Fast build times through layer caching
3. Security through principle of least privilege
4. Portability across container runtimes (Docker/Podman)

## Design Decisions

### Container Runtime

- **Primary**: Podman (rootless containers)
- **Compatible**: Docker
- **Rationale**: Enhanced security, no daemon requirement

### Base Image Strategy

```text
debian:bookworm-slim
    └── base-debian (with Python, essential tooling)
        ├── postgres-debian (managed by poststack)
        └── user-containers (user-defined containers)
```

### Shared Resources

1. **PostgreSQL Integration**

   - Database connections via poststack configuration
   - Shared database access patterns
   - Schema management through poststack migrations

2. **Volume Management**
   - Named volumes for persistent data
   - Shared volume patterns between user containers
   - PostgreSQL data persistence managed by poststack

## Implementation Guidelines

### Base Image Requirements

```dockerfile
FROM debian:bookworm-slim

# Essential packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python environment
RUN python3 -m venv /data/.venv
ENV PATH="/data/.venv/bin:$PATH"
```

### User Container Pattern

```dockerfile
FROM base-debian:latest

# Service-specific packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    <your-service-packages> \
    && rm -rf /var/lib/apt/lists/*

# Configuration and entrypoint
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

### Volume Mounting Patterns

```bash
# PostgreSQL data (managed by poststack)
podman run -v poststack-postgres-data:/var/lib/postgresql/data ...

# User application data
podman run -v user-app-data:/app/data ...
```

## Configuration Management

### Environment Variables

- Container configuration through environment variables
- PostgreSQL connection configuration via poststack
- Template substitution in entrypoint scripts
- Validation before service startup

### Standard Variables

- `POSTSTACK_DATABASE_URL`: PostgreSQL connection string (provided by poststack)
- `LOG_LEVEL`: Service logging verbosity
- `APP_ENV`: Application environment (development/production)
- User-defined variables for specific containers

## Testing Considerations

1. **Image Build Tests**

   - Verify base image builds successfully
   - Confirm user images inherit properly
   - Check final image sizes

2. **Integration Tests**

   - PostgreSQL connectivity from user containers
   - Container startup and health checks
   - Volume mounting and data persistence

3. **Security Tests**
   - Non-root container execution
   - File permission validation
   - Network isolation verification

## Future Considerations

1. **Orchestration**

   - Kubernetes manifests for user containers
   - Docker Compose files for development
   - Systemd service units for production

2. **Monitoring**

   - Health check endpoints for user containers
   - Metrics integration with poststack
   - Log aggregation patterns

3. **Scaling**
   - Horizontal scaling patterns for user containers
   - Load balancer integration
   - PostgreSQL connection pooling
