"""
Service Discovery Registry for Poststack

Provides service discovery and URL generation based on service types.
Enables automatic service connection without manual variable duplication.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    """Information about a discovered service with dual endpoints."""
    name: str
    type: str
    networking_mode: str  # 'host', 'bridge', or 'mixed'
    network_endpoint: Optional['ServiceEndpoint']
    host_endpoint: Optional['ServiceEndpoint']
    variables: Dict[str, str]
    
    
@dataclass 
class ServiceEndpoint:
    """A service endpoint with connection details."""
    host: str
    port: int
    protocol: str
    url: str


class ServiceRegistry:
    """
    Service discovery registry that generates connection URLs and variables
    based on service types and deployment configuration.
    """
    
    def __init__(self, project_name: str, environment: str):
        """
        Initialize service registry for a specific project and environment.
        
        Args:
            project_name: Name of the project (e.g., 'unified')
            environment: Environment name (e.g., 'dev', 'staging')
        """
        self.project_name = project_name
        self.environment = environment
        self.services: Dict[str, ServiceInfo] = {}
        
        # Template substitution map for resolving variables in hostnames
        self.template_vars = {
            "ENVIRONMENT": environment,
            "PROJECT": project_name
        }
        
    def register_service(self, name: str, service_type: str, variables: Dict[str, str]) -> None:
        """
        Register a service with the registry, generating both network and host endpoints.
        
        Args:
            name: Service name (e.g., 'postgres', 'apache')
            service_type: Service type (e.g., 'postgres', 'web')
            variables: Service configuration variables
        """
        networking_mode = self._detect_networking_mode(name, variables)
        network_endpoint = self._generate_network_endpoint(name, service_type, variables)
        host_endpoint = self._generate_host_endpoint(name, service_type, variables, networking_mode)
        
        service_info = ServiceInfo(
            name=name,
            type=service_type,
            networking_mode=networking_mode,
            network_endpoint=network_endpoint,
            host_endpoint=host_endpoint,
            variables=variables
        )
        
        self.services[name] = service_info
        logger.info(f"Registered service: {name} ({service_type}) mode={networking_mode} network={network_endpoint} host={host_endpoint}")
        
    def get_service_url(self, service_name: str, prefer_host: bool = False) -> Optional[str]:
        """
        Get the complete connection URL for a service.
        
        Args:
            service_name: Name of the service to get URL for
            prefer_host: If True, prefer host endpoint over network endpoint
            
        Returns:
            Complete service URL or None if service not found
        """
        service = self.services.get(service_name)
        if not service:
            logger.warning(f"Service '{service_name}' not found in registry")
            return None
            
        endpoint = self._select_endpoint(service, prefer_host)
        if not endpoint:
            logger.warning(f"No available endpoint for service '{service_name}'")
            return None
            
        return endpoint.url
    
    def get_service_endpoint(self, service_name: str, prefer_host: bool = False) -> Optional[ServiceEndpoint]:
        """
        Get service endpoint details.
        
        Args:
            service_name: Name of the service
            prefer_host: If True, prefer host endpoint over network endpoint
            
        Returns:
            ServiceEndpoint with connection details or None if not found
        """
        service = self.services.get(service_name)
        if not service:
            return None
            
        return self._select_endpoint(service, prefer_host)
    
    def generate_service_variables(self, target_service: str, dependencies: List[str], target_networking_mode: str = None) -> Dict[str, str]:
        """
        Generate service connection variables for a target service based on its dependencies.
        
        Args:
            target_service: Service that needs connection variables
            dependencies: List of service names this service depends on
            target_networking_mode: Networking mode of the target service ('host', 'bridge', or None for auto-detect)
            
        Returns:
            Dictionary of generated variables
        """
        variables = {}
        
        # Auto-detect target networking mode if not provided
        if target_networking_mode is None:
            target_service_info = self.services.get(target_service)
            target_networking_mode = target_service_info.networking_mode if target_service_info else 'bridge'
        
        for dep_name in dependencies:
            service = self.services.get(dep_name)
            if not service:
                logger.warning(f"Dependency '{dep_name}' not found for service '{target_service}'")
                continue
                
            # Select appropriate endpoint based on target service networking mode
            prefer_host = (target_networking_mode == 'host')
            endpoint = self._select_endpoint(service, prefer_host)
            
            if not endpoint:
                logger.warning(f"No available endpoint for dependency '{dep_name}' of service '{target_service}'")
                continue
                
            # Generate type-specific variables using selected endpoint
            if service.type == "postgres":
                variables.update(self._generate_postgres_variables(service, endpoint))
            elif service.type == "web":
                variables.update(self._generate_web_variables(service, endpoint))
            else:
                variables.update(self._generate_generic_variables(service, endpoint))
                
        return variables
    
    def _generate_service_host(self, name: str, service_type: str) -> str:
        """
        Generate the pod host name for a service for network DNS resolution.
        
        Uses template pattern from pod metadata.name and substitutes variables.
        Pattern: {project}-{name}-{environment}
        E.g., 'unified-postgres-dev', 'unified-apache-dev'
        """
        # Generate template-aware hostname
        # This matches the pattern used in pod templates: unified-postgres-${ENVIRONMENT}
        hostname_template = f"{self.project_name}-{name}-${{ENVIRONMENT}}"
        
        # Substitute template variables
        return self._substitute_template_variables(hostname_template)
    
    def _substitute_template_variables(self, template: str) -> str:
        """Substitute template variables in a string."""
        import re
        
        # Pattern matches ${VAR} syntax
        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}'
        
        def replace_variable(match):
            var_name = match.group(1)
            if var_name in self.template_vars:
                return self.template_vars[var_name]
            else:
                logger.warning(f"Undefined template variable in service registry: ${{{var_name}}}")
                return match.group(0)  # Return unchanged if not found
        
        return re.sub(pattern, replace_variable, template)
    
    def _detect_networking_mode(self, name: str, variables: Dict[str, str]) -> str:
        """Detect networking mode for a service based on variables."""
        # Check service-specific host network variables first (highest priority)
        if name == 'apache' and variables.get('APACHE_USE_HOST_NETWORK', '').lower() == 'true':
            return 'host'
        elif name == 'mail' and variables.get('MAIL_USE_HOST_NETWORK', '').lower() == 'true':
            return 'host'
        
        # Some services like postgres should use bridge networking even with global host mode
        # They use host port mappings instead of host networking
        if name in ['postgres', 'volume-setup']:
            return 'bridge'
        
        # Fail2ban should always use host networking for iptables access
        if name == 'fail2ban':
            return 'host'
        
        # Check general network mode setting for other services
        network_mode = variables.get('NETWORK_MODE', '').lower()
        if network_mode == 'host':
            return 'host'
        
        # Default to bridge networking
        return 'bridge'
    
    def _generate_network_endpoint(self, name: str, service_type: str, variables: Dict[str, str]) -> Optional[ServiceEndpoint]:
        """Generate network endpoint for inter-service communication."""
        # Network endpoints use container names and standard ports
        host = self._generate_service_host(name, service_type)
        port = self._extract_container_port(service_type, variables)
        protocol = self._get_service_protocol(service_type)
        url = self._generate_endpoint_url(host, port, protocol, service_type, variables)
        
        return ServiceEndpoint(
            host=host,
            port=port,
            protocol=protocol,
            url=url
        )
    
    def _generate_host_endpoint(self, name: str, service_type: str, variables: Dict[str, str], networking_mode: str) -> Optional[ServiceEndpoint]:
        """Generate host endpoint for external access."""
        # Only generate host endpoint if service uses host networking or has port mappings
        if networking_mode == 'host':
            # Host networking: use localhost with standard service ports
            host = "localhost"
            port = self._extract_container_port(service_type, variables)
        else:
            # Bridge networking: check for explicit host port mappings
            host_port = self._extract_host_port(service_type, variables)
            if host_port is None:
                return None  # No host endpoint available
            host = "localhost"
            port = host_port
        
        protocol = self._get_service_protocol(service_type)
        url = self._generate_endpoint_url(host, port, protocol, service_type, variables)
        
        return ServiceEndpoint(
            host=host,
            port=port,
            protocol=protocol,
            url=url
        )
    
    def _select_endpoint(self, service: ServiceInfo, prefer_host: bool = False) -> Optional[ServiceEndpoint]:
        """Select appropriate endpoint based on preference and availability."""
        if prefer_host and service.host_endpoint:
            return service.host_endpoint
        elif not prefer_host and service.network_endpoint:
            return service.network_endpoint
        else:
            # Fallback to available endpoint
            return service.host_endpoint or service.network_endpoint
    
    def _generate_endpoint_url(self, host: str, port: int, protocol: str, service_type: str, variables: Dict[str, str]) -> str:
        """Generate URL for an endpoint based on service type."""
        if service_type == "postgres":
            return self._generate_postgres_url_for_endpoint(host, port, variables)
        elif service_type == "web":
            return f"{protocol}://{host}:{port}"
        else:
            return f"{protocol}://{host}:{port}"
    
    def _get_primary_container_name(self, service_type: str) -> str:
        """Get the primary container name for a service type."""
        container_names = {
            "postgres": "postgres",
            "web": "apache-web",  # Based on current apache container name
            "redis": "redis",
            "mysql": "mysql"
        }
        return container_names.get(service_type, service_type)
    
    def _extract_container_port(self, service_type: str, variables: Dict[str, str]) -> int:
        """Extract the container port for inter-service communication."""
        # For inter-service communication, use standard container ports
        default_ports = {
            "postgres": 5432,
            "web": 80,
            "redis": 6379,
            "mysql": 3306
        }
        
        # For known service types, always use the standard container port
        if service_type in default_ports:
            return default_ports[service_type]
        
        # For unknown service types, try to find port in variables
        port_keys = ["CONTAINER_PORT", "PORT", "HTTP_PORT", "HTTPS_PORT"]
        for key in port_keys:
            if key in variables:
                try:
                    return int(variables[key])
                except ValueError:
                    continue
                    
        # Final fallback
        return 8080
    
    def _extract_host_port(self, service_type: str, variables: Dict[str, str]) -> Optional[int]:
        """Extract the host port for external access (if mapped)."""
        # Look for service-specific host port variables
        host_port_keys = {
            "postgres": ["DB_PORT", "POSTGRES_HOST_PORT"],
            "web": ["APACHE_HOST_PORT", "HTTP_HOST_PORT"],
            "mail": ["MAIL_HOST_PORT", "SMTP_HOST_PORT"]
        }
        
        # Check service-specific keys first
        if service_type in host_port_keys:
            for key in host_port_keys[service_type]:
                if key in variables:
                    try:
                        return int(variables[key])
                    except ValueError:
                        continue
        
        # Check generic host port keys
        generic_keys = ["HOST_PORT", "EXPOSED_PORT"]
        for key in generic_keys:
            if key in variables:
                try:
                    return int(variables[key])
                except ValueError:
                    continue
        
        return None  # No host port mapping found
    
    # Legacy method removed - URLs are now generated per endpoint
    
    def _generate_postgres_url_for_endpoint(self, host: str, port: int, variables: Dict[str, str]) -> str:
        """Generate PostgreSQL connection URL for a specific endpoint."""
        user = variables.get("DB_USER", "postgres")
        password = variables.get("DB_PASSWORD", "")
        database = variables.get("DB_NAME", "postgres")
        
        # URL encode password to handle special characters
        encoded_password = quote(password) if password else ""
        
        if encoded_password:
            return f"postgresql://{user}:{encoded_password}@{host}:{port}/{database}"
        else:
            return f"postgresql://{user}@{host}:{port}/{database}"
    
    # Legacy method removed - URLs are now generated per endpoint
    
    # Legacy method removed - URLs are now generated per endpoint
    
    def _get_service_protocol(self, service_type: str) -> str:
        """Get the default protocol for a service type."""
        protocols = {
            "postgres": "postgresql",
            "web": "http",
            "redis": "redis",
            "mysql": "mysql"
        }
        return protocols.get(service_type, "tcp")
    
    def _generate_postgres_variables(self, service: ServiceInfo, endpoint: ServiceEndpoint) -> Dict[str, str]:
        """Generate PostgreSQL-specific connection variables using selected endpoint."""
        return {
            "POSTGRES_URL": endpoint.url,
            "DATABASE_URL": endpoint.url,  # Common alias
            "POSTGRES_HOST": endpoint.host,
            "POSTGRES_PORT": str(endpoint.port),
            "POSTGRES_USER": service.variables.get("DB_USER", "postgres"),
            "POSTGRES_PASSWORD": service.variables.get("DB_PASSWORD", ""),
            "POSTGRES_DATABASE": service.variables.get("DB_NAME", "postgres"),
        }
    
    def _generate_web_variables(self, service: ServiceInfo, endpoint: ServiceEndpoint) -> Dict[str, str]:
        """Generate web service connection variables using selected endpoint."""
        return {
            "WEB_URL": endpoint.url,
            "WEB_HOST": endpoint.host,
            "WEB_PORT": str(endpoint.port),
        }
    
    def _generate_generic_variables(self, service: ServiceInfo, endpoint: ServiceEndpoint) -> Dict[str, str]:
        """Generate generic service connection variables using selected endpoint."""
        service_upper = service.name.upper()
        return {
            f"{service_upper}_URL": endpoint.url,
            f"{service_upper}_HOST": endpoint.host,
            f"{service_upper}_PORT": str(endpoint.port),
        }
    
    def list_services(self) -> List[ServiceInfo]:
        """Get a list of all registered services."""
        return list(self.services.values())
    
    def get_service_by_type(self, service_type: str) -> List[ServiceInfo]:
        """Get all services of a specific type."""
        return [service for service in self.services.values() if service.type == service_type]