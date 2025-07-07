"""
Phase 5: Container Runtime Verification

Provides specialized container runtime management for PostgreSQL and Liquibase
containers with health checks, side effects verification, and lifecycle management.
"""

import logging
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
        container_name: str = "poststack-postgres",
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
                
                if is_postgres and (is_poststack or any('poststack-postgres' in name for name in names)):
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
        
        # Prefer containers with 'poststack-postgres' in the name
        for container in containers:
            if 'poststack-postgres' in container['container_name']:
                logger.info(f"Using primary PostgreSQL container: {container['container_name']}")
                return container['database_url']
        
        # Fallback to first available container
        if containers:
            container = containers[0]
            logger.info(f"Using PostgreSQL container: {container['container_name']}")
            return container['database_url']
        
        return None


class LiquibaseRunner(ContainerRunner):
    """
    Specialized container runner for Liquibase containers.
    
    Provides Liquibase-specific operations for schema management including
    running migrations, rollbacks, and status checks.
    """
    
    def __init__(self, config: PoststackConfig, log_handler: Optional[SubprocessLogHandler] = None):
        """Initialize Liquibase container runner."""
        super().__init__(config, log_handler)
        
    def run_liquibase_command(
        self,
        command: str,
        database_url: str,
        changelog_file: str = "/data/liquibase/changelogs/master.xml",
        container_name: str = "poststack-liquibase-temp",
        image_name: str = "poststack/liquibase:latest",
        timeout: int = 300,
    ) -> RuntimeResult:
        """
        Run a Liquibase command using a temporary container.
        
        Args:
            command: Liquibase command to run (e.g., "update", "status", "rollback")
            database_url: PostgreSQL connection URL
            changelog_file: Path to Liquibase changelog file
            container_name: Temporary container name
            image_name: Liquibase image to use
            timeout: Command timeout in seconds
            
        Returns:
            RuntimeResult with command execution details
        """
        logger.info(f"Running Liquibase command: {command}")
        
        # Parse database URL for environment variables
        env_vars = self._parse_database_url(database_url)
        env_vars.update({
            "LIQUIBASE_CHANGELOG_FILE": changelog_file,
            "LIQUIBASE_LOG_LEVEL": "INFO",
        })
        
        # Start temporary container with Liquibase command
        cmd_args = [command]
        
        result = RuntimeResult(
            container_name=container_name,
            image_name=image_name,
            status=RuntimeStatus.STARTING,
            environment=env_vars,
        )
        
        try:
            # Build run command
            run_cmd = [
                self.container_runtime,
                "run",
                "--rm",  # Remove container when done
                "--name", container_name,
            ]
            
            # Add volume mount for changelog file if needed
            from pathlib import Path
            changelog_path = Path(changelog_file)
            if changelog_path.exists():
                # Mount the directory containing the changelog
                changelog_dir = changelog_path.parent
                container_changelog_dir = "/tmp/changelog"
                container_changelog_file = f"{container_changelog_dir}/{changelog_path.name}"
                
                run_cmd.extend(["-v", f"{changelog_dir}:{container_changelog_dir}:ro"])
                
                # Update the environment variable to point to the mounted location
                env_vars["LIQUIBASE_CHANGELOG_FILE"] = "changelog.xml"
                logger.debug(f"Mounting changelog: {changelog_dir} -> {container_changelog_dir}")
            
            # Add environment variables
            for env_name, env_value in env_vars.items():
                run_cmd.extend(["-e", f"{env_name}={env_value}"])
                
            # Add image and command
            run_cmd.append(image_name)
            run_cmd.extend(cmd_args)
            
            logger.info(f"Liquibase command: {' '.join(run_cmd)}")
            logger.debug(f"Changelog file exists: {changelog_path.exists()}")
            if changelog_path.exists():
                logger.debug(f"Changelog size: {changelog_path.stat().st_size} bytes")
            
            # Execute command
            start_time = time.time()
            process = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            execution_time = time.time() - start_time
            
            # Update result
            if process.returncode == 0:
                result.mark_started("temp")
                result.mark_stopped(process.returncode)
                logger.info(f"Liquibase {command} completed successfully in {execution_time:.1f}s")
            else:
                result.status = RuntimeStatus.FAILED
                logger.error(f"Liquibase {command} failed with exit code {process.returncode}")
                
            # Add output to result
            if process.stdout:
                result.add_logs(process.stdout)
            if process.stderr:
                result.add_logs(process.stderr)
                
            return result
            
        except subprocess.TimeoutExpired:
            result.status = RuntimeStatus.FAILED
            result.add_logs(f"Liquibase command timed out after {timeout} seconds")
            logger.error(f"Liquibase {command} timed out")
            return result
            
        except Exception as e:
            result.status = RuntimeStatus.FAILED
            result.add_logs(f"Liquibase command failed: {e}")
            logger.error(f"Liquibase {command} exception: {e}")
            return result
    
    def health_check_liquibase(
        self,
        database_url: str,
        changelog_file: str = "/data/liquibase/changelogs/master.xml",
    ) -> HealthCheckResult:
        """
        Perform health check by running Liquibase status command.
        
        Args:
            database_url: PostgreSQL connection URL
            changelog_file: Path to Liquibase changelog file
            
        Returns:
            HealthCheckResult with Liquibase status
        """
        start_time = time.time()
        
        try:
            result = self.run_liquibase_command(
                command="status",
                database_url=database_url,
                changelog_file=changelog_file,
                timeout=60,
            )
            
            response_time = time.time() - start_time
            
            if result.success:
                return HealthCheckResult(
                    container_name="liquibase-health-check",
                    check_type="liquibase_health",
                    passed=True,
                    message="Liquibase status check passed",
                    response_time=response_time,
                    details={"changelog": changelog_file},
                )
            else:
                return HealthCheckResult(
                    container_name="liquibase-health-check",
                    check_type="liquibase_health",
                    passed=False,
                    message=f"Liquibase status check failed: {result.logs}",
                    response_time=response_time,
                )
                
        except Exception as e:
            return HealthCheckResult(
                container_name="liquibase-health-check",
                check_type="liquibase_health",
                passed=False,
                message=f"Liquibase health check exception: {e}",
                response_time=time.time() - start_time,
            )
    
    def verify_liquibase_side_effects(
        self, database_url: str, expected_tables: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """
        Verify expected side effects of Liquibase operations.
        
        Args:
            database_url: PostgreSQL connection URL
            expected_tables: List of tables that should exist after migrations
            
        Returns:
            Dictionary of side effect checks and their results
        """
        results = {}
        expected_tables = expected_tables or ["databasechangelog", "databasechangeloglock"]
        
        # Check if Liquibase tracking tables exist
        for table in expected_tables:
            try:
                # Use psql in a temporary container to check table existence
                check_cmd = [
                    self.container_runtime,
                    "run",
                    "--rm",
                    "poststack/postgres:latest",
                    "psql",
                    database_url,
                    "-c",
                    f"SELECT 1 FROM {table} LIMIT 1;",
                ]
                
                result = subprocess.run(check_cmd, capture_output=True, timeout=30)
                results[f"table_{table}"] = result.returncode == 0
                
            except Exception:
                results[f"table_{table}"] = False
                
        logger.debug(f"Liquibase side effects verification: {results}")
        return results
    
    def _parse_database_url(self, database_url: str) -> Dict[str, str]:
        """Parse database URL into environment variables for Liquibase."""
        # Simple URL parsing for postgresql://user:pass@host:port/database
        try:
            # Remove protocol
            url_part = database_url.replace("postgresql://", "")
            
            # Split user:pass and host:port/database
            if "@" in url_part:
                user_pass, host_db = url_part.split("@", 1)
                if ":" in user_pass:
                    user, password = user_pass.split(":", 1)
                else:
                    user, password = user_pass, ""
            else:
                user, password = "postgres", ""
                host_db = url_part
                
            # Split host:port and database
            if "/" in host_db:
                host_port, database = host_db.split("/", 1)
            else:
                host_port, database = host_db, "postgres"
                
            # Split host and port
            if ":" in host_port:
                host, port = host_port.split(":", 1)
            else:
                host, port = host_port, "5432"
                
            # For container-to-host communication, replace localhost with host IP
            if host in ["localhost", "127.0.0.1"]:
                import subprocess
                try:
                    # Get host IP for container networking
                    result = subprocess.run(
                        ["ip", "route", "get", "1.1.1.1"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        for part in result.stdout.split():
                            if part.startswith("src"):
                                continue
                            # Look for IP after 'src'
                            parts = result.stdout.split()
                            if "src" in parts:
                                src_index = parts.index("src")
                                if src_index + 1 < len(parts):
                                    host_ip = parts[src_index + 1]
                                    logger.info(f"Using host IP {host_ip} for container connectivity")
                                    host = host_ip
                                    break
                except Exception as e:
                    logger.warning(f"Could not determine host IP, using localhost: {e}")
                
            # Convert to JDBC URL format for Liquibase
            jdbc_url = f"jdbc:postgresql://{host}:{port}/{database}"
            
            return {
                "DATABASE_HOST": host,
                "DATABASE_PORT": port,
                "DATABASE_NAME": database,
                "DATABASE_USER": user,
                "DATABASE_PASSWORD": password,
                "DATABASE_URL": jdbc_url,
            }
            
        except Exception as e:
            logger.error(f"Failed to parse database URL: {e}")
            return {
                "DATABASE_URL": database_url,
            }


class ContainerLifecycleManager:
    """
    Manages complete container lifecycle including startup, health monitoring, and cleanup.
    
    Coordinates PostgreSQL and Liquibase containers for integrated testing scenarios.
    """
    
    def __init__(self, config: PoststackConfig):
        """Initialize container lifecycle manager."""
        self.config = config
        self.postgres_runner = PostgreSQLRunner(config)
        self.liquibase_runner = LiquibaseRunner(config)
        self.running_containers: List[str] = []
        
    def start_test_environment(
        self,
        postgres_port: int = 5433,  # Use non-standard port for testing
        cleanup_on_failure: bool = True,
    ) -> Tuple[RuntimeResult, Optional[HealthCheckResult]]:
        """
        Start a complete test environment with PostgreSQL.
        
        Args:
            postgres_port: Port for PostgreSQL container
            cleanup_on_failure: Clean up containers if startup fails
            
        Returns:
            Tuple of (PostgreSQL RuntimeResult, Health check result)
        """
        logger.info("Starting test environment...")
        
        postgres_container = "poststack-postgres-test"
        
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