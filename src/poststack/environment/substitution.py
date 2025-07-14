"""
Variable substitution engine for deployment files using Jinja2.

Provides template processing for Docker Compose and Podman Pod files
with automatic database configuration injection and custom variables.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Undefined

from ..config import EnvironmentConfig, VolumeConfig
from ..service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


class VariableSubstitutor:
    """Engine for processing template files with Jinja2 variable substitution."""
    
    def __init__(self, environment_name_or_variables, environment_config: EnvironmentConfig = None, project_name: str = "poststack", service_registry: Optional[ServiceRegistry] = None):
        """Initialize substitutor with environment configuration or direct variables."""
        
        # Set basic attributes first
        self.environment_config = environment_config
        self.project_name = project_name
        
        # Handle both old style (env_name, config) and new style (variables dict)
        if isinstance(environment_name_or_variables, dict):
            # New style: called with variables dict
            self.variables = environment_name_or_variables.copy()
            self.environment_name = None
            self.service_registry = None
        else:
            # Old style: called with environment name and config
            self.environment_name = environment_name_or_variables
            self.service_registry = service_registry or ServiceRegistry(project_name, self.environment_name)
            # Register all deployments with the service registry
            self._register_deployments()
            self.variables = self._build_variable_map()
        
        # Initialize Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader('.'),  # Use current directory as base
            undefined=Undefined,           # Allow undefined variables with defaults
            trim_blocks=True,              # Clean up whitespace
            lstrip_blocks=True
        )
        
        # Add custom filters
        self.jinja_env.filters['default'] = lambda value, default='': value if value is not None else default
        
        logger.debug(f"Created variable substitutor for environment '{self.environment_name}' with {len(self.variables)} variables")
    
    def _build_variable_map(self) -> Dict[str, str]:
        """Build complete variable map from all sources."""
        variables = {}
        
        # Add basic environment variables
        variables.update(self._get_basic_variables())
        
        # Add volume variables
        variables.update(self._get_volume_variables())
        
        # Add user-defined variables from environment config
        variables.update(self.environment_config.variables)
        
        # Add auto-generated service discovery variables
        # Generate service variables for all registered services (for global template context)
        for service_name in self.service_registry.services.keys():
            service_vars = self.service_registry.generate_service_variables(service_name, [], target_networking_mode='bridge')
            variables.update(service_vars)
        
        # Add system environment variables (POSTSTACK_*)
        variables.update(self._get_system_variables())
        
        logger.debug(f"Built variable map with {len(variables)} total variables")
        return variables
    
    def _register_deployments(self):
        """Register all deployments with the service registry."""
        if not self.environment_config.deployments:
            return
        
        for deployment in self.environment_config.deployments:
            # Use deployment name directly from DeploymentRef
            service_name = deployment.name
            service_type = deployment.type or "web"  # Use deployment type or default to web
            deployment_variables = deployment.variables or {}
            
            # Merge deployment variables with environment variables for networking mode detection
            merged_variables = {}
            merged_variables.update(self.environment_config.variables)  # Environment-level variables
            merged_variables.update(deployment_variables)  # Deployment-specific variables
            
            self.service_registry.register_service(service_name, service_type, merged_variables)
        
        logger.debug(f"Registered {len(self.environment_config.deployments)} deployments with service registry")
    
    def _get_basic_variables(self) -> Dict[str, str]:
        """Get basic poststack environment variables."""
        return {
            "ENVIRONMENT": self.environment_name,
            "PROJECT": self.project_name,
            "POSTSTACK_ENVIRONMENT": self.environment_name,
        }
    
    def _get_system_variables(self) -> Dict[str, str]:
        """Get system environment variables with POSTSTACK_ prefix."""
        system_vars = {}
        for key, value in os.environ.items():
            if key.startswith("POSTSTACK_"):
                system_vars[key] = value
        return system_vars
    
    def _get_volume_variables(self) -> Dict[str, str]:
        """Generate volume configuration variables for templates."""
        variables = {}
        
        # Standard volume names that templates expect
        standard_volumes = ["postgres_data", "unified_logs", "mail_data", "apache_data", "mail_config"]
        
        # Process configured volumes
        if hasattr(self.environment_config, 'volumes') and self.environment_config.volumes:
            for volume_name, volume_config in self.environment_config.volumes.items():
                # Generate volume type variable (e.g., VOLUME_POSTGRES_DATA_TYPE)
                var_prefix = f"VOLUME_{volume_name.upper()}"
                volume_type = self._get_k8s_volume_type(volume_config)
                variables[f"{var_prefix}_TYPE"] = volume_type
                
                # Generate volume configuration variable
                volume_config_json = self._get_k8s_volume_config(volume_config, volume_name)
                variables[f"{var_prefix}_CONFIG"] = volume_config_json
        
        # Provide defaults for standard volumes that aren't configured
        for volume_name in standard_volumes:
            var_prefix = f"VOLUME_{volume_name.upper()}"
            if f"{var_prefix}_TYPE" not in variables:
                variables[f"{var_prefix}_TYPE"] = "emptyDir"
                variables[f"{var_prefix}_CONFIG"] = "{}"
            
        return variables
    
    def _get_k8s_volume_type(self, volume_config: VolumeConfig) -> str:
        """Get Kubernetes/Podman volume type for a volume configuration."""
        type_mapping = {
            "emptyDir": "emptyDir",
            "named": "persistentVolumeClaim", 
            "hostPath": "hostPath"
        }
        return type_mapping.get(volume_config.type, "emptyDir")
    
    def _get_k8s_volume_config(self, volume_config: VolumeConfig, volume_name: str) -> str:
        """Get Kubernetes/Podman volume configuration YAML for a volume."""
        if volume_config.type == "emptyDir":
            return "{}"
        elif volume_config.type == "hostPath":
            return f'{{"path": "{volume_config.path}"}}'
        elif volume_config.type == "named":
            # Generate default volume name if not specified
            default_name = f"{self.project_name}-{volume_name}-{self.environment_name}"
            volume_claim_name = volume_config.name or default_name
            return f'{{"claimName": "{volume_claim_name}"}}'
        else:
            return "{}"
    
    def process_file(self, file_path: str, output_path: Optional[str] = None) -> str:
        """
        Process template file using Jinja2 and return substituted content.
        
        Args:
            file_path: Path to template file (.j2 extension expected)
            output_path: Optional path to write processed file
            
        Returns:
            Processed file content with variables substituted
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise ValueError(f"Template file not found: {file_path}")
        
        logger.info(f"Processing Jinja2 template file: {file_path}")
        
        # Read template content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
        except Exception as e:
            raise ValueError(f"Failed to read template file {file_path}: {e}")
        
        # Process Jinja2 template
        try:
            template = self.jinja_env.from_string(template_content)
            processed_content = template.render(**self.variables)
        except Exception as e:
            raise ValueError(f"Failed to process Jinja2 template {file_path}: {e}")
        
        # Write to output file if specified
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(processed_content)
                logger.info(f"Processed template written to: {output_path}")
            except Exception as e:
                raise ValueError(f"Failed to write processed file {output_path}: {e}")
        
        return processed_content
    
    def get_variables(self) -> Dict[str, str]:
        """Get all available template variables."""
        return self.variables.copy()
    
    def list_missing_variables(self, template_content: str) -> List[str]:
        """
        Analyze template content and return list of undefined variables.
        
        Args:
            template_content: Jinja2 template content to analyze
            
        Returns:
            List of variable names that are referenced but not defined
        """
        try:
            template = self.jinja_env.from_string(template_content)
            # Get all variables referenced in the template
            referenced_vars = template.environment.get_template(template.name or '<string>').module.__dict__.get('variables', [])
            
            # Find variables that aren't in our variable map
            missing = [var for var in referenced_vars if var not in self.variables]
            return missing
        except Exception:
            # If we can't parse the template, return empty list
            return []
    
    def process_template(self, template_path: str) -> str:
        """
        Process template file and return substituted content.
        Compatible with old API for backward compatibility.
        """
        return self.process_file(template_path)


def create_temp_processed_file(template_path: str, substitutor: VariableSubstitutor, suffix: str = ".processed") -> str:
    """
    Create a temporary file with processed template content.
    
    Args:
        template_path: Path to template file
        substitutor: VariableSubstitutor instance to use
        suffix: Suffix for temp file name
        
    Returns:
        Path to temporary processed file
    """
    processed_content = substitutor.process_template(template_path)
    
    # Create temporary file
    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix, text=True)
    
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            f.write(processed_content)
    except Exception:
        # Clean up if writing fails
        os.close(temp_fd)
        os.unlink(temp_path)
        raise
    
    logger.debug(f"Created temporary processed file: {temp_path}")
    return temp_path


def cleanup_temp_file(temp_path: str) -> None:
    """
    Clean up temporary processed file.
    
    Args:
        temp_path: Path to temporary file to remove
    """
    try:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
            logger.debug(f"Cleaned up temporary file: {temp_path}")
    except Exception as e:
        logger.warning(f"Failed to cleanup temporary file {temp_path}: {e}")