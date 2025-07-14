# Service Registry

The service registry is a key component of poststack that provides automatic service discovery and connection management for multi-container deployments. It enables services to automatically connect to their dependencies without manual configuration.

## Purpose

- **Automatic Service Discovery**: Services are automatically registered and discoverable by other services
- **Dual Endpoint Support**: Supports both network-internal and host-accessible endpoints
- **Mixed Networking**: Handles scenarios where services use different networking modes (host vs bridge)
- **Template Integration**: Automatically injects connection variables into deployment templates
- **Dependency Management**: Generates connection variables based on service dependencies

## Architecture

### Core Components

#### ServiceInfo
Represents a registered service with dual endpoint support:

```python
@dataclass
class ServiceInfo:
    name: str                                      # Service name (e.g., 'postgres', 'apache')
    type: str                                      # Service type (e.g., 'postgres', 'web', 'mail')
    networking_mode: str                           # 'host', 'bridge', or 'mixed'
    network_endpoint: Optional[ServiceEndpoint]    # Network-internal endpoint
    host_endpoint: Optional[ServiceEndpoint]       # Host-accessible endpoint
    variables: Dict[str, str]                      # Service configuration variables
```

#### ServiceEndpoint
Represents a connection endpoint:

```python
@dataclass
class ServiceEndpoint:
    host: str        # Hostname or IP address
    port: int        # Port number
    protocol: str    # Protocol (http, https, postgresql, etc.)
    url: str         # Complete connection URL
```

#### ServiceRegistry
Main registry class that manages service discovery:

```python
class ServiceRegistry:
    def __init__(self, project_name: str, environment: str)
    def register_service(self, name: str, service_type: str, variables: Dict[str, str])
    def generate_service_variables(self, target_service: str, dependencies: List[str], target_networking_mode: str = None)
    def get_service_url(self, service_name: str, prefer_host: bool = False)
    def get_service_endpoint(self, service_name: str, prefer_host: bool = False)
```

## Dual Endpoint System

### Networking Mode Detection

The service registry automatically detects the networking mode for each service:

- **Host Mode**: Service uses host networking (`hostNetwork: true`)
- **Bridge Mode**: Service uses bridge networking with container-internal networking

Detection logic:
1. Check service-specific variables (`APACHE_USE_HOST_NETWORK`, `MAIL_USE_HOST_NETWORK`)
2. Check environment-wide setting (`NETWORK_MODE`)
3. Default to bridge mode

### Endpoint Generation

For each registered service, the registry generates up to two endpoints:

#### Network Endpoint
- **Purpose**: Inter-service communication within the container network
- **Format**: `{project}-{service}-{environment}:{container_port}`
- **Example**: `unified-postgres-dev:5432`
- **Availability**: Always available for bridge-mode services

#### Host Endpoint
- **Purpose**: Access from host network or external clients
- **Format**: `localhost:{host_port}`
- **Example**: `localhost:5436`
- **Availability**: Available for host-mode services or bridge services with port mappings

### Endpoint Selection Logic

When generating connection variables, the registry selects endpoints based on the target service's networking mode:

| Target Service Mode | Preferred Endpoint | Fallback |
|---------------------|-------------------|----------|
| Host                | Host endpoint     | Network endpoint |
| Bridge              | Network endpoint  | Host endpoint |

## Configuration

### Service Types

The registry supports several predefined service types:

#### PostgreSQL (`postgres`)
- **Container Port**: 5432
- **Protocol**: `postgresql`
- **Generated Variables**:
  - `POSTGRES_URL`: Complete connection URL
  - `DATABASE_URL`: Alias for POSTGRES_URL
  - `POSTGRES_HOST`: Hostname
  - `POSTGRES_PORT`: Port number
  - `POSTGRES_USER`: Username
  - `POSTGRES_PASSWORD`: Password
  - `POSTGRES_DATABASE`: Database name

#### Web Server (`web`)
- **Container Port**: 80
- **Protocol**: `http` (or `https` for port 443)
- **Generated Variables**:
  - `WEB_URL`: Complete connection URL
  - `WEB_HOST`: Hostname
  - `WEB_PORT`: Port number

#### Generic Services
- **Container Port**: 8080 (default)
- **Protocol**: `tcp`
- **Generated Variables**:
  - `{SERVICE_NAME}_URL`: Complete connection URL
  - `{SERVICE_NAME}_HOST`: Hostname
  - `{SERVICE_NAME}_PORT`: Port number

### Environment Configuration

Configure networking modes in `.poststack.yml`:

```yaml
environments:
  dev:
    variables:
      # Global network mode
      NETWORK_MODE: "host"
      
      # Service-specific host networking
      APACHE_USE_HOST_NETWORK: "true"
      MAIL_USE_HOST_NETWORK: "true"
    
    deployments:
      - name: postgres
        type: postgres
        variables:
          DB_PORT: "5436"  # Host port mapping
      
      - name: apache
        type: web
        depends_on: [postgres]
        variables:
          APACHE_HOST_PORT: "8080"
```

## Usage Examples

### Basic Service Registration

```python
# Initialize registry
registry = ServiceRegistry("unified", "dev")

# Register PostgreSQL service
registry.register_service("postgres", "postgres", {
    "DB_NAME": "unified_dev",
    "DB_USER": "unified_dev_user",
    "DB_PASSWORD": "dev_password123",
    "DB_PORT": "5436",
    "NETWORK_MODE": "bridge"
})

# Register Apache web service
registry.register_service("apache", "web", {
    "APACHE_USE_HOST_NETWORK": "true",
    "APACHE_HOST_PORT": "8080"
})
```

### Dependency Variable Generation

```python
# Generate connection variables for Apache service
# Apache uses host networking, so it will get host endpoints for dependencies
variables = registry.generate_service_variables(
    target_service="apache",
    dependencies=["postgres"],
    target_networking_mode="host"
)

# Result:
# {
#     "POSTGRES_URL": "postgresql://unified_dev_user:dev_password123@localhost:5436/unified_dev",
#     "DATABASE_URL": "postgresql://unified_dev_user:dev_password123@localhost:5436/unified_dev",
#     "POSTGRES_HOST": "localhost",
#     "POSTGRES_PORT": "5436",
#     "POSTGRES_USER": "unified_dev_user",
#     "POSTGRES_PASSWORD": "dev_password123",
#     "POSTGRES_DATABASE": "unified_dev"
# }
```

### Mixed Networking Scenarios

#### Scenario 1: Host Service → Bridge Service
```yaml
# Apache (host) connecting to PostgreSQL (bridge)
apache:
  networking_mode: host
  depends_on: [postgres]

postgres:
  networking_mode: bridge
  host_port: 5436
```

Apache will receive: `POSTGRES_URL=postgresql://user:pass@localhost:5436/db`

#### Scenario 2: Bridge Service → Host Service
```yaml
# Worker (bridge) connecting to Redis (host)
worker:
  networking_mode: bridge
  depends_on: [redis]

redis:
  networking_mode: host
```

Worker will receive: `REDIS_URL=redis://unified-redis-dev:6379`

## Integration with Orchestrator

The service registry integrates with the orchestrator through the variable substitution system:

### Registration Flow
1. **Environment Parsing**: Orchestrator parses `.poststack.yml` configuration
2. **Service Registration**: All deployments are registered with the service registry
3. **Variable Merging**: Environment and deployment variables are merged for networking detection
4. **Template Processing**: Registry variables are injected into deployment templates

### Dependency Resolution
1. **Dependency Detection**: Orchestrator identifies service dependencies from `depends_on` fields
2. **Networking Mode Detection**: Orchestrator determines target service networking mode
3. **Variable Generation**: Registry generates connection variables for dependencies
4. **Template Substitution**: Variables are merged into deployment-specific templates

## Troubleshooting

### Common Issues

#### Service Not Found
```
WARNING: Service 'redis' not found in registry
```
**Solution**: Ensure the service is defined in the `deployments` section of `.poststack.yml`

#### No Available Endpoint
```
WARNING: No available endpoint for service 'postgres'
```
**Solution**: Check that the service has either host networking enabled or port mappings configured

#### Connection Refused
```
ERROR: Connection refused to unified-postgres-dev:5432
```
**Solution**: Verify that the target service is running and accessible from the source service's network

### Debug Information

Enable debug logging to see endpoint selection:

```bash
export POSTSTACK_LOG_LEVEL=DEBUG
poststack env start dev
```

Look for log messages like:
```
INFO: Registered service: postgres (postgres) mode=bridge network=unified-postgres-dev:5432 host=localhost:5436
DEBUG: Deployment apache uses host networking: True
```

### Configuration Validation

Check service registry configuration:

```python
# List all registered services
services = registry.list_services()
for service in services:
    print(f"{service.name}: {service.networking_mode}")
    print(f"  Network: {service.network_endpoint}")
    print(f"  Host: {service.host_endpoint}")
```

## Best Practices

1. **Use Host Networking for External Services**: Services that need real client IP addresses (like web servers with fail2ban)
2. **Use Bridge Networking for Internal Services**: Databases and internal services that don't need external access
3. **Configure Port Mappings**: For bridge services that need external access, configure explicit port mappings
4. **Test Connectivity**: Use `poststack env start --dry-run` to validate configuration before deployment
5. **Monitor Logs**: Enable debug logging to troubleshoot networking issues

## Future Enhancements

- **Load Balancer Integration**: Support for multiple service instances
- **Health Check Integration**: Service availability monitoring
- **Dynamic Service Discovery**: Runtime service registration/deregistration
- **Custom Protocols**: Support for additional service types and protocols