# Core Container Architecture Specification

## Purpose

This document defines the core architectural principles and patterns for container-based service infrastructure.

## Scope

- Container orchestration patterns
- Base image design
- Service composition
- Shared resource management

## Requirements

### Functional Requirements

1. Support multiple independent services (web, DNS, mail, certificate management)
2. Enable shared certificate access across services
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

```
debian:bookworm-slim
    └── base-debian (with Python, certificates tooling)
        ├── apache-debian
        ├── bind-debian
        ├── mail-debian
        ├── certbot-debian
        ├── postgres-debian
        └── liquibase-debian
```

### Shared Resources

1. **Certificate Volume**

   - Named volume: `certs`
   - Mount path: `/data/certificates`
   - Access: Read-only for services, read-write for certbot

2. **User/Group Model**
   - Shared group: `certgroup` (GID 9999)
   - Certificate owner: `certuser` (UID 9999)
   - Services added to certgroup for access

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

# Certificate access group
RUN groupadd -g 9999 certgroup && \
    useradd -u 9999 -g certgroup -M -s /usr/sbin/nologin certuser

# Python environment
RUN python3 -m venv /data/.venv
ENV PATH="/data/.venv/bin:$PATH"
```

### Service Container Pattern

```dockerfile
FROM base-debian:latest

# Service-specific packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    <service-packages> \
    && rm -rf /var/lib/apt/lists/*

# Add service user to certgroup
RUN usermod -a -G certgroup <service-user>

# Configuration and entrypoint
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

### Volume Mounting Patterns

```bash
# Certificate generation (read-write)
podman run -v certs:/data/certificates ...

# Service usage (read-only)
podman run -v certs:/data/certificates:ro ...
```

## Configuration Management

### Environment Variables

- Service configuration through environment variables
- Template substitution in entrypoint scripts
- Validation before service startup

### Standard Variables

- `DOMAIN` or `DOMAIN_NAME`: Primary service domain
- `LE_EMAIL`: Let's encrypt email
- `CERT_PATH`: Override certificate location
- `LOG_LEVEL`: Service logging verbosity

## Testing Considerations

1. **Image Build Tests**

   - Verify base image builds successfully
   - Confirm service images inherit properly
   - Check final image sizes

2. **Integration Tests**

   - Certificate volume accessibility
   - Service startup with/without certificates
   - Inter-service communication

3. **Security Tests**
   - Non-root service execution
   - File permission validation
   - Network isolation verification

## Future Considerations

1. **Orchestration**

   - Kubernetes manifests
   - Docker Compose files
   - Systemd service units

2. **Monitoring**

   - Health check endpoints
   - Metrics exporters
   - Log aggregation

3. **Scaling**
   - Horizontal scaling patterns
   - Load balancer integration
   - Session management
