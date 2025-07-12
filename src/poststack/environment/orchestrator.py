"""
Environment orchestration for Docker Compose and Podman Pod deployments.

Manages the complete lifecycle of environment deployment including:
- PostgreSQL database setup
- Init phase execution and validation
- Main deployment phase
- Status monitoring and error handling
"""

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import EnvironmentConfig, PoststackConfig
from ..container_runtime import PostgreSQLRunner
from .config import EnvironmentConfigParser
from .substitution import VariableSubstitutor, PostgresInfo, create_temp_processed_file, cleanup_temp_file

logger = logging.getLogger(__name__)


@dataclass
class PhaseResult:
    """Result of a deployment phase (init or deploy)."""
    success: bool
    exit_code: int
    duration: float
    logs: str
    command: str
    file_path: str


@dataclass
class EnvironmentResult:
    """Complete result of environment deployment."""
    environment_name: str
    success: bool
    postgres_started: bool
    init_results: List[PhaseResult]
    deployment_result: Optional[PhaseResult]
    error_message: Optional[str] = None
    total_duration: Optional[float] = None


class EnvironmentOrchestrator:
    """Orchestrates complete environment deployment workflows."""
    
    def __init__(self, poststack_config: PoststackConfig):
        """Initialize orchestrator with poststack configuration."""
        self.poststack_config = poststack_config
        self.config_parser = EnvironmentConfigParser(poststack_config)
        self.postgres_runner = PostgreSQLRunner(poststack_config)
        
    async def start_environment(self, env_name: str, init_only: bool = False) -> EnvironmentResult:
        """
        Complete environment startup workflow.
        
        Args:
            env_name: Environment name to start
            init_only: If True, only run init phase
            
        Returns:
            EnvironmentResult with complete deployment status
        """
        start_time = asyncio.get_event_loop().time()
        
        logger.info(f"Starting environment deployment: {env_name}")
        
        try:
            # Load and validate environment configuration
            env_config = self.config_parser.get_environment_config(env_name)
            project_config = self.config_parser.load_project_config()
            
            # Ensure all required volumes exist
            volume_success = await self._ensure_volumes_exist(env_name, env_config, project_config.project.name)
            if not volume_success:
                raise RuntimeError(f"Failed to create required volumes for environment: {env_name}")
            
            # Start PostgreSQL database
            postgres_info = await self._setup_postgres(env_config)
            postgres_started = True
            
            # Create variable substitutor
            substitutor = VariableSubstitutor(env_name, env_config, postgres_info, project_config.project.name)
            
            # Run init phase
            init_results = await self._run_init_phase(env_config, substitutor)
            
            # Check if all init containers succeeded
            init_success = all(result.success for result in init_results)
            if not init_success:
                failed_inits = [r for r in init_results if not r.success]
                error_msg = f"Init phase failed. {len(failed_inits)} container(s) failed to complete successfully."
                logger.error(error_msg)
                return EnvironmentResult(
                    environment_name=env_name,
                    success=False,
                    postgres_started=postgres_started,
                    init_results=init_results,
                    deployment_result=None,
                    error_message=error_msg,
                    total_duration=asyncio.get_event_loop().time() - start_time
                )
            
            # If init_only, stop here
            if init_only:
                logger.info(f"Init phase completed successfully for environment: {env_name}")
                return EnvironmentResult(
                    environment_name=env_name,
                    success=True,
                    postgres_started=postgres_started,
                    init_results=init_results,
                    deployment_result=None,
                    total_duration=asyncio.get_event_loop().time() - start_time
                )
            
            # Run deployment phase
            deployment_result = await self._run_deployment_phase(env_config, substitutor)
            
            success = deployment_result.success if deployment_result else False
            
            logger.info(f"Environment deployment completed: {env_name} (success: {success})")
            
            return EnvironmentResult(
                environment_name=env_name,
                success=success,
                postgres_started=postgres_started,
                init_results=init_results,
                deployment_result=deployment_result,
                total_duration=asyncio.get_event_loop().time() - start_time
            )
            
        except Exception as e:
            logger.error(f"Environment deployment failed: {env_name} - {e}")
            return EnvironmentResult(
                environment_name=env_name,
                success=False,
                postgres_started=False,
                init_results=[],
                deployment_result=None,
                error_message=str(e),
                total_duration=asyncio.get_event_loop().time() - start_time
            )
    
    async def stop_environment(self, env_name: str, keep_postgres: bool = False, remove: bool = False) -> bool:
        """
        Stop all containers for an environment.
        
        Args:
            env_name: Environment name to stop
            keep_postgres: If True, don't stop postgres database
            remove: If True, remove containers after stopping (--rm flag)
            
        Returns:
            True if successful
        """
        action = "Stopping and removing" if remove else "Stopping"
        logger.info(f"{action} environment: {env_name}")
        
        try:
            env_config = self.config_parser.get_environment_config(env_name)
            
            # Stop deployment containers - need to process templates for valid YAML
            if env_config.deployment.compose:
                await self._stop_compose_deployment(env_config.deployment.compose, remove=remove)
            elif env_config.deployment.pod:
                # For pods, we need to create a processed version for stopping
                await self._stop_pod_deployment_with_substitution(env_name, env_config, remove=remove)
            
            # Stop init containers (they should already be stopped, but cleanup just in case)
            for init_ref in env_config.init:
                if init_ref.compose:
                    await self._stop_compose_deployment(init_ref.compose, remove=remove)
                elif init_ref.pod:
                    await self._stop_pod_deployment(init_ref.pod, remove=remove)
            
            # Stop postgres if requested
            if not keep_postgres:
                # Get the actual postgres status to find the correct container name
                postgres_status = self._get_postgres_status(env_name)
                postgres_container_name = postgres_status.get("container_name")
                
                if postgres_container_name and postgres_status.get("status") != "not_running":
                    success = self.postgres_runner.stop_postgres_container(postgres_container_name)
                    if success:
                        logger.info(f"Stopped postgres container: {postgres_container_name}")
                        
                        # Remove container if --rm flag specified
                        if remove:
                            removal_success = self.postgres_runner.remove_postgres_container(postgres_container_name)
                            if removal_success:
                                logger.info(f"Removed postgres container: {postgres_container_name}")
                            else:
                                logger.warning(f"Failed to remove postgres container: {postgres_container_name}")
                    else:
                        logger.warning(f"Failed to stop postgres container: {postgres_container_name}")
                else:
                    logger.info(f"No running postgres container found for environment: {env_name}")
            
            status = "stopped and cleaned" if remove else "stopped"
            logger.info(f"Environment {status}: {env_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop environment {env_name}: {e}")
            return False
    
    async def get_environment_status(self, env_name: str) -> Dict:
        """Get status of all containers in an environment."""
        try:
            env_config = self.config_parser.get_environment_config(env_name)
            
            status = {
                "environment": env_name,
                "postgres": self._get_postgres_status(env_name),
                "init_containers": [],
                "deployment_containers": []
            }
            
            # Check deployment containers
            if env_config.deployment.compose:
                deployment_status = await self._get_compose_status(env_config.deployment.compose)
                status["deployment_containers"] = deployment_status
            elif env_config.deployment.pod:
                deployment_status = await self._get_pod_status(env_config.deployment.pod)
                status["deployment_containers"] = deployment_status
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get environment status for {env_name}: {e}")
            return {"environment": env_name, "error": str(e)}
    
    async def _setup_postgres(self, env_config: EnvironmentConfig) -> PostgresInfo:
        """Setup PostgreSQL database for environment with smart container detection."""
        postgres_config = env_config.postgres
        
        # Generate password if needed
        if postgres_config.password == "auto_generated":
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            actual_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        else:
            actual_password = postgres_config.password
        
        # Container name pattern
        container_name = f"poststack-postgres-{postgres_config.database}"
        
        logger.info(f"Setting up PostgreSQL database: {postgres_config.database} on port {postgres_config.port}")
        
        # Check for existing container (using the actual container name pattern)
        existing_container = self.postgres_runner.find_postgres_container_by_env(container_name)
        
        if existing_container:
            container_status = existing_container.get('status', '').lower()
            existing_name = existing_container.get('name', container_name)
            
            if container_status == 'running':
                logger.info(f"Found running PostgreSQL container: {existing_name}")
                return PostgresInfo(postgres_config, actual_password)
            elif container_status in ['stopped', 'exited']:
                logger.info(f"Found stopped PostgreSQL container {existing_name}, restarting...")
                success = self.postgres_runner.restart_postgres_container(existing_name)
                if success:
                    logger.info(f"Successfully restarted PostgreSQL container: {existing_name}")
                    return PostgresInfo(postgres_config, actual_password)
                else:
                    logger.warning(f"Failed to restart container {existing_name}, removing and recreating...")
                    self.postgres_runner.remove_postgres_container(existing_name, force=True)
            else:
                logger.warning(f"PostgreSQL container {existing_name} in unexpected state '{container_status}', removing and recreating...")
                self.postgres_runner.remove_postgres_container(existing_name, force=True)
        
        # Create new container (either no existing container or cleanup was needed)
        logger.info(f"Creating new PostgreSQL container: {container_name}")
        success = self.postgres_runner.start_postgres_container(
            container_name=container_name,
            port=postgres_config.port,
            database_name=postgres_config.database,
            username=postgres_config.user,
            password=actual_password
        )
        
        if not success:
            raise RuntimeError(f"Failed to start PostgreSQL container: {container_name}")
        
        return PostgresInfo(postgres_config, actual_password)
    
    async def _run_init_phase(self, env_config: EnvironmentConfig, substitutor: VariableSubstitutor) -> List[PhaseResult]:
        """Run initialization phase containers."""
        if not env_config.init:
            logger.info("No init containers configured, skipping init phase")
            return []
        
        logger.info(f"Running init phase with {len(env_config.init)} container(s)")
        
        results = []
        
        for i, init_ref in enumerate(env_config.init):
            if init_ref.compose:
                result = await self._run_compose_init(init_ref.compose, substitutor, i)
            elif init_ref.pod:
                result = await self._run_pod_init(init_ref.pod, substitutor, i)
            else:
                result = PhaseResult(
                    success=False,
                    exit_code=-1,
                    duration=0.0,
                    logs="No deployment file specified",
                    command="",
                    file_path=""
                )
            
            results.append(result)
            
            # Stop immediately if this init container failed
            if not result.success:
                logger.error(f"Init container {i} failed, stopping init phase")
                break
        
        return results
    
    async def _run_deployment_phase(self, env_config: EnvironmentConfig, substitutor: VariableSubstitutor) -> Optional[PhaseResult]:
        """Run main deployment phase."""
        logger.info("Running deployment phase")
        
        if env_config.deployment.compose:
            return await self._run_compose_deployment(env_config.deployment.compose, substitutor)
        elif env_config.deployment.pod:
            return await self._run_pod_deployment(env_config.deployment.pod, substitutor)
        else:
            logger.error("No deployment configuration specified")
            return PhaseResult(
                success=False,
                exit_code=-1,
                duration=0.0,
                logs="No deployment file specified",
                command="",
                file_path=""
            )
    
    async def _run_compose_init(self, compose_file: str, substitutor: VariableSubstitutor, index: int) -> PhaseResult:
        """Run a Docker Compose init container and wait for completion."""
        start_time = asyncio.get_event_loop().time()
        temp_file = None
        
        try:
            # Process template file
            temp_file = create_temp_processed_file(compose_file, substitutor, f".init{index}.processed")
            
            # Run docker-compose up and wait for completion
            cmd = [self.poststack_config.container_runtime, "compose", "-f", temp_file, "up", "--abort-on-container-exit"]
            
            logger.info(f"Running init compose: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path(compose_file).parent
            )
            
            stdout, _ = await process.communicate()
            logs = stdout.decode('utf-8') if stdout else ""
            
            duration = asyncio.get_event_loop().time() - start_time
            success = process.returncode == 0
            
            logger.info(f"Init compose completed: exit_code={process.returncode}, duration={duration:.2f}s")
            
            return PhaseResult(
                success=success,
                exit_code=process.returncode,
                duration=duration,
                logs=logs,
                command=' '.join(cmd),
                file_path=compose_file
            )
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(f"Init compose failed: {e}")
            
            return PhaseResult(
                success=False,
                exit_code=-1,
                duration=duration,
                logs=str(e),
                command=' '.join(cmd) if 'cmd' in locals() else "",
                file_path=compose_file
            )
        
        finally:
            if temp_file:
                cleanup_temp_file(temp_file)
    
    async def _run_pod_init(self, pod_file: str, substitutor: VariableSubstitutor, index: int) -> PhaseResult:
        """Run a Podman Pod init container and wait for completion."""
        start_time = asyncio.get_event_loop().time()
        temp_file = None
        
        try:
            # Process template file
            temp_file = create_temp_processed_file(pod_file, substitutor, f".init{index}.processed")
            
            # Run podman play kube and wait for completion
            cmd = ["podman", "play", "kube", "--down", temp_file]
            
            logger.info(f"Running init pod: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            stdout, _ = await process.communicate()
            logs = stdout.decode('utf-8') if stdout else ""
            
            duration = asyncio.get_event_loop().time() - start_time
            success = process.returncode == 0
            
            logger.info(f"Init pod completed: exit_code={process.returncode}, duration={duration:.2f}s")
            
            return PhaseResult(
                success=success,
                exit_code=process.returncode,
                duration=duration,
                logs=logs,
                command=' '.join(cmd),
                file_path=pod_file
            )
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(f"Init pod failed: {e}")
            
            return PhaseResult(
                success=False,
                exit_code=-1,
                duration=duration,
                logs=str(e),
                command=' '.join(cmd) if 'cmd' in locals() else "",
                file_path=pod_file
            )
        
        finally:
            if temp_file:
                cleanup_temp_file(temp_file)
    
    async def _run_compose_deployment(self, compose_file: str, substitutor: VariableSubstitutor) -> PhaseResult:
        """Run Docker Compose deployment (detached)."""
        start_time = asyncio.get_event_loop().time()
        temp_file = None
        
        try:
            # Process template file
            temp_file = create_temp_processed_file(compose_file, substitutor, ".deploy.processed")
            
            # Run docker-compose up in detached mode
            cmd = [self.poststack_config.container_runtime, "compose", "-f", temp_file, "up", "-d"]
            
            logger.info(f"Running deployment compose: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path(compose_file).parent
            )
            
            stdout, _ = await process.communicate()
            logs = stdout.decode('utf-8') if stdout else ""
            
            duration = asyncio.get_event_loop().time() - start_time
            success = process.returncode == 0
            
            logger.info(f"Deployment compose completed: exit_code={process.returncode}, duration={duration:.2f}s")
            
            return PhaseResult(
                success=success,
                exit_code=process.returncode,
                duration=duration,
                logs=logs,
                command=' '.join(cmd),
                file_path=compose_file
            )
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(f"Deployment compose failed: {e}")
            
            return PhaseResult(
                success=False,
                exit_code=-1,
                duration=duration,
                logs=str(e),
                command=' '.join(cmd) if 'cmd' in locals() else "",
                file_path=compose_file
            )
        
        finally:
            # Keep temp file for running deployment (don't cleanup immediately)
            pass
    
    async def _run_pod_deployment(self, pod_file: str, substitutor: VariableSubstitutor) -> PhaseResult:
        """Run Podman Pod deployment."""
        start_time = asyncio.get_event_loop().time()
        temp_file = None
        
        try:
            # Process template file
            temp_file = create_temp_processed_file(pod_file, substitutor, ".deploy.processed")
            
            # Run podman play kube
            cmd = ["podman", "play", "kube", temp_file]
            
            logger.info(f"Running deployment pod: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            stdout, _ = await process.communicate()
            logs = stdout.decode('utf-8') if stdout else ""
            
            duration = asyncio.get_event_loop().time() - start_time
            success = process.returncode == 0
            
            logger.info(f"Deployment pod completed: exit_code={process.returncode}, duration={duration:.2f}s")
            
            return PhaseResult(
                success=success,
                exit_code=process.returncode,
                duration=duration,
                logs=logs,
                command=' '.join(cmd),
                file_path=pod_file
            )
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            logger.error(f"Deployment pod failed: {e}")
            
            return PhaseResult(
                success=False,
                exit_code=-1,
                duration=duration,
                logs=str(e),
                command=' '.join(cmd) if 'cmd' in locals() else "",
                file_path=pod_file
            )
        
        finally:
            # Keep temp file for running deployment (don't cleanup immediately)
            pass
    
    async def _stop_compose_deployment(self, compose_file: str, remove: bool = False) -> bool:
        """Stop Docker Compose deployment."""
        try:
            # Use 'down' which stops and removes containers by default for compose
            cmd = [self.poststack_config.container_runtime, "compose", "-f", compose_file, "down"]
            
            # Note: docker-compose down already removes containers, so remove flag doesn't change behavior
            if remove:
                logger.debug(f"Stopping and removing compose deployment: {compose_file}")
            else:
                logger.debug(f"Stopping compose deployment: {compose_file}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path(compose_file).parent
            )
            
            await process.communicate()
            return process.returncode == 0
            
        except Exception as e:
            logger.error(f"Failed to stop compose deployment {compose_file}: {e}")
            return False
    
    async def _stop_pod_deployment_with_substitution(self, env_name: str, env_config: EnvironmentConfig, remove: bool = False) -> bool:
        """Stop pod deployment using processed template with variable substitution."""
        try:
            # Get project configuration for variable substitution
            project_config = self.config_parser.load_project_config()
            
            # Get postgres info for variable substitution
            postgres_info = None
            try:
                postgres_status = self._get_postgres_status(env_name)
                if postgres_status.get("running"):
                    # Create postgres info from running container
                    postgres_info = PostgresInfo(
                        config=env_config.postgres,
                        actual_password="dummy_password_for_stop"  # Password doesn't matter for stop
                    )
            except:
                pass
            
            if postgres_info:
                # Create variable substitutor
                substitutor = VariableSubstitutor(env_name, env_config, postgres_info, project_config.project.name)
            else:
                # Create a dummy postgres info for template processing
                dummy_postgres = PostgresInfo(
                    config=env_config.postgres,
                    actual_password="dummy_password"
                )
                substitutor = VariableSubstitutor(env_name, env_config, dummy_postgres, project_config.project.name)
            
            # Process the pod file with substitution
            pod_file = env_config.deployment.pod
            temp_file = create_temp_processed_file(pod_file, substitutor, ".stop.processed")
            
            try:
                result = await self._stop_pod_deployment(temp_file, remove=remove)
                return result
            finally:
                cleanup_temp_file(temp_file)
                
        except Exception as e:
            logger.error(f"Failed to stop pod deployment with substitution: {e}")
            return False

    async def _stop_pod_deployment(self, pod_file: str, remove: bool = False) -> bool:
        """Stop Podman Pod deployment."""
        try:
            # Use podman play kube --down to stop the pod
            cmd = ["podman", "play", "kube", "--down", pod_file]
            
            if remove:
                logger.info(f"Stopping and removing pod deployment: {pod_file}")
            else:
                logger.info(f"Stopping pod deployment: {pod_file}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            stdout, _ = await process.communicate()
            success = process.returncode == 0
            
            if stdout:
                logger.info(f"Pod stop output: {stdout.decode('utf-8')}")
            if not success:
                logger.warning(f"Pod stop failed with exit code {process.returncode}")
            
            # If remove flag is set and stop was successful, force remove any remaining pod
            if remove and success:
                # Extract pod name from the deployment file to force remove
                await self._force_remove_pod_from_file(pod_file)
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to stop pod deployment {pod_file}: {e}")
            return False
    
    async def _force_remove_pod_from_file(self, pod_file: str) -> bool:
        """Force remove pod based on deployment file metadata."""
        try:
            # Read the pod file to extract pod name
            with open(pod_file, 'r') as f:
                import yaml
                pod_data = yaml.safe_load(f)
                
            pod_name = pod_data.get('metadata', {}).get('name')
            if not pod_name:
                logger.warning(f"Could not extract pod name from {pod_file}")
                return False
                
            # Force remove the pod
            cmd = ["podman", "pod", "rm", "--force", pod_name]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            await process.communicate()
            if process.returncode == 0:
                logger.debug(f"Force removed pod: {pod_name}")
            else:
                logger.debug(f"Pod {pod_name} was already removed or doesn't exist")
            
            return True
            
        except Exception as e:
            logger.debug(f"Could not force remove pod from {pod_file}: {e}")
            return False
    
    def _get_postgres_status(self, env_name: str) -> Dict:
        """Get PostgreSQL container status for environment."""
        try:
            # Environment-specific containers use the database name as part of the container name
            env_config = self.config_parser.get_environment_config(env_name)
            expected_container_name = f"poststack-postgres-{env_config.postgres.database}"
            
            # Use existing postgres runner to check status
            containers = self.postgres_runner.list_postgres_containers()
            
            logger.debug(f"Looking for container '{expected_container_name}' in {len(containers)} postgres containers")
            
            for container in containers:
                container_name = container.get("name", "")
                logger.debug(f"Checking container: {container_name}")
                
                # Check for exact match or if the environment database name is in the container name
                if (container_name == expected_container_name or 
                    env_config.postgres.database in container_name):
                    status = container.get("status", "unknown").lower()
                    return {
                        "container_name": container_name,
                        "status": container.get("status", "unknown"),
                        "running": status == "running" or status == "up",
                        "port": container.get("host_port"),
                        "database": container.get("database"),
                        "image": container.get("image")
                    }
            
            # Also check for containers that might be using a simpler naming pattern
            simple_container_name = f"poststack-postgres-{env_name}"
            for container in containers:
                container_name = container.get("name", "")
                if container_name == simple_container_name:
                    status = container.get("status", "unknown").lower()
                    return {
                        "container_name": container_name,
                        "status": container.get("status", "unknown"),
                        "running": status == "running" or status == "up",
                        "port": container.get("host_port"),
                        "database": container.get("database"),
                        "image": container.get("image")
                    }
            
            return {
                "container_name": expected_container_name, 
                "status": "not_running",
                "running": False,
                "expected_name": expected_container_name,
                "simple_name": simple_container_name
            }
            
        except Exception as e:
            logger.error(f"Failed to get postgres status for {env_name}: {e}")
            return {"container_name": f"poststack-postgres-{env_name}", "status": "error", "running": False, "error": str(e)}
    
    async def _get_compose_status(self, compose_file: str) -> List[Dict]:
        """Get status of Docker Compose services."""
        try:
            cmd = [self.poststack_config.container_runtime, "compose", "-f", compose_file, "ps", "--format", "json"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path(compose_file).parent
            )
            
            stdout, _ = await process.communicate()
            
            if process.returncode == 0 and stdout:
                import json
                return json.loads(stdout.decode('utf-8'))
            else:
                return []
                
        except Exception as e:
            logger.error(f"Failed to get compose status for {compose_file}: {e}")
            return []
    
    async def _get_pod_status(self, pod_file: str) -> List[Dict]:
        """Get status of Podman Pod containers."""
        try:
            # This is a simplified implementation - podman doesn't have direct equivalent to docker-compose ps
            # In a real implementation, you'd parse the pod file and check each container
            cmd = ["podman", "ps", "--format", "json"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            stdout, _ = await process.communicate()
            
            if process.returncode == 0 and stdout:
                import json
                containers = json.loads(stdout.decode('utf-8'))
                
                # Convert to expected format
                formatted_containers = []
                for container in containers:
                    # Skip infra containers
                    if container.get("IsInfra", False):
                        continue
                        
                    state = container.get("State", "unknown").lower()
                    names = container.get("Names", [])
                    name = names[0] if names else "unknown"
                    
                    formatted_containers.append({
                        "name": name,
                        "status": container.get("Status", "unknown"),
                        "running": state == "running",
                        "image": container.get("Image", ""),
                        "state": state
                    })
                
                return formatted_containers
            else:
                return []
                
        except Exception as e:
            logger.error(f"Failed to get pod status for {pod_file}: {e}")
            return []
    
    async def _ensure_volumes_exist(self, env_name: str, env_config: EnvironmentConfig, project_name: str) -> bool:
        """Ensure all required named volumes exist before deployment."""
        try:
            for volume_name, volume_config in env_config.volumes.items():
                if volume_config.type == "named":
                    # Generate volume name using same logic as VariableSubstitutor
                    default_name = f"{project_name}-{volume_name}-{env_name}"
                    actual_volume_name = volume_config.name or default_name
                    
                    # Check if volume exists
                    if not await self._volume_exists(actual_volume_name):
                        # Create the volume
                        success = await self._create_volume(actual_volume_name, volume_config)
                        if not success:
                            logger.error(f"Failed to create volume: {actual_volume_name}")
                            return False
                        logger.info(f"Created volume: {actual_volume_name}")
                    else:
                        logger.debug(f"Volume already exists: {actual_volume_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to ensure volumes exist for {env_name}: {e}")
            return False
    
    async def _volume_exists(self, volume_name: str) -> bool:
        """Check if a named volume exists."""
        try:
            cmd = [self.poststack_config.container_runtime, "volume", "inspect", volume_name]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            await process.wait()
            return process.returncode == 0
            
        except Exception as e:
            logger.debug(f"Error checking volume existence {volume_name}: {e}")
            return False
    
    async def _create_volume(self, volume_name: str, volume_config) -> bool:
        """Create a named volume."""
        try:
            cmd = [self.poststack_config.container_runtime, "volume", "create"]
            
            # Add size constraint if specified (Podman format)
            if volume_config.size:
                cmd.extend(["--opt", f"size={volume_config.size}"])
            
            # Add user permissions for rootless podman
            # This ensures volumes are accessible by containers
            import os
            uid = os.getuid()
            gid = os.getgid()
            cmd.extend(["--opt", f"o=uid={uid},gid={gid}"])
            
            cmd.append(volume_name)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Successfully created volume: {volume_name}")
                return True
            else:
                logger.error(f"Failed to create volume {volume_name}: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Exception creating volume {volume_name}: {e}")
            return False
    
    async def remove_environment_volumes(self, env_name: str, force: bool = False) -> bool:
        """Remove all volumes associated with an environment."""
        try:
            env_config = self.config_parser.get_environment_config(env_name)
            project_config = self.config_parser.load_project_config()
            
            success = True
            for volume_name, volume_config in env_config.volumes.items():
                if volume_config.type == "named":
                    # Generate volume name
                    default_name = f"{project_config.project.name}-{volume_name}-{env_name}"
                    actual_volume_name = volume_config.name or default_name
                    
                    if await self._volume_exists(actual_volume_name):
                        if await self._remove_volume(actual_volume_name, force):
                            logger.info(f"Removed volume: {actual_volume_name}")
                        else:
                            logger.error(f"Failed to remove volume: {actual_volume_name}")
                            success = False
                    else:
                        logger.debug(f"Volume does not exist: {actual_volume_name}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to remove environment volumes for {env_name}: {e}")
            return False
    
    async def _remove_volume(self, volume_name: str, force: bool = False) -> bool:
        """Remove a named volume."""
        try:
            cmd = [self.poststack_config.container_runtime, "volume", "rm"]
            
            if force:
                cmd.append("--force")
            
            cmd.append(volume_name)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True
            else:
                logger.warning(f"Failed to remove volume {volume_name}: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Exception removing volume {volume_name}: {e}")
            return False
    
    async def list_environment_volumes(self, env_name: Optional[str] = None) -> List[Dict[str, str]]:
        """List volumes, optionally filtered by environment."""
        try:
            # Get all volumes
            cmd = [self.poststack_config.container_runtime, "volume", "ls", "--format", "json"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Failed to list volumes: {stderr.decode()}")
                return []
            
            # Parse volume information
            volumes = []
            try:
                volume_data = json.loads(stdout.decode())
                if isinstance(volume_data, list):
                    for volume in volume_data:
                        volume_name = volume.get("Name", "")
                        # Filter by environment if specified
                        if env_name is None or f"-{env_name}" in volume_name:
                            volumes.append({
                                "name": volume_name,
                                "driver": volume.get("Driver", ""),
                                "mountpoint": volume.get("Mountpoint", ""),
                                "created": volume.get("CreatedAt", "")
                            })
            except json.JSONDecodeError:
                logger.error("Failed to parse volume list JSON")
            
            return volumes
            
        except Exception as e:
            logger.error(f"Failed to list volumes: {e}")
            return []