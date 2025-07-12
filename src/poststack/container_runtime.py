"""
Phase 5: Container Runtime Verification

Provides specialized container runtime management for PostgreSQL
containers with health checks, side effects verification, and lifecycle management.
"""

import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import PoststackConfig
from .container_management import ContainerRunner
from .logging_config import SubprocessLogHandler
from .models import HealthCheckResult, RuntimeResult, RuntimeStatus

logger = logging.getLogger(__name__)


class PostgreSQLRunner(ContainerRunner):
    """
    Specialized container runner for PostgreSQL containers.
    
    Provides PostgreSQL-specific configuration, health checks, and side effects
    verification including database connectivity, port availability, and file system setup.
    """
    
    def __init__(self, config: PoststackConfig, log_handler: Optional[SubprocessLogHandler] = None):
        """Initialize PostgreSQL container runner."""
        super().__init__(config, log_handler)
        self.default_port = 5432
        self.default_database = "poststack"
        self.default_user = "poststack"
        
    def start_postgres_container(
        self,
        container_name: Optional[str] = None,
        image_name: str = "poststack/postgres:latest",
        port: int = 5432,
        database_name: str = "poststack",
        username: str = "poststack",
        password: str = "poststack_dev",
        data_volume: Optional[str] = None,
        config_volume: Optional[str] = None,
        wait_for_ready: bool = True,
        timeout: int = 120,
    ) -> RuntimeResult:
        """
        Start a PostgreSQL container with proper configuration.
        
        Args:
            container_name: Name for the PostgreSQL container
            image_name: PostgreSQL image to use
            port: Host port to map to PostgreSQL (default: 5432)
            database_name: Name of database to create
            username: PostgreSQL username
            password: PostgreSQL password
            data_volume: Host path for data persistence
            config_volume: Host path for configuration files
            wait_for_ready: Wait for PostgreSQL to be ready before returning
            timeout: Total timeout for startup and readiness
            
        Returns:
            RuntimeResult with PostgreSQL container status
        """
        # Use configured container name if not provided
        if container_name is None:
            container_name = self.config.postgres_container_name
            
        logger.info(f"Starting PostgreSQL container: {container_name}")
        
        # Prepare environment variables
        environment = {
            "POSTGRES_DB": database_name,
            "POSTGRES_USER": username,
            "POSTGRES_PASSWORD": password,
            "POSTGRES_HOST_AUTH_METHOD": "trust",  # For development
            "PGDATA": "/data/postgres/data",
        }
        
        # Prepare port mappings
        ports = {str(port): "5432"}
        
        # Prepare volume mappings
        volumes = {}
        if data_volume:
            volumes[data_volume] = "/data/postgres/data"
        if config_volume:
            volumes[config_volume] = "/data/postgres/config"
            
        # Start the container
        result = self.start_container(
            container_name=container_name,
            image_name=image_name,
            ports=ports,
            volumes=volumes,
            environment=environment,
            detached=True,
            remove_on_exit=False,
            timeout=60,
        )
        
        if not result.success:
            return result
            
        # Wait for PostgreSQL to be ready if requested
        if wait_for_ready:
            logger.info("Waiting for PostgreSQL to be ready...")
            ready_result = self.wait_for_postgres_ready(
                container_name, port, database_name, username, timeout - 60
            )
            
            if not ready_result.passed:
                logger.error(f"PostgreSQL failed to become ready: {ready_result.message}")
                result.status = RuntimeStatus.FAILED
                result.add_logs(f"Readiness check failed: {ready_result.message}")
                
        return result
    
    def wait_for_postgres_ready(
        self,
        container_name: str,
        port: int,
        database_name: str,
        username: str,
        timeout: int = 60,
    ) -> HealthCheckResult:
        """
        Wait for PostgreSQL to be ready to accept connections.
        
        Args:
            container_name: Name of PostgreSQL container
            port: PostgreSQL port
            database_name: Database name to test
            username: Username for connection
            timeout: Maximum time to wait
            
        Returns:
            HealthCheckResult indicating readiness status
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if container is still running
            status = self.get_container_status(container_name)
            if not status or not status.running:
                return HealthCheckResult(
                    container_name=container_name,
                    check_type="postgres_ready",
                    passed=False,
                    message="Container is not running",
                    response_time=time.time() - start_time,
                )
            
            # Try to connect to PostgreSQL
            check_result = self.health_check_postgres(
                container_name, port, database_name, username
            )
            
            if check_result.passed:
                return check_result
                
            # Wait before retry
            time.sleep(2)
            
        return HealthCheckResult(
            container_name=container_name,
            check_type="postgres_ready",
            passed=False,
            message=f"PostgreSQL not ready after {timeout} seconds",
            response_time=time.time() - start_time,
        )
    
    def health_check_postgres(
        self,
        container_name: str,
        port: int = 5432,
        database_name: str = "poststack",
        username: str = "poststack",
    ) -> HealthCheckResult:
        """
        Perform comprehensive health check on PostgreSQL container.
        
        Args:
            container_name: Name of PostgreSQL container
            port: PostgreSQL port
            database_name: Database name to test
            username: Username for connection
            
        Returns:
            HealthCheckResult with detailed health information
        """
        start_time = time.time()
        
        # First check if container is running
        basic_check = self.health_check(container_name, "running")
        if not basic_check.passed:
            return basic_check
            
        # Check port connectivity
        port_check = self.check_port_availability("localhost", port)
        if not port_check:
            return HealthCheckResult(
                container_name=container_name,
                check_type="postgres_health",
                passed=False,
                message=f"PostgreSQL port {port} not accessible",
                response_time=time.time() - start_time,
            )
        
        # Try database connection using pg_isready
        try:
            cmd = [
                self.container_runtime,
                "exec",
                container_name,
                "pg_isready",
                "-h", "localhost",
                "-p", "5432",
                "-d", database_name,
                "-U", username,
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                return HealthCheckResult(
                    container_name=container_name,
                    check_type="postgres_health",
                    passed=True,
                    message="PostgreSQL is healthy and accepting connections",
                    response_time=time.time() - start_time,
                    details={
                        "port": str(port),
                        "database": database_name,
                        "user": username,
                    },
                )
            else:
                return HealthCheckResult(
                    container_name=container_name,
                    check_type="postgres_health",
                    passed=False,
                    message=f"pg_isready failed: {result.stderr}",
                    response_time=time.time() - start_time,
                )
                
        except Exception as e:
            return HealthCheckResult(
                container_name=container_name,
                check_type="postgres_health",
                passed=False,
                message=f"Health check failed: {e}",
                response_time=time.time() - start_time,
            )
    
    def verify_postgres_side_effects(
        self, container_name: str, expected_port: int = 5432
    ) -> Dict[str, bool]:
        """
        Verify expected side effects of running PostgreSQL container.
        
        Args:
            container_name: Name of PostgreSQL container
            expected_port: Expected PostgreSQL port
            
        Returns:
            Dictionary of side effect checks and their results
        """
        results = {}
        
        # Check if PostgreSQL process is running in container
        try:
            cmd = [
                self.container_runtime,
                "exec",
                container_name,
                "pgrep",
                "-f",
                "postgres:",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            results["postgres_process"] = result.returncode == 0
        except Exception:
            results["postgres_process"] = False
            
        # Check if PostgreSQL port is listening
        results["port_listening"] = self.check_port_availability("localhost", expected_port)
        
        # Check if data directory exists and has proper permissions
        try:
            cmd = [
                self.container_runtime,
                "exec",
                container_name,
                "test",
                "-d",
                "/data/postgres/data",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            results["data_directory"] = result.returncode == 0
        except Exception:
            results["data_directory"] = False
            
        # Check if PostgreSQL is accepting connections
        try:
            cmd = [
                self.container_runtime,
                "exec",
                container_name,
                "pg_isready",
                "-h", "localhost",
                "-p", "5432",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            results["accepting_connections"] = result.returncode == 0
        except Exception:
            results["accepting_connections"] = False
            
        logger.debug(f"PostgreSQL side effects verification: {results}")
        return results
    
    def check_port_availability(self, host: str, port: int) -> bool:
        """Check if a port is available/listening."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                result = sock.connect_ex((host, port))
                return result == 0
        except Exception:
            return False
    
    def get_running_postgres_containers(self) -> List[Dict[str, str]]:
        """Get list of running PostgreSQL containers with their connection details."""
        try:
            # List all running containers
            cmd = [self.container_runtime, "ps", "--format", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.warning(f"Failed to list containers: {result.stderr}")
                return []
            
            import json
            containers_data = result.stdout.strip()
            if not containers_data:
                return []
            
            # Parse JSON output (podman returns a JSON array)
            try:
                containers = json.loads(containers_data)
                if not isinstance(containers, list):
                    containers = [containers]
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse container JSON: {containers_data}")
                return []
            
            postgres_containers = []
            for container in containers:
                # Look for poststack PostgreSQL containers
                names = container.get('Names', [])
                image = container.get('Image', '')
                
                # Check if this looks like a poststack postgres container
                is_postgres = (
                    any('postgres' in name.lower() for name in names) or
                    'postgres' in image.lower()
                )
                
                is_poststack = (
                    any('poststack' in name.lower() for name in names) or
                    'poststack' in image.lower()
                )
                
                if is_postgres and (is_poststack or any(self.config.postgres_container_name in name for name in names)):
                    # Extract connection details
                    container_details = self._extract_postgres_connection_info(container)
                    if container_details:
                        postgres_containers.append(container_details)
            
            logger.info(f"Found {len(postgres_containers)} running PostgreSQL containers")
            return postgres_containers
            
        except Exception as e:
            logger.error(f"Failed to get running PostgreSQL containers: {e}")
            return []
    
    def _extract_postgres_connection_info(self, container_info: Dict) -> Optional[Dict[str, str]]:
        """Extract PostgreSQL connection information from container info."""
        try:
            names = container_info.get('Names', [])
            container_name = names[0] if names else container_info.get('Id', '')[:12]
            
            # Get port mappings
            ports = container_info.get('Ports', [])
            postgres_port = None
            
            for port_info in ports:
                if isinstance(port_info, dict):
                    # Look for PostgreSQL port (5432)
                    if port_info.get('container_port') == 5432:
                        postgres_port = port_info.get('host_port')
                        break
                    # Also check for PrivatePort/PublicPort format (docker compatibility)
                    elif port_info.get('PrivatePort') == 5432:
                        postgres_port = port_info.get('PublicPort')
                        break
                elif isinstance(port_info, str):
                    # Parse string format "0.0.0.0:5434->5432/tcp"
                    if '5432' in port_info:
                        parts = port_info.split(':')
                        if len(parts) >= 2:
                            port_part = parts[1].split('->')[0]
                            try:
                                postgres_port = int(port_part)
                            except ValueError:
                                continue
            
            if not postgres_port:
                logger.warning(f"Could not determine port for container {container_name}")
                return None
            
            # Try to get environment variables from the container
            env_info = self._get_container_environment(container_name)
            
            database_name = env_info.get('POSTGRES_DB', 'poststack')
            username = env_info.get('POSTGRES_USER', 'poststack')
            password = env_info.get('POSTGRES_PASSWORD', 'poststack_dev')
            
            # Build database URL
            database_url = f"postgresql://{username}:{password}@localhost:{postgres_port}/{database_name}"
            
            return {
                'container_name': container_name,
                'host': 'localhost',
                'port': str(postgres_port),
                'database': database_name,
                'username': username,
                'password': password,
                'database_url': database_url
            }
            
        except Exception as e:
            logger.error(f"Failed to extract connection info: {e}")
            return None
    
    def _get_container_environment(self, container_name: str) -> Dict[str, str]:
        """Get environment variables from a running container."""
        try:
            cmd = [self.container_runtime, "inspect", container_name, "--format", "{{json .Config.Env}}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                logger.warning(f"Could not inspect container {container_name}: {result.stderr}")
                return {}
            
            import json
            env_list = json.loads(result.stdout.strip())
            
            # Convert list of "KEY=value" strings to dict
            env_dict = {}
            for env_var in env_list:
                if '=' in env_var:
                    key, value = env_var.split('=', 1)
                    env_dict[key] = value
            
            return env_dict
            
        except Exception as e:
            logger.warning(f"Failed to get environment for {container_name}: {e}")
            return {}
    
    def get_primary_postgres_url(self) -> Optional[str]:
        """Get database URL for the primary PostgreSQL container."""
        containers = self.get_running_postgres_containers()
        
        if not containers:
            return None
        
        # Prefer containers with configured postgres name in the name
        for container in containers:
            if self.config.postgres_container_name in container['container_name']:
                logger.info(f"Using primary PostgreSQL container: {container['container_name']}")
                return container['database_url']
        
        # Fallback to first available container
        if containers:
            container = containers[0]
            logger.info(f"Using PostgreSQL container: {container['container_name']}")
            return container['database_url']
        
        return None
    
    def list_postgres_containers(self) -> List[Dict[str, str]]:
        """
        List all PostgreSQL containers (both running and stopped).
        
        Returns:
            List of dictionaries containing container information
        """
        try:
            # Get both running and stopped containers
            cmd = [self.container_runtime, "ps", "-a", "--format", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.warning(f"Failed to list containers: {result.stderr}")
                return []
            
            import json
            containers_data = result.stdout.strip()
            if not containers_data:
                return []
            
            # Parse JSON output
            try:
                containers = json.loads(containers_data)
                if not isinstance(containers, list):
                    containers = [containers]
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse container JSON: {containers_data}")
                return []
            
            postgres_containers = []
            for container in containers:
                # Look for poststack PostgreSQL containers
                names = container.get('Names', [])
                image = container.get('Image', '')
                
                # Check if this looks like a poststack postgres container
                is_postgres = (
                    any('postgres' in name.lower() for name in names) or
                    'postgres' in image.lower()
                )
                
                is_poststack = (
                    any('poststack' in name.lower() for name in names) or
                    'poststack' in image.lower()
                )
                
                if is_postgres and (is_poststack or any(self.config.postgres_container_name in name for name in names)):
                    # Extract basic container info
                    container_name = names[0] if names else container.get('Id', '')[:12]
                    status = container.get('State', container.get('Status', 'unknown'))
                    
                    # Get port info if running
                    host_port = None
                    database = None
                    if status.lower() in ['running', 'up']:
                        connection_info = self._extract_postgres_connection_info(container)
                        if connection_info:
                            host_port = connection_info.get('port')
                            database = connection_info.get('database')
                    
                    postgres_containers.append({
                        'name': container_name,
                        'status': status,
                        'image': image,
                        'host_port': host_port,
                        'database': database
                    })
            
            logger.debug(f"Found {len(postgres_containers)} PostgreSQL containers")
            return postgres_containers
            
        except Exception as e:
            logger.error(f"Failed to list PostgreSQL containers: {e}")
            return []
    
    def stop_postgres_container(self, container_name: str) -> bool:
        """
        Stop a PostgreSQL container by name.
        
        Args:
            container_name: Name of the container to stop
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Stopping PostgreSQL container: {container_name}")
            
            # First try to stop gracefully
            cmd = [self.container_runtime, "stop", container_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"Successfully stopped PostgreSQL container: {container_name}")
                return True
            else:
                logger.warning(f"Failed to stop container {container_name}: {result.stderr}")
                
                # Try to force stop if graceful stop failed
                logger.info(f"Attempting force stop for container: {container_name}")
                force_cmd = [self.container_runtime, "stop", "-t", "5", container_name]
                force_result = subprocess.run(force_cmd, capture_output=True, text=True, timeout=10)
                
                if force_result.returncode == 0:
                    logger.info(f"Force stopped PostgreSQL container: {container_name}")
                    return True
                else:
                    logger.error(f"Failed to force stop container {container_name}: {force_result.stderr}")
                    return False
                    
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout stopping PostgreSQL container: {container_name}")
            return False
        except Exception as e:
            logger.error(f"Error stopping PostgreSQL container {container_name}: {e}")
            return False
    
    def restart_postgres_container(self, container_name: str) -> bool:
        """
        Restart an existing stopped PostgreSQL container.
        
        Args:
            container_name: Name of the container to restart
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Restarting PostgreSQL container: {container_name}")
            
            cmd = [self.container_runtime, "restart", container_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"Successfully restarted PostgreSQL container: {container_name}")
                return True
            else:
                logger.error(f"Failed to restart container {container_name}: {result.stderr}")
                return False
                    
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout restarting PostgreSQL container: {container_name}")
            return False
        except Exception as e:
            logger.error(f"Error restarting PostgreSQL container {container_name}: {e}")
            return False
    
    def remove_postgres_container(self, container_name: str, force: bool = True) -> bool:
        """
        Remove a PostgreSQL container.
        
        Args:
            container_name: Name of the container to remove
            force: Use force removal if container is running
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Removing PostgreSQL container: {container_name}")
            
            cmd = [self.container_runtime, "rm", container_name]
            if force:
                cmd.insert(-1, "--force")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info(f"Successfully removed PostgreSQL container: {container_name}")
                return True
            else:
                logger.warning(f"Failed to remove container {container_name}: {result.stderr}")
                return False
                    
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout removing PostgreSQL container: {container_name}")
            return False
        except Exception as e:
            logger.error(f"Error removing PostgreSQL container {container_name}: {e}")
            return False
    
    def find_postgres_container_by_env(self, container_name_or_pattern: str) -> Optional[Dict]:
        """
        Find postgres container by name or pattern.
        
        Args:
            container_name_or_pattern: Exact container name or pattern to search for
            
        Returns:
            Dict with container info if found, None otherwise
        """
        try:
            # Get all postgres containers
            all_postgres = self.list_postgres_containers()
            
            # First try exact name match
            for container in all_postgres:
                if container.get('name') == container_name_or_pattern:
                    return container
            
            # Then try pattern matching
            for container in all_postgres:
                name = container.get('name', '')
                if container_name_or_pattern in name:
                    return container
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding postgres container for {container_name_or_pattern}: {e}")
            return None




class ProjectContainerRunner(ContainerRunner):
    """
    Specialized container runner for project-level custom containers.
    
    Provides project container lifecycle management with configurable names,
    ports, and environment variables.
    """
    
    def __init__(self, config: PoststackConfig, log_handler: Optional[SubprocessLogHandler] = None):
        """Initialize project container runner."""
        super().__init__(config, log_handler)
        
    def start_project_container(
        self,
        container_name: str,
        image_name: str,
        port_mappings: Optional[Dict[int, int]] = None,
        environment: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, str]] = None,
        wait_for_ready: bool = False,
        timeout: int = 60,
    ) -> RuntimeResult:
        """
        Start a project container with custom configuration.
        
        Args:
            container_name: Short name for the container (will be prefixed)
            image_name: Container image to use
            port_mappings: Dict of {host_port: container_port}
            environment: Environment variables for the container
            volumes: Volume mappings {host_path: container_path}
            wait_for_ready: Wait for container to be ready
            timeout: Total timeout for startup
            
        Returns:
            RuntimeResult with container status
        """
        # Get full container name with project prefix
        full_container_name = self.config.get_project_container_name(container_name)
        
        # Get container-specific configuration from environment
        custom_port = self.config.get_project_container_env_var(container_name, 'port')
        custom_name = self.config.get_project_container_env_var(container_name, 'container_name')
        
        # Use custom name if specified
        if custom_name:
            full_container_name = custom_name
            
        logger.info(f"Starting project container: {full_container_name}")
        
        # Prepare default environment
        container_env = environment or {}
        
        # Add project-specific environment variables
        project_env = {}
        for key, value in os.environ.items():
            if key.startswith(f"POSTSTACK_{container_name.upper()}_ENV_"):
                env_key = key.replace(f"POSTSTACK_{container_name.upper()}_ENV_", "")
                project_env[env_key] = value
        
        container_env.update(project_env)
        
        # Prepare port mappings
        ports = {}
        if port_mappings:
            for host_port, container_port in port_mappings.items():
                # Check for custom port override
                if custom_port and host_port == list(port_mappings.keys())[0]:
                    host_port = custom_port
                ports[str(host_port)] = str(container_port)
        
        # Prepare volumes
        container_volumes = volumes or {}
        
        # Start the container
        result = self.start_container(
            container_name=full_container_name,
            image_name=image_name,
            ports=ports,
            volumes=container_volumes,
            environment=container_env,
            detached=True,
            remove_on_exit=False,
            timeout=timeout,
        )
        
        if not result.success:
            return result
            
        # Wait for container to be ready if requested
        if wait_for_ready:
            logger.info(f"Waiting for {container_name} to be ready...")
            ready_result = self.wait_for_container_ready(
                full_container_name, timeout - 30
            )
            
            if not ready_result.passed:
                logger.error(f"Container {container_name} failed to become ready: {ready_result.message}")
                result.status = RuntimeStatus.FAILED
                result.add_logs(f"Readiness check failed: {ready_result.message}")
                
        return result
    
    def wait_for_container_ready(
        self,
        container_name: str,
        timeout: int = 30,
    ) -> HealthCheckResult:
        """
        Wait for container to be ready and running.
        
        Args:
            container_name: Name of container
            timeout: Maximum time to wait
            
        Returns:
            HealthCheckResult indicating readiness status
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if container is still running
            status = self.get_container_status(container_name)
            if status and status.running:
                return HealthCheckResult(
                    container_name=container_name,
                    check_type="container_ready",
                    passed=True,
                    message="Container is running",
                    response_time=time.time() - start_time,
                )
            elif status and not status.running:
                return HealthCheckResult(
                    container_name=container_name,
                    check_type="container_ready",
                    passed=False,
                    message=f"Container stopped: {status.status.value}",
                    response_time=time.time() - start_time,
                )
                
            # Wait before retry
            time.sleep(2)
            
        return HealthCheckResult(
            container_name=container_name,
            check_type="container_ready",
            passed=False,
            message=f"Container not ready after {timeout} seconds",
            response_time=time.time() - start_time,
        )
    
    def get_running_project_containers(self) -> List[Dict[str, str]]:
        """Get information about running project containers."""
        try:
            prefix = self.config.get_project_container_prefix()
            cmd = [
                self.container_runtime,
                "ps",
                "--filter", f"name={prefix}-",
                "--format", "json"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                logger.warning(f"Failed to list project containers: {result.stderr}")
                return []
            
            if not result.stdout.strip():
                return []
            
            import json
            containers = []
            
            # Handle both single object and array responses
            output = result.stdout.strip()
            if output.startswith('['):
                container_list = json.loads(output)
            else:
                # Multiple JSON objects, one per line
                container_list = []
                for line in output.split('\n'):
                    if line.strip():
                        container_list.append(json.loads(line))
            
            for container_info in container_list:
                container_name = container_info.get('Names', [''])[0]
                if container_name.startswith(prefix + '-'):
                    containers.append({
                        'container_name': container_name,
                        'image': container_info.get('Image', ''),
                        'status': container_info.get('Status', ''),
                        'ports': container_info.get('Ports', ''),
                    })
            
            return containers
            
        except Exception as e:
            logger.error(f"Failed to get running project containers: {e}")
            return []


class ContainerLifecycleManager:
    """
    Manages complete container lifecycle including startup, health monitoring, and cleanup.
    
    Coordinates PostgreSQL containers for integrated testing scenarios.
    """
    
    def __init__(self, config: PoststackConfig):
        """Initialize container lifecycle manager."""
        self.config = config
        self.postgres_runner = PostgreSQLRunner(config)
        self.project_runner = ProjectContainerRunner(config)
        self.running_containers: List[str] = []
        
    def start_test_environment(
        self,
        postgres_port: Optional[int] = None,
        cleanup_on_failure: bool = True,
    ) -> Tuple[RuntimeResult, Optional[HealthCheckResult]]:
        """
        Start a complete PostgreSQL environment.
        
        Args:
            postgres_port: Port for PostgreSQL container (uses config default if None)
            cleanup_on_failure: Clean up containers if startup fails
            
        Returns:
            Tuple of (PostgreSQL RuntimeResult, Health check result)
        """
        logger.info("Starting PostgreSQL environment...")
        
        # Use configured container name directly (no -test suffix)
        postgres_container = self.config.postgres_container_name
        
        # Use configured port if not specified
        if postgres_port is None:
            postgres_port = self.config.postgres_host_port
        
        try:
            # Start PostgreSQL container
            postgres_result = self.postgres_runner.start_postgres_container(
                container_name=postgres_container,
                port=postgres_port,
                wait_for_ready=True,
                timeout=120,
            )
            
            if postgres_result.success:
                self.running_containers.append(postgres_container)
                
                # Perform comprehensive health check
                health_result = self.postgres_runner.health_check_postgres(
                    container_name=postgres_container,
                    port=postgres_port,
                )
                
                if health_result.passed:
                    logger.info("Test environment started successfully")
                    return postgres_result, health_result
                else:
                    logger.error("Health check failed after startup")
                    if cleanup_on_failure:
                        self.cleanup_test_environment()
                    return postgres_result, health_result
            else:
                logger.error("Failed to start PostgreSQL container")
                if cleanup_on_failure:
                    self.cleanup_test_environment()
                return postgres_result, None
                
        except Exception as e:
            logger.error(f"Test environment startup failed: {e}")
            if cleanup_on_failure:
                self.cleanup_test_environment()
            raise
    
    def cleanup_test_environment(self) -> bool:
        """
        Clean up all running test containers.
        
        Returns:
            True if cleanup was successful
        """
        logger.info("Cleaning up test environment...")
        success = True
        
        for container_name in self.running_containers[:]:
            try:
                # Stop container
                stop_result = self.postgres_runner.stop_container(container_name)
                if stop_result.success:
                    logger.debug(f"Stopped container: {container_name}")
                else:
                    logger.warning(f"Failed to stop container: {container_name}")
                    success = False
                    
                # Remove container
                try:
                    subprocess.run(
                        [self.config.container_runtime, "rm", container_name],
                        capture_output=True,
                        timeout=30,
                    )
                    self.running_containers.remove(container_name)
                    logger.debug(f"Removed container: {container_name}")
                except Exception as e:
                    logger.warning(f"Failed to remove container {container_name}: {e}")
                    success = False
                    
            except Exception as e:
                logger.error(f"Cleanup error for {container_name}: {e}")
                success = False
                
        if success:
            logger.info("Test environment cleanup completed successfully")
        else:
            logger.warning("Test environment cleanup completed with some errors")
            
        return success
    
    def get_running_containers(self) -> List[str]:
        """Get list of containers managed by this lifecycle manager."""
        return self.running_containers.copy()