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
    """Information about a discovered service."""
    name: str
    type: str
    host: str
    port: int
    variables: Dict[str, str]
    
    
@dataclass 
class ServiceEndpoint:
    """A service endpoint with connection details."""
    url: str
    host: str
    port: int
    protocol: str


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
        Register a service with the registry.
        
        Args:
            name: Service name (e.g., 'postgres', 'apache')
            service_type: Service type (e.g., 'postgres', 'web')
            variables: Service configuration variables
        """
        host = self._generate_service_host(name, service_type)
        port = self._extract_port(service_type, variables)
        
        service_info = ServiceInfo(
            name=name,
            type=service_type,
            host=host,
            port=port,
            variables=variables
        )
        
        self.services[name] = service_info
        logger.debug(f"Registered service: {name} ({service_type}) at {host}:{port}")
        
    def get_service_url(self, service_name: str) -> Optional[str]:
        """
        Get the complete connection URL for a service.
        
        Args:
            service_name: Name of the service to get URL for
            
        Returns:
            Complete service URL or None if service not found
        """
        service = self.services.get(service_name)
        if not service:
            logger.warning(f"Service '{service_name}' not found in registry")
            return None
            
        return self._generate_service_url(service)
    
    def get_service_endpoint(self, service_name: str) -> Optional[ServiceEndpoint]:
        """
        Get service endpoint details.
        
        Args:
            service_name: Name of the service
            
        Returns:
            ServiceEndpoint with connection details or None if not found
        """
        service = self.services.get(service_name)
        if not service:
            return None
            
        url = self._generate_service_url(service)
        protocol = self._get_service_protocol(service.type)
        
        return ServiceEndpoint(
            url=url,
            host=service.host,
            port=service.port,
            protocol=protocol
        )
    
    def generate_service_variables(self, target_service: str, dependencies: List[str]) -> Dict[str, str]:
        """
        Generate service connection variables for a target service based on its dependencies.
        
        Args:
            target_service: Service that needs connection variables
            dependencies: List of service names this service depends on
            
        Returns:
            Dictionary of generated variables
        """
        variables = {}
        
        for dep_name in dependencies:
            service = self.services.get(dep_name)
            if not service:
                logger.warning(f"Dependency '{dep_name}' not found for service '{target_service}'")
                continue
                
            # Generate type-specific variables
            if service.type == "postgres":
                variables.update(self._generate_postgres_variables(service))
            elif service.type == "web":
                variables.update(self._generate_web_variables(service))
            else:
                variables.update(self._generate_generic_variables(service))
                
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
    
    def _get_primary_container_name(self, service_type: str) -> str:
        """Get the primary container name for a service type."""
        container_names = {
            "postgres": "postgres",
            "web": "apache-web",  # Based on current apache container name
            "redis": "redis",
            "mysql": "mysql"
        }
        return container_names.get(service_type, service_type)
    
    def _extract_port(self, service_type: str, variables: Dict[str, str]) -> int:
        """Extract the container port for inter-service communication (not host port)."""
        # For inter-service communication, use standard container ports
        # regardless of host port mappings
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
    
    def _generate_service_url(self, service: ServiceInfo) -> str:
        """Generate the complete service URL based on type."""
        if service.type == "postgres":
            return self._generate_postgres_url(service)
        elif service.type == "web":
            return self._generate_web_url(service)
        else:
            return self._generate_generic_url(service)
    
    def _generate_postgres_url(self, service: ServiceInfo) -> str:
        """Generate PostgreSQL connection URL."""
        user = service.variables.get("DB_USER", "postgres")
        password = service.variables.get("DB_PASSWORD", "")
        database = service.variables.get("DB_NAME", "postgres")
        
        # URL encode password to handle special characters
        encoded_password = quote(password) if password else ""
        
        if encoded_password:
            return f"postgresql://{user}:{encoded_password}@{service.host}:{service.port}/{database}"
        else:
            return f"postgresql://{user}@{service.host}:{service.port}/{database}"
    
    def _generate_web_url(self, service: ServiceInfo) -> str:
        """Generate web service URL."""
        protocol = "https" if service.port == 443 else "http"
        return f"{protocol}://{service.host}:{service.port}"
    
    def _generate_generic_url(self, service: ServiceInfo) -> str:
        """Generate generic service URL."""
        protocol = self._get_service_protocol(service.type)
        return f"{protocol}://{service.host}:{service.port}"
    
    def _get_service_protocol(self, service_type: str) -> str:
        """Get the default protocol for a service type."""
        protocols = {
            "postgres": "postgresql",
            "web": "http",
            "redis": "redis",
            "mysql": "mysql"
        }
        return protocols.get(service_type, "tcp")
    
    def _generate_postgres_variables(self, service: ServiceInfo) -> Dict[str, str]:
        """Generate PostgreSQL-specific connection variables."""
        url = self._generate_postgres_url(service)
        return {
            "POSTGRES_URL": url,
            "DATABASE_URL": url,  # Common alias
            "POSTGRES_HOST": service.host,
            "POSTGRES_PORT": str(service.port),
            "POSTGRES_USER": service.variables.get("DB_USER", "postgres"),
            "POSTGRES_PASSWORD": service.variables.get("DB_PASSWORD", ""),
            "POSTGRES_DATABASE": service.variables.get("DB_NAME", "postgres"),
        }
    
    def _generate_web_variables(self, service: ServiceInfo) -> Dict[str, str]:
        """Generate web service connection variables."""
        url = self._generate_web_url(service)
        return {
            "WEB_URL": url,
            "WEB_HOST": service.host,
            "WEB_PORT": str(service.port),
        }
    
    def _generate_generic_variables(self, service: ServiceInfo) -> Dict[str, str]:
        """Generate generic service connection variables."""
        url = self._generate_generic_url(service)
        service_upper = service.name.upper()
        return {
            f"{service_upper}_URL": url,
            f"{service_upper}_HOST": service.host,
            f"{service_upper}_PORT": str(service.port),
        }
    
    def list_services(self) -> List[ServiceInfo]:
        """Get a list of all registered services."""
        return list(self.services.values())
    
    def get_service_by_type(self, service_type: str) -> List[ServiceInfo]:
        """Get all services of a specific type."""
        return [service for service in self.services.values() if service.type == service_type]