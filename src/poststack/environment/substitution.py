"""
Variable substitution engine for deployment files.

Provides template processing for Docker Compose and Podman Pod files
with automatic database configuration injection and custom variables.
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from ..config import EnvironmentConfig, VolumeConfig
from ..service_registry import ServiceRegistry

logger = logging.getLogger(__name__)


class VariableSubstitutor:
    """Engine for processing template files with variable substitution."""
    
    def __init__(self, environment_name: str, environment_config: EnvironmentConfig, project_name: str = "poststack", service_registry: Optional[ServiceRegistry] = None):
        """Initialize substitutor with environment configuration."""
        self.environment_name = environment_name
        self.environment_config = environment_config
        self.project_name = project_name
        self.service_registry = service_registry or ServiceRegistry(project_name, environment_name)
        
        # Register all deployments with the service registry
        self._register_deployments()
        
        self.variables = self._build_variable_map()
        
        logger.debug(f"Created variable substitutor for environment '{environment_name}' with {len(self.variables)} variables")
    
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
        variables.update(self._get_service_discovery_variables())
        
        # Add system environment variables (prefixed with POSTSTACK_)
        variables.update(self._get_system_variables())
        
        return variables
    
    def _register_deployments(self) -> None:
        """Register all deployments with the service registry."""
        for deployment in self.environment_config.deployments:
            if deployment.enabled:
                self.service_registry.register_service(
                    name=deployment.get_deployment_name(),
                    service_type=deployment.type or "generic",
                    variables=deployment.variables
                )
                logger.debug(f"Registered deployment '{deployment.get_deployment_name()}' with service registry")
    
    def _get_service_discovery_variables(self) -> Dict[str, str]:
        """Generate service discovery variables for all registered services."""
        variables = {}
        
        # Generate variables for each deployment based on its dependencies
        for deployment in self.environment_config.deployments:
            if deployment.enabled and deployment.depends_on:
                service_name = deployment.get_deployment_name()
                dep_vars = self.service_registry.generate_service_variables(
                    target_service=service_name,
                    dependencies=deployment.depends_on
                )
                variables.update(dep_vars)
                logger.debug(f"Generated {len(dep_vars)} service discovery variables for '{service_name}'")
        
        return variables
    
    def _get_basic_variables(self) -> Dict[str, str]:
        """Get basic environment variables without PostgreSQL dependency."""
        return {
            "ENVIRONMENT": self.environment_name,
            "PROJECT": self.project_name,
        }
    
    
    def _get_system_variables(self) -> Dict[str, str]:
        """Get system environment variables that start with POSTSTACK_."""
        variables = {}
        
        for key, value in os.environ.items():
            if key.startswith("POSTSTACK_"):
                # Don't override our built-in variables
                if key not in self._get_poststack_variables():
                    variables[key] = value
        
        return variables
    
    def _get_volume_variables(self) -> Dict[str, str]:
        """Generate volume variables for template substitution."""
        variables = {}
        
        # Define standard volume names used in templates
        standard_volumes = ['postgres_data', 'postgres_logs', 'postgres_config', 'apache_logs', 'apache_config']
        
        # Process configured volumes
        for volume_name, volume_config in self.environment_config.volumes.items():
            # Convert volume name to uppercase for variable names
            var_prefix = f"VOLUME_{volume_name.upper()}"
            
            # Generate volume type variable
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
        Process template file and return substituted content.
        
        Args:
            file_path: Path to template file
            output_path: Optional path to write processed file
            
        Returns:
            Processed file content with variables substituted
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise ValueError(f"Template file not found: {file_path}")
        
        logger.info(f"Processing template file: {file_path}")
        
        # Read template content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
        except Exception as e:
            raise ValueError(f"Failed to read template file {file_path}: {e}")
        
        # Process substitutions
        processed_content = self._substitute_variables(template_content, str(file_path))
        
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
    
    def _substitute_variables(self, content: str, file_context: str) -> str:
        """Substitute variables in content using ${VAR} syntax."""
        # Pattern matches ${VAR} or ${VAR:-default_value}
        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::(-[^}]*))?\}'
        
        def replace_variable(match):
            var_name = match.group(1)
            default_value = match.group(2)
            
            # Remove leading dash from default value if present
            if default_value and default_value.startswith('-'):
                default_value = default_value[1:]
            
            if var_name in self.variables:
                value = self.variables[var_name]
                logger.debug(f"Substituting ${{{var_name}}} -> '{value}' in {file_context}")
                return value
            elif default_value is not None:
                logger.debug(f"Using default value for ${{{var_name}}} -> '{default_value}' in {file_context}")
                return default_value
            else:
                logger.warning(f"Undefined variable ${{{var_name}}} in {file_context}, leaving unchanged")
                return match.group(0)  # Return original ${VAR} unchanged
        
        return re.sub(pattern, replace_variable, content)
    
    def dry_run(self, file_path: str) -> Dict[str, str]:
        """
        Analyze template file and return variables that would be substituted.
        
        Args:
            file_path: Path to template file
            
        Returns:
            Dictionary of variables found in template with their resolved values
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise ValueError(f"Template file not found: {file_path}")
        
        # Read template content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f"Failed to read template file {file_path}: {e}")
        
        # Find all variable references
        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::(-[^}]*))?\}'
        matches = re.findall(pattern, content)
        
        found_variables = {}
        
        for var_name, default_value in matches:
            # Remove leading dash from default value if present
            if default_value and default_value.startswith('-'):
                default_value = default_value[1:]
            
            if var_name in self.variables:
                found_variables[var_name] = self.variables[var_name]
            elif default_value:
                found_variables[var_name] = f"(default: {default_value})"
            else:
                found_variables[var_name] = "(UNDEFINED)"
        
        return found_variables
    
    def get_all_variables(self) -> Dict[str, str]:
        """Get all available variables and their values."""
        return self.variables.copy()
    
    def validate_template(self, file_path: str) -> List[str]:
        """
        Validate template file and return list of issues.
        
        Args:
            file_path: Path to template file
            
        Returns:
            List of validation errors/warnings
        """
        issues = []
        
        try:
            dry_run_result = self.dry_run(file_path)
            
            for var_name, value in dry_run_result.items():
                if value == "(UNDEFINED)":
                    issues.append(f"Undefined variable: ${{{var_name}}}")
                elif value.startswith("(default:"):
                    issues.append(f"Using default value for: ${{{var_name}}} -> {value}")
        
        except Exception as e:
            issues.append(f"Template validation failed: {e}")
        
        return issues


def create_temp_processed_file(template_path: str, substitutor: VariableSubstitutor, suffix: str = ".processed") -> str:
    """
    Create a temporary processed version of a template file.
    
    Args:
        template_path: Path to the template file
        substitutor: VariableSubstitutor instance
        suffix: Suffix to add to temporary file name
        
    Returns:
        Path to the temporary processed file
    """
    template_path = Path(template_path)
    temp_path = template_path.with_suffix(template_path.suffix + suffix)
    
    # Process the template
    processed_content = substitutor.process_file(str(template_path))
    
    # Write to temporary file
    with open(temp_path, 'w', encoding='utf-8') as f:
        f.write(processed_content)
    
    logger.debug(f"Created temporary processed file: {temp_path}")
    return str(temp_path)


def cleanup_temp_file(file_path: str) -> None:
    """Clean up a temporary processed file."""
    try:
        Path(file_path).unlink()
        logger.debug(f"Cleaned up temporary file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up temporary file {file_path}: {e}")