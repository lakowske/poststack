"""
Environment management for copying and removing environments.

Handles the complete lifecycle of environment copying including:
- Resource isolation (ports, databases, containers, volumes)
- Configuration templating and substitution
- Environment registration and cleanup
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from ..config import PoststackConfig, EnvironmentConfig
from .config import EnvironmentConfigParser
from .port_allocator import PortAllocator

logger = logging.getLogger(__name__)


class EnvironmentManager:
    """Manages environment copying, removal, and resource isolation."""
    
    def __init__(self, poststack_config: PoststackConfig):
        """Initialize environment manager."""
        self.poststack_config = poststack_config
        self.config_parser = EnvironmentConfigParser(poststack_config)
        self.port_allocator = PortAllocator(poststack_config.project_root)
        self.project_root = poststack_config.project_root
    
    def copy_environment(self, source_env: str, target_env: str) -> bool:
        """
        Copy an environment with isolated resources.
        
        Args:
            source_env: Name of source environment to copy from
            target_env: Name of target environment to create
            
        Returns:
            True if copy was successful, False otherwise
            
        Raises:
            ValueError: If source environment doesn't exist or target already exists
        """
        logger.info(f"Copying environment '{source_env}' to '{target_env}'")
        
        # Validate source environment exists
        try:
            source_config = self.config_parser.get_environment_config(source_env)
        except ValueError as e:
            raise ValueError(f"Source environment '{source_env}' not found: {e}")
        
        # Check if target environment already exists
        if self._environment_exists(target_env):
            raise ValueError(f"Target environment '{target_env}' already exists")
        
        try:
            # 1. Allocate ports for the new environment
            source_ports = self._extract_ports_from_config(source_config)
            allocated_ports = self.port_allocator.allocate_ports_for_copy(
                source_ports, source_env, target_env
            )
            
            # 2. Create environment configuration
            self._create_environment_config(source_env, target_env, source_config, allocated_ports)
            
            # 3. Update project configuration to include new environment
            self._add_environment_to_project_config(target_env, source_config, allocated_ports)
            
            logger.info(f"Successfully copied environment '{source_env}' to '{target_env}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy environment: {e}")
            # Cleanup on failure
            self._cleanup_failed_copy(target_env)
            raise
    
    def remove_environment(self, env_name: str, force: bool = False) -> bool:
        """
        Remove an environment and all its resources.
        
        Args:
            env_name: Name of environment to remove
            force: If True, remove even if containers are running
            
        Returns:
            True if removal was successful, False otherwise
        """
        logger.info(f"Removing environment '{env_name}' (force={force})")
        
        # Validate environment exists
        if not self._environment_exists(env_name):
            logger.warning(f"Environment '{env_name}' does not exist")
            return False
        
        try:
            # 1. Stop environment if running (unless force=True and it fails)
            if not self._stop_environment(env_name, force):
                if not force:
                    raise RuntimeError(f"Failed to stop environment '{env_name}'. Use --force to override.")
                logger.warning(f"Failed to stop environment '{env_name}', continuing with forced removal")
            
            # 2. Remove containers and volumes
            self._remove_environment_resources(env_name, force)
            
            # 3. Remove databases
            self._remove_environment_databases(env_name)
            
            # 4. Deallocate ports
            self.port_allocator.deallocate_ports_for_environment(env_name)
            
            # 5. Remove from project configuration
            self._remove_environment_from_project_config(env_name)
            
            logger.info(f"Successfully removed environment '{env_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove environment '{env_name}': {e}")
            return False
    
    def list_environments(self, include_copies: bool = True) -> Dict[str, Dict]:
        """
        List all environments with their information.
        
        Args:
            include_copies: If True, include copied environments
            
        Returns:
            Dict mapping environment names to their information
        """
        environments = {}
        
        # Get base environments from project config
        try:
            project_config = self.config_parser.load_project_config()
            for env_name, env_config in project_config.environments.items():
                environments[env_name] = {
                    "type": "base",
                    "status": self._get_environment_status(env_name),
                    "services": getattr(env_config, 'services', []),
                }
        except Exception as e:
            logger.error(f"Failed to load base environments: {e}")
        
        # Get copied environments from port allocator registry
        if include_copies:
            allocated_envs = self.port_allocator.list_allocated_environments()
            for env_name, env_info in allocated_envs.items():
                if env_name not in environments:  # Don't overwrite base environments
                    environments[env_name] = {
                        "type": env_info.get("type", "copy"),
                        "parent": env_info.get("parent"),
                        "status": self._get_environment_status(env_name),
                        "created": env_info.get("created"),
                        "ports": env_info.get("ports", {}),
                    }
        
        return environments
    
    def _extract_ports_from_config(self, env_config: EnvironmentConfig) -> Dict[str, int]:
        """Extract port mappings from environment configuration."""
        # Extract ports from environment variables first
        ports = {}
        
        # Map environment variables to our port keys
        var_to_port_key = {
            "POSTGRES_PORT": "postgres",
            "APACHE_HTTP_PORT": "apache_http",
            "APACHE_HTTPS_PORT": "apache_https", 
            "MAIL_SMTP_PORT": "mail_smtp",
            "MAIL_IMAP_PORT": "mail_imap",
            "MAIL_SUBMISSION_PORT": "mail_submission",
            "DNS_PORT": "dns",
        }
        
        for var_name, port_key in var_to_port_key.items():
            if var_name in env_config.variables:
                try:
                    ports[port_key] = int(env_config.variables[var_name])
                except ValueError:
                    logger.warning(f"Invalid port value for {var_name}: {env_config.variables[var_name]}")
        
        # Use defaults for missing ports
        default_ports = {
            "postgres": 5432,
            "apache_http": 80,
            "apache_https": 443,
            "mail_smtp": 25,
            "mail_imap": 143,
            "mail_submission": 587,
            "dns": 53,
        }
        
        # Fill in missing ports with defaults
        for port_key, default_port in default_ports.items():
            if port_key not in ports:
                ports[port_key] = default_port
        
        logger.debug(f"Extracted ports from environment config: {ports}")
        return ports
    
    def _create_environment_config(self, source_env: str, target_env: str, 
                                 source_config: EnvironmentConfig, 
                                 allocated_ports: Dict[str, int]) -> None:
        """Create configuration files for the new environment."""
        # For now, we'll rely on the project configuration update
        # In the future, this could create dedicated config files per environment
        logger.debug(f"Environment configuration will be handled via project config update")
    
    def _add_environment_to_project_config(self, env_name: str, 
                                         source_config: EnvironmentConfig,
                                         allocated_ports: Dict[str, int]) -> None:
        """Add new environment to project configuration."""
        try:
            project_config = self.config_parser.load_project_config()
            
            # Update deployment-specific variables to use allocated ports
            updated_deployments = []
            for deployment in source_config.deployments:
                updated_deployment_vars = self._update_deployment_variables_for_ports(
                    deployment.variables, allocated_ports, env_name
                )
                # Create a new deployment with updated variables
                from ..config import DeploymentRef
                updated_deployment = DeploymentRef(
                    compose=deployment.compose,
                    pod=deployment.pod,
                    name=deployment.name,
                    type=deployment.type,
                    depends_on=deployment.depends_on,
                    variables=updated_deployment_vars,
                    volumes=deployment.volumes,
                    enabled=deployment.enabled,
                    restart_policy=deployment.restart_policy
                )
                updated_deployments.append(updated_deployment)
            
            # Update init deployments as well
            updated_init = []
            for deployment in source_config.init:
                updated_deployment_vars = self._update_deployment_variables_for_ports(
                    deployment.variables, allocated_ports, env_name
                )
                # Create a new deployment with updated variables
                from ..config import DeploymentRef
                updated_deployment = DeploymentRef(
                    compose=deployment.compose,
                    pod=deployment.pod,
                    name=deployment.name,
                    type=deployment.type,
                    depends_on=deployment.depends_on,
                    variables=updated_deployment_vars,
                    volumes=deployment.volumes,
                    enabled=deployment.enabled,
                    restart_policy=deployment.restart_policy
                )
                updated_init.append(updated_deployment)
            
            # Create new environment config based on source with updated deployments
            new_env_config = EnvironmentConfig(
                deployments=updated_deployments,
                init=updated_init,
                variables=self._update_variables_for_ports(source_config.variables, allocated_ports, env_name),
                volumes=source_config.volumes
            )
            
            # Add to project config
            project_config.environments[env_name] = new_env_config
            
            # Save updated project config
            self.poststack_config.save_project_config(project_config)
            
            logger.debug(f"Added environment '{env_name}' to project configuration")
            
        except Exception as e:
            logger.error(f"Failed to add environment to project config: {e}")
            raise
    
    def _update_variables_for_ports(self, source_variables: Dict[str, str], 
                                  allocated_ports: Dict[str, int], env_name: str) -> Dict[str, str]:
        """Update environment variables to use allocated ports."""
        updated_vars = source_variables.copy()
        
        # Update port-related variables
        port_mappings = {
            "POSTGRES_PORT": "postgres",
            "APACHE_HTTP_PORT": "apache_http", 
            "APACHE_HTTPS_PORT": "apache_https",
            "MAIL_SMTP_PORT": "mail_smtp",
            "MAIL_IMAP_PORT": "mail_imap",
            "MAIL_SUBMISSION_PORT": "mail_submission",
            "DNS_PORT": "dns",
        }
        
        for var_name, port_key in port_mappings.items():
            if port_key in allocated_ports:
                updated_vars[var_name] = str(allocated_ports[port_key])
        
        # Update database-related variables for the new environment
        # Replace hyphens with underscores for valid database names
        safe_env_name = env_name.replace('-', '_')
        updated_vars["POSTGRES_DB"] = f"unified_{safe_env_name}"
        updated_vars["POSTGRES_USER"] = f"unified_{safe_env_name}_user"
        
        # Update environment name for template processing
        updated_vars["POSTSTACK_ENVIRONMENT"] = env_name
        
        # Keep other variables like POSTGRES_PASSWORD from source
        
        return updated_vars
    
    def _update_deployment_variables_for_ports(self, deployment_variables: Dict[str, str], 
                                             allocated_ports: Dict[str, int], env_name: str) -> Dict[str, str]:
        """Update deployment-specific variables to use allocated ports."""
        updated_vars = deployment_variables.copy()
        
        # Update port-related variables in deployment
        port_mappings = {
            "DB_PORT": "postgres",
            "POSTGRES_PORT": "postgres", 
            "APACHE_HTTP_PORT": "apache_http",
            "APACHE_HTTPS_PORT": "apache_https",
            "MAIL_SMTP_PORT": "mail_smtp",
            "MAIL_IMAP_PORT": "mail_imap",
            "MAIL_SUBMISSION_PORT": "mail_submission",
            "MAIL_IMAPS_PORT": "mail_imaps",
            "MAIL_SMTPS_PORT": "mail_smtps",
            "DNS_PORT": "dns",
        }
        
        for var_name, port_key in port_mappings.items():
            if var_name in deployment_variables and port_key in allocated_ports:
                updated_vars[var_name] = str(allocated_ports[port_key])
        
        # Update database-related variables for the new environment
        safe_env_name = env_name.replace('-', '_')
        if "DB_NAME" in deployment_variables:
            updated_vars["DB_NAME"] = f"unified_{safe_env_name}"
        if "DB_USER" in deployment_variables:
            updated_vars["DB_USER"] = f"unified_{safe_env_name}_user"
        
        return updated_vars
    
    def _remove_environment_from_project_config(self, env_name: str) -> None:
        """Remove environment from project configuration."""
        try:
            project_config = self.config_parser.load_project_config()
            
            if env_name in project_config.environments:
                del project_config.environments[env_name]
                self.poststack_config.save_project_config(project_config)
                logger.debug(f"Removed environment '{env_name}' from project configuration")
            
        except Exception as e:
            logger.error(f"Failed to remove environment from project config: {e}")
    
    def _environment_exists(self, env_name: str) -> bool:
        """Check if an environment exists."""
        try:
            self.config_parser.get_environment_config(env_name)
            return True
        except ValueError:
            return False
    
    def _get_environment_status(self, env_name: str) -> str:
        """Get the current status of an environment."""
        try:
            # Check container status directly instead of recursive subprocess calls
            result = subprocess.run(
                ["podman", "ps", "--format", "{{.Names}}:{{.State}}", "--filter", f"name=unified-{env_name}-"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                # If any containers are running, environment is running
                for line in result.stdout.strip().split('\n'):
                    if line and ':' in line:
                        name, state = line.split(':', 1)
                        if state.strip().lower() == 'running':
                            return "running"
                return "stopped"
            else:
                return "stopped"
                
        except Exception:
            return "unknown"
    
    def _stop_environment(self, env_name: str, force: bool = False) -> bool:
        """Stop an environment."""
        try:
            cmd = ["poststack", "env", "stop", env_name]
            if force:
                cmd.append("--rm")
            
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for stopping
            )
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Failed to stop environment '{env_name}': {e}")
            return False
    
    def _remove_environment_resources(self, env_name: str, force: bool = False) -> None:
        """Remove containers and volumes for an environment."""
        try:
            # Remove containers with pattern matching
            self._remove_containers_by_pattern(f"unified-{env_name}-*", force)
            
            # Remove volumes with pattern matching  
            self._remove_volumes_by_pattern(f"unified-{env_name}-*", force)
            
        except Exception as e:
            logger.error(f"Failed to remove resources for environment '{env_name}': {e}")
            if not force:
                raise
    
    def _remove_containers_by_pattern(self, pattern: str, force: bool = False) -> None:
        """Remove containers matching a pattern."""
        try:
            # List containers matching pattern
            result = subprocess.run(
                ["podman", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name={pattern}"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                container_names = result.stdout.strip().split('\n')
                
                for container_name in container_names:
                    if container_name.strip():
                        cmd = ["podman", "rm"]
                        if force:
                            cmd.append("-f")
                        cmd.append(container_name.strip())
                        
                        subprocess.run(cmd, capture_output=True, timeout=60)
                        logger.debug(f"Removed container: {container_name}")
            
        except Exception as e:
            logger.warning(f"Failed to remove containers with pattern '{pattern}': {e}")
    
    def _remove_volumes_by_pattern(self, pattern: str, force: bool = False) -> None:
        """Remove volumes matching a pattern."""
        try:
            # List volumes matching pattern
            result = subprocess.run(
                ["podman", "volume", "ls", "--format", "{{.Name}}", "--filter", f"name={pattern}"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                volume_names = result.stdout.strip().split('\n')
                
                for volume_name in volume_names:
                    if volume_name.strip():
                        cmd = ["podman", "volume", "rm"]
                        if force:
                            cmd.append("-f")
                        cmd.append(volume_name.strip())
                        
                        subprocess.run(cmd, capture_output=True, timeout=60)
                        logger.debug(f"Removed volume: {volume_name}")
            
        except Exception as e:
            logger.warning(f"Failed to remove volumes with pattern '{pattern}': {e}")
    
    def _remove_environment_databases(self, env_name: str) -> None:
        """Remove databases for an environment."""
        try:
            # Replace hyphens with underscores for valid database names
            safe_env_name = env_name.replace('-', '_')
            db_name = f"unified_{safe_env_name}"
            
            # Use poststack db command to drop database
            result = subprocess.run(
                ["poststack", "db", "shell", "--command", f"DROP DATABASE IF EXISTS {db_name};"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.debug(f"Removed database: {db_name}")
            else:
                logger.warning(f"Failed to remove database '{db_name}': {result.stderr}")
                
        except Exception as e:
            logger.warning(f"Failed to remove databases for environment '{env_name}': {e}")
    
    def _cleanup_failed_copy(self, env_name: str) -> None:
        """Clean up resources from a failed environment copy."""
        logger.info(f"Cleaning up failed copy: {env_name}")
        
        try:
            # Deallocate ports
            self.port_allocator.deallocate_ports_for_environment(env_name)
            
            # Remove from project config if it was added
            self._remove_environment_from_project_config(env_name)
            
        except Exception as e:
            logger.error(f"Failed to cleanup failed copy '{env_name}': {e}")