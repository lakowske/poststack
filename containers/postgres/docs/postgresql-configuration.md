# PostgreSQL Configuration Guide

This document explains the PostgreSQL configuration files created by `poststack init`.

## Files Overview

### containers/postgres/Dockerfile
The PostgreSQL container definition. Based on the poststack base image and includes:
- PostgreSQL 15 with PostGIS extensions
- Performance monitoring tools
- Development and debugging tools
- Health check scripts

**Customization**: You can modify this to add additional PostgreSQL extensions,
tools, or configuration.

### containers/postgres/entrypoint.sh
The container startup script that:
- Processes configuration templates
- Initializes the database if needed
- Sets up users and permissions
- Starts PostgreSQL

**Customization**: Add custom initialization logic, additional users, or
database setup steps.

### containers/postgres/postgresql.conf.template
PostgreSQL server configuration template with environment variable substitution.
Key settings include:
- `listen_addresses` - Network interface configuration
- `port` - PostgreSQL port (usually 5432)
- `max_connections` - Connection limit
- `shared_buffers` - Memory allocation
- `log_statement` - SQL logging level

**Customization**: Tune performance settings, logging, and security options
for your specific workload.

### containers/postgres/pg_hba.conf.template
PostgreSQL client authentication configuration. Controls:
- Which users can connect
- Which databases they can access
- Authentication methods (trust, password, etc.)
- Connection sources (local, network)

**Customization**: Add specific authentication rules for your application
users and security requirements.

### deploy/postgres-pod.yaml
Podman/Kubernetes pod specification for PostgreSQL deployment. Defines:
- Container image and ports
- Environment variables
- Volume mounts
- Resource limits
- Health checks

**Customization**: Adjust resource limits, add persistent volumes, or
modify health check settings.

## Environment Variables

The following environment variables are available for configuration:

### Database Settings
- `DB_NAME` - Database name
- `DB_USER` - Database user
- `DB_PASSWORD` - Database password  
- `DB_PORT` - Database port

### PostgreSQL Specific
- `PGDATA` - PostgreSQL data directory
- `POSTGRES_INITDB_ARGS` - Additional initdb arguments
- `POSTGRES_HOST_AUTH_METHOD` - Default authentication method

### Poststack Environment
- `POSTSTACK_ENVIRONMENT` - Current environment (dev/staging/prod)
- `POSTSTACK_CONFIG_DIR` - Configuration directory
- `POSTSTACK_CERT_PATH` - SSL certificate path
- `POSTSTACK_LOG_DIR` - Log directory

## Configuration Examples

### Development Environment
```yaml
# .poststack.yml
environments:
  dev:
    postgres:
      database: myapp_dev
      port: 5436
      user: dev_user
      password: auto_generated
```

### Production Tuning
```ini
# postgresql.conf.template - Add these settings
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
```

### Custom Authentication
```ini
# pg_hba.conf.template - Add application user
host myapp_prod app_user 10.0.0.0/8 md5
```

## Building and Deployment

After customizing the configuration:

1. **Build the container**:
   ```bash
   poststack build
   ```

2. **Deploy the environment**:
   ```bash
   poststack env start
   ```

3. **Verify deployment**:
   ```bash
   poststack env status
   ```

## Troubleshooting

### Container Build Issues
- Check Dockerfile syntax and COPY paths
- Ensure all referenced files exist
- Verify base image is available

### Startup Problems
- Check entrypoint.sh for syntax errors
- Verify environment variables are set correctly
- Review PostgreSQL logs for initialization errors

### Connection Issues
- Verify pg_hba.conf allows your connection
- Check postgresql.conf listen_addresses setting
- Ensure port is not blocked by firewall

### Performance Issues
- Tune postgresql.conf memory settings
- Monitor resource usage in pod specification
- Check for slow queries in PostgreSQL logs

## Further Reading

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [Podman Pod Documentation](https://docs.podman.io/en/latest/markdown/podman-pod.1.html)
