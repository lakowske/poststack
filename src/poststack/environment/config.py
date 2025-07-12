"""
Environment configuration parsing and validation.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ..config import PoststackConfig, PoststackProjectConfig, EnvironmentConfig

logger = logging.getLogger(__name__)


class EnvironmentConfigParser:
    """Parser and validator for environment configuration."""
    
    def __init__(self, poststack_config: PoststackConfig):
        """Initialize parser with poststack configuration."""
        self.poststack_config = poststack_config
    
    def load_project_config(self) -> PoststackProjectConfig:
        """Load and validate project configuration."""
        project_config = self.poststack_config.load_project_config()
        
        if project_config is None:
            raise ValueError(
                f"No project configuration found at {self.poststack_config.project_config_file}. "
                "Run 'poststack init' to create a project configuration."
            )
        
        # Validate that referenced files exist
        self._validate_deployment_files(project_config)
        
        return project_config
    
    def get_environment_config(self, env_name: str) -> EnvironmentConfig:
        """Get configuration for a specific environment."""
        project_config = self.load_project_config()
        
        if env_name not in project_config.environments:
            available = ", ".join(project_config.environments.keys())
            raise ValueError(
                f"Environment '{env_name}' not found. Available environments: {available}"
            )
        
        return project_config.environments[env_name]
    
    def list_environments(self) -> List[str]:
        """List all available environment names."""
        try:
            project_config = self.load_project_config()
            return list(project_config.environments.keys())
        except ValueError:
            return []
    
    def _validate_deployment_files(self, project_config: PoststackProjectConfig) -> None:
        """Validate that all referenced deployment files exist."""
        errors = []
        
        for env_name, env_config in project_config.environments.items():
            # Validate init deployment files
            for i, init_ref in enumerate(env_config.init):
                file_path = init_ref.compose or init_ref.pod
                if not Path(file_path).exists():
                    errors.append(f"Environment '{env_name}' init[{i}]: {file_path} not found")
            
            # Validate main deployment file
            deployment_file = env_config.deployment.compose or env_config.deployment.pod
            if not Path(deployment_file).exists():
                errors.append(f"Environment '{env_name}' deployment: {deployment_file} not found")
        
        if errors:
            error_msg = "Deployment file validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
            raise ValueError(error_msg)


def create_default_project_config(project_name: str) -> PoststackProjectConfig:
    """Create a default project configuration."""
    from ..config import (
        PoststackProjectConfig, 
        ProjectMeta, 
        EnvironmentConfig, 
        PostgresConfig, 
        DeploymentRef
    )
    
    return PoststackProjectConfig(
        project=ProjectMeta(
            name=project_name,
            description=f"{project_name} project managed by poststack"
        ),
        environments={
            "dev": EnvironmentConfig(
                postgres=PostgresConfig(
                    database=f"{project_name}_dev",
                    port=5433,
                    user=f"{project_name}_user",
                    password="auto_generated"
                ),
                init=[],
                deployment=DeploymentRef(compose="deploy/dev-compose.yml"),
                variables={
                    "LOG_LEVEL": "debug",
                    "ENVIRONMENT": "development"
                }
            )
        }
    )


def save_project_config(config: PoststackProjectConfig, file_path: str = ".poststack.yml") -> None:
    """Save project configuration to YAML file."""
    config_dict = config.model_dump(exclude_none=True)
    
    with open(file_path, 'w') as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    
    logger.info(f"Project configuration saved to {file_path}")


def validate_project_config_file(file_path: str) -> List[str]:
    """Validate a project configuration file and return any errors."""
    errors = []
    
    try:
        with open(file_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        if not config_data:
            errors.append("Configuration file is empty")
            return errors
        
        # Try to parse as PoststackProjectConfig
        try:
            PoststackProjectConfig(**config_data)
        except Exception as e:
            errors.append(f"Configuration validation failed: {e}")
            
    except FileNotFoundError:
        errors.append(f"Configuration file not found: {file_path}")
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML syntax: {e}")
    except Exception as e:
        errors.append(f"Unexpected error: {e}")
    
    return errors