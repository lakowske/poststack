"""
Environment orchestration for Docker Compose and Podman Pod deployments.

Manages the complete lifecycle of environment deployment including:
- PostgreSQL database setup
- Init phase execution and validation
- Main deployment phase
- Status monitoring and error handling
"""

import asyncio
import logging
import subprocess
import tempfile
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
            
            # Start PostgreSQL database
            postgres_info = await self._setup_postgres(env_config)
            postgres_started = True
            
            # Create variable substitutor
            substitutor = VariableSubstitutor(env_name, env_config, postgres_info)
            
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
    
    async def stop_environment(self, env_name: str, keep_postgres: bool = False) -> bool:
        """
        Stop all containers for an environment.
        
        Args:
            env_name: Environment name to stop
            keep_postgres: If True, don't stop postgres database
            
        Returns:
            True if successful
        """
        logger.info(f"Stopping environment: {env_name}")
        
        try:
            env_config = self.config_parser.get_environment_config(env_name)
            
            # Stop deployment containers
            if env_config.deployment.compose:
                await self._stop_compose_deployment(env_config.deployment.compose)
            elif env_config.deployment.pod:
                await self._stop_pod_deployment(env_config.deployment.pod)
            
            # Stop init containers (they should already be stopped, but cleanup just in case)
            for init_ref in env_config.init:
                if init_ref.compose:
                    await self._stop_compose_deployment(init_ref.compose)
                elif init_ref.pod:
                    await self._stop_pod_deployment(init_ref.pod)
            
            # Stop postgres if requested
            if not keep_postgres:
                # Get the actual postgres status to find the correct container name
                postgres_status = self._get_postgres_status(env_name)
                postgres_container_name = postgres_status.get("name")
                
                if postgres_container_name and postgres_status.get("status") != "not_running":
                    success = self.postgres_runner.stop_postgres_container(postgres_container_name)
                    if not success:
                        logger.warning(f"Failed to stop postgres container: {postgres_container_name}")
                    else:
                        logger.info(f"Stopped postgres container: {postgres_container_name}")
                else:
                    logger.info(f"No running postgres container found for environment: {env_name}")
            
            logger.info(f"Environment stopped: {env_name}")
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
        """Setup PostgreSQL database for environment."""
        postgres_config = env_config.postgres
        
        # Generate password if needed
        if postgres_config.password == "auto_generated":
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            actual_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        else:
            actual_password = postgres_config.password
        
        # Start postgres container with environment-specific settings
        container_name = f"poststack-postgres-{postgres_config.database}"
        
        logger.info(f"Setting up PostgreSQL database: {postgres_config.database} on port {postgres_config.port}")
        
        # Use existing postgres runner but with custom settings
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
    
    async def _stop_compose_deployment(self, compose_file: str) -> bool:
        """Stop Docker Compose deployment."""
        try:
            cmd = [self.poststack_config.container_runtime, "compose", "-f", compose_file, "down"]
            
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
    
    async def _stop_pod_deployment(self, pod_file: str) -> bool:
        """Stop Podman Pod deployment."""
        try:
            # Use podman play kube --down to stop the pod
            cmd = ["podman", "play", "kube", "--down", pod_file]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            await process.communicate()
            return process.returncode == 0
            
        except Exception as e:
            logger.error(f"Failed to stop pod deployment {pod_file}: {e}")
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
                    return {
                        "name": container_name,
                        "status": container.get("status", "unknown"),
                        "port": container.get("host_port"),
                        "database": container.get("database"),
                        "image": container.get("image")
                    }
            
            # Also check for containers that might be using a simpler naming pattern
            simple_container_name = f"poststack-postgres-{env_name}"
            for container in containers:
                container_name = container.get("name", "")
                if container_name == simple_container_name:
                    return {
                        "name": container_name,
                        "status": container.get("status", "unknown"),
                        "port": container.get("host_port"),
                        "database": container.get("database"),
                        "image": container.get("image")
                    }
            
            return {
                "name": expected_container_name, 
                "status": "not_running",
                "expected_name": expected_container_name,
                "simple_name": simple_container_name
            }
            
        except Exception as e:
            logger.error(f"Failed to get postgres status for {env_name}: {e}")
            return {"name": f"poststack-postgres-{env_name}", "status": "error", "error": str(e)}
    
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
                return json.loads(stdout.decode('utf-8'))
            else:
                return []
                
        except Exception as e:
            logger.error(f"Failed to get pod status for {pod_file}: {e}")
            return []