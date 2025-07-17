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

from ..config import EnvironmentConfig, PoststackConfig, DeploymentRef
from ..container_runtime import PostgreSQLRunner
from ..models import RuntimeStatus
from .config import EnvironmentConfigParser
from .substitution import VariableSubstitutor, create_temp_processed_file, cleanup_temp_file

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
    init_results: List[PhaseResult]
    deployment_results: List[PhaseResult]
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
            
            # Create dedicated network for environment
            network_success = await self._ensure_network_exists(env_name, project_config.project.name)
            if not network_success:
                raise RuntimeError(f"Failed to create network for environment: {env_name}")
            
            # Ensure all required volumes exist
            volume_success = await self._ensure_volumes_exist(env_name, env_config, project_config.project.name)
            if not volume_success:
                raise RuntimeError(f"Failed to create required volumes for environment: {env_name}")
            
            # Create variable substitutor with environment variables
            substitutor = VariableSubstitutor(env_name, env_config, project_config.project.name)
            
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
                    init_results=init_results,
                    deployment_results=[],
                    error_message=error_msg,
                    total_duration=asyncio.get_event_loop().time() - start_time
                )
            
            # If init_only, stop here
            if init_only:
                logger.info(f"Init phase completed successfully for environment: {env_name}")
                return EnvironmentResult(
                    environment_name=env_name,
                    success=True,
                    init_results=init_results,
                    deployment_results=[],
                    total_duration=asyncio.get_event_loop().time() - start_time
                )
            
            # Run deployment phase (process multiple deployments)
            deployment_results = await self._run_deployments_phase(env_config, substitutor)
            
            success = all(result.success for result in deployment_results) if deployment_results else False
            
            logger.info(f"Environment deployment completed: {env_name} (success: {success})")
            
            return EnvironmentResult(
                environment_name=env_name,
                success=success,
                init_results=init_results,
                deployment_results=deployment_results,
                total_duration=asyncio.get_event_loop().time() - start_time
            )
            
        except Exception as e:
            logger.error(f"Environment deployment failed: {env_name} - {e}")
            return EnvironmentResult(
                environment_name=env_name,
                success=False,
                init_results=[],
                deployment_results=[],
                error_message=str(e),
                total_duration=asyncio.get_event_loop().time() - start_time
            )
    
    async def validate_environment(self, env_name: str) -> EnvironmentResult:
        """
        Validate environment templates without deploying.
        
        Args:
            env_name: Environment name to validate
            
        Returns:
            EnvironmentResult with validation status
        """
        start_time = asyncio.get_event_loop().time()
        
        logger.info(f"Validating environment templates: {env_name}")
        
        try:
            # Load and validate environment configuration
            env_config = self.config_parser.get_environment_config(env_name)
            project_config = self.config_parser.load_project_config()
            
            # Create variable substitutor with environment variables
            substitutor = VariableSubstitutor(env_name, env_config, project_config.project.name)
            
            # Validate init templates
            init_results = []
            for init_ref in env_config.init:
                if init_ref.enabled:
                    try:
                        # Process template to validate syntax
                        if init_ref.compose:
                            substitutor.process_file(init_ref.compose)
                        elif init_ref.pod:
                            substitutor.process_file(init_ref.pod)
                        
                        init_results.append(PhaseResult(
                            success=True,
                            exit_code=0,
                            duration=0.0,
                            logs="Template validation successful",
                            command="validate",
                            file_path=init_ref.pod or init_ref.compose or ""
                        ))
                    except Exception as e:
                        init_results.append(PhaseResult(
                            success=False,
                            exit_code=1,
                            duration=0.0,
                            logs=f"Template validation failed: {e}",
                            command="validate",
                            file_path=init_ref.pod or init_ref.compose or ""
                        ))
            
            # Validate deployment templates
            deployment_results = []
            for deployment in env_config.deployments:
                if deployment.enabled:
                    try:
                        logger.debug(f"Validating deployment: {deployment.name}, pod: {deployment.pod}, type: {type(deployment.pod)}")
                        
                        # Create deployment-specific substitutor with dependencies
                        deployment_substitutor = self._create_deployment_substitutor_with_dependencies(substitutor, deployment)
                        
                        # Process template to validate syntax
                        if deployment.compose:
                            logger.debug(f"Processing compose file: {deployment.compose}")
                            deployment_substitutor.process_file(deployment.compose)
                        elif deployment.pod:
                            logger.debug(f"Processing pod file: {deployment.pod}")
                            deployment_substitutor.process_file(deployment.pod)
                        
                        deployment_results.append(PhaseResult(
                            success=True,
                            exit_code=0,
                            duration=0.0,
                            logs="Template validation successful",
                            command="validate",
                            file_path=deployment.pod or deployment.compose or ""
                        ))
                    except Exception as e:
                        logger.error(f"Validation failed for {deployment.name}: {e}")
                        deployment_results.append(PhaseResult(
                            success=False,
                            exit_code=1,
                            duration=0.0,
                            logs=f"Template validation failed: {e}",
                            command="validate",
                            file_path=deployment.pod or deployment.compose or ""
                        ))
            
            # Check if all validations succeeded
            success = all(r.success for r in init_results + deployment_results)
            error_message = None
            if not success:
                failed_validations = [r for r in init_results + deployment_results if not r.success]
                error_message = f"Template validation failed for {len(failed_validations)} deployment(s)"
            
            return EnvironmentResult(
                environment_name=env_name,
                success=success,
                init_results=init_results,
                deployment_results=deployment_results,
                error_message=error_message,
                total_duration=asyncio.get_event_loop().time() - start_time
            )
            
        except Exception as e:
            import traceback
            logger.error(f"Environment validation failed: {env_name} - {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return EnvironmentResult(
                environment_name=env_name,
                success=False,
                init_results=[],
                deployment_results=[],
                error_message=str(e),
                total_duration=asyncio.get_event_loop().time() - start_time
            )
    
    async def stop_environment(self, env_name: str, remove: bool = False) -> bool:
        """
        Stop all containers for an environment.
        
        Args:
            env_name: Environment name to stop
            remove: If True, remove containers after stopping (--rm flag)
            
        Returns:
            True if successful
        """
        action = "Stopping and removing" if remove else "Stopping"
        logger.info(f"{action} environment: {env_name}")
        
        try:
            env_config = self.config_parser.get_environment_config(env_name)
            project_config = self.config_parser.load_project_config()
            
            # Create variable substitutor for processing stop templates
            substitutor = VariableSubstitutor(env_name, env_config, project_config.project.name)
            
            # Stop deployment containers in reverse order
            for deployment in reversed(env_config.deployments):
                if deployment.enabled:
                    if deployment.compose:
                        await self._stop_compose_deployment(deployment.compose, remove=remove)
                    elif deployment.pod:
                        # Create deployment-specific substitutor
                        deployment_substitutor = self._create_deployment_substitutor(substitutor, deployment)
                        await self._stop_pod_deployment_with_substitution(deployment_substitutor, deployment.pod, remove=remove)
            
            # Stop init containers (they should already be stopped, but cleanup just in case)
            for init_ref in env_config.init:
                if init_ref.compose:
                    await self._stop_compose_deployment(init_ref.compose, remove=remove)
                elif init_ref.pod:
                    await self._stop_pod_deployment(init_ref.pod, remove=remove)
            
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
            project_config = self.config_parser.load_project_config()
            
            # Get PostgreSQL status first
            postgres_status = await self._get_postgres_status(env_name, env_config, project_config)
            
            # Collect all deployment containers into a flat list for the expected format
            deployment_containers = []
            
            # Check deployment containers
            for deployment in env_config.deployments:
                if deployment.enabled:
                    if deployment.compose:
                        deployment_status = await self._get_compose_status(deployment.compose)
                    elif deployment.pod:
                        deployment_status = await self._get_pod_status(deployment.pod)
                    else:
                        deployment_status = []
                    
                    # Add containers to the flat list
                    deployment_containers.extend(deployment_status)
            
            # Return status in the format expected by CLI
            status = {
                "environment": env_name,
                "postgres": postgres_status,
                "deployment_containers": deployment_containers
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get environment status for {env_name}: {e}")
            return {"environment": env_name, "error": str(e)}
    
    async def _get_postgres_status(self, env_name: str, env_config: EnvironmentConfig, project_config) -> Dict:
        """Get PostgreSQL container status for the environment."""
        # Find PostgreSQL deployment by type
        postgres_deployment = None
        for deployment in env_config.deployments:
            if deployment.enabled and deployment.type == "postgres":
                postgres_deployment = deployment
                break
        
        if not postgres_deployment:
            return {
                "running": False,
                "status": "no postgres deployment",
                "port": None
            }
        
        # Generate PostgreSQL container name pattern: {project}-{deployment_name}-{environment}-postgres
        deployment_name = postgres_deployment.get_deployment_name()
        postgres_container_name = f"{project_config.project.name}-{deployment_name}-{env_name}-postgres"
        
        try:
            # Use the postgres runner to get container status
            postgres_result = self.postgres_runner.get_container_status(postgres_container_name)
            
            if postgres_result and postgres_result.status == RuntimeStatus.RUNNING:
                # Get PostgreSQL port from deployment config
                postgres_port = postgres_deployment.variables.get("DB_PORT", "5432")
                
                return {
                    "running": True,
                    "container_name": postgres_container_name,
                    "port": postgres_port,
                    "status": "running"
                }
            else:
                return {
                    "running": False,
                    "container_name": postgres_container_name,
                    "port": None,
                    "status": "not running" if postgres_result else "not found"
                }
                
        except Exception as e:
            logger.error(f"Failed to get PostgreSQL status for {env_name}: {e}")
            return {
                "running": False,
                "container_name": postgres_container_name,
                "port": None,
                "status": f"error: {e}"
            }
    
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
    
    async def _run_deployments_phase(self, env_config: EnvironmentConfig, substitutor: VariableSubstitutor) -> List[PhaseResult]:
        """Run multiple deployments phase."""
        logger.info("Running deployments phase")
        
        if not env_config.deployments:
            logger.warning("No deployments configured for environment")
            return []
        
        results = []
        
        # Process deployments with dependency resolution
        deployed_services = set()
        remaining_deployments = env_config.deployments.copy()
        
        while remaining_deployments:
            # Find deployments that can be started (all dependencies satisfied)
            ready_deployments = []
            for deployment in remaining_deployments:
                if deployment.enabled and all(dep in deployed_services for dep in deployment.depends_on):
                    ready_deployments.append(deployment)
            
            if not ready_deployments:
                # Check if we have circular dependencies or missing dependencies
                remaining_deps = {dep for d in remaining_deployments for dep in d.depends_on if dep not in deployed_services}
                available_services = {d.get_deployment_name() for d in remaining_deployments}
                missing_deps = remaining_deps - available_services
                
                if missing_deps:
                    error_msg = f"Missing dependencies: {missing_deps}"
                    logger.error(error_msg)
                    results.append(PhaseResult(
                        success=False,
                        exit_code=-1,
                        duration=0.0,
                        logs=error_msg,
                        command="",
                        file_path=""
                    ))
                    break
                else:
                    error_msg = f"Circular dependency detected in deployments"
                    logger.error(error_msg)
                    results.append(PhaseResult(
                        success=False,
                        exit_code=-1,
                        duration=0.0,
                        logs=error_msg,
                        command="",
                        file_path=""
                    ))
                    break
            
            # Deploy ready services
            for deployment in ready_deployments:
                logger.info(f"Deploying service: {deployment.get_deployment_name()}")
                
                # Create deployment-specific substitutor with dependencies and merged variables
                deployment_substitutor = self._create_deployment_substitutor_with_dependencies(substitutor, deployment)
                
                if deployment.compose:
                    result = await self._run_compose_deployment(deployment.compose, deployment_substitutor)
                elif deployment.pod:
                    # Check if this deployment uses host networking
                    uses_host_network = self._deployment_uses_host_network(deployment_substitutor, deployment)
                    network_name = None if uses_host_network else f"{deployment_substitutor.project_name}-{deployment_substitutor.environment_name}"
                    
                    logger.debug(f"Deployment {deployment.name} uses host networking: {uses_host_network}")
                    result = await self._run_pod_deployment(deployment.pod, deployment_substitutor, network_name)
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
                if result.success:
                    deployed_services.add(deployment.get_deployment_name())
                
                # Remove from remaining deployments
                remaining_deployments.remove(deployment)
        
        return results
    
    def _create_deployment_substitutor(self, base_substitutor: VariableSubstitutor, deployment: DeploymentRef) -> VariableSubstitutor:
        """Create a deployment-specific variable substitutor."""
        # Create a new substitutor with deployment-specific variables
        deployment_variables = base_substitutor.get_variables().copy()
        deployment_variables.update(deployment.variables)
        
        # Create new substitutor instance with merged variables (using dict constructor)
        new_substitutor = VariableSubstitutor(
            deployment_variables,  # Pass variables dict as first parameter
            base_substitutor.environment_config,
            base_substitutor.project_name
        )
        
        # Preserve environment name from base substitutor
        new_substitutor.environment_name = base_substitutor.environment_name
        
        return new_substitutor
    
    def _create_deployment_substitutor_with_dependencies(self, base_substitutor: VariableSubstitutor, deployment: DeploymentRef) -> VariableSubstitutor:
        """Create a deployment-specific variable substitutor with service discovery variables."""
        # Create a new substitutor with deployment-specific variables
        deployment_variables = base_substitutor.get_variables().copy()
        deployment_variables.update(deployment.variables)
        
        # Add service discovery variables for this deployment's dependencies
        if hasattr(deployment, 'depends_on') and deployment.depends_on:
            # Detect target service networking mode for proper endpoint selection
            target_service_info = base_substitutor.service_registry.services.get(deployment.name)
            target_networking_mode = target_service_info.networking_mode if target_service_info else None
            
            service_vars = base_substitutor.service_registry.generate_service_variables(
                deployment.name, 
                deployment.depends_on, 
                target_networking_mode
            )
            deployment_variables.update(service_vars)
        
        # Create new substitutor instance with merged variables (using dict constructor)
        new_substitutor = VariableSubstitutor(
            deployment_variables,  # Pass variables dict as first parameter
            base_substitutor.environment_config,
            base_substitutor.project_name
        )
        
        # Preserve environment name from base substitutor
        new_substitutor.environment_name = base_substitutor.environment_name
        
        return new_substitutor
    
    def _deployment_uses_host_network(self, substitutor: VariableSubstitutor, deployment: DeploymentRef) -> bool:
        """Check if a deployment uses host networking by examining the template variables."""
        variables = substitutor.get_variables()
        
        # Check for service-specific host network variables first (highest priority)
        if deployment.name == 'apache':
            return variables.get('APACHE_USE_HOST_NETWORK', '').lower() == 'true'
        elif deployment.name == 'mail':
            return variables.get('MAIL_USE_HOST_NETWORK', '').lower() == 'true'
        
        # Some services like postgres should use bridge networking even with global host mode
        # They use host port mappings instead of host networking
        if deployment.name in ['postgres', 'volume-setup']:
            return False
        
        # Fail2ban should always use host networking for iptables access
        if deployment.name == 'fail2ban':
            return True
        
        # Check for general network mode setting for other services
        network_mode = variables.get('NETWORK_MODE', '').lower()
        return network_mode == 'host'
    
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
    
    async def _run_pod_deployment(self, pod_file: str, substitutor: VariableSubstitutor, network_name: Optional[str] = None) -> PhaseResult:
        """Run Podman Pod deployment with optional network."""
        start_time = asyncio.get_event_loop().time()
        temp_file = None
        
        try:
            # Process template file
            temp_file = create_temp_processed_file(pod_file, substitutor, ".deploy.processed")
            
            # Run podman play kube with network if specified
            cmd = ["podman", "play", "kube", temp_file]
            if network_name:
                cmd.extend(["--network", network_name])
            
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
                file_path=temp_file or pod_file
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
    
    async def _stop_pod_deployment_with_substitution(self, substitutor: VariableSubstitutor, pod_file: str, remove: bool = False) -> bool:
        """Stop pod deployment using processed template with variable substitution."""
        try:
            # Process the pod file with substitution
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
        """Stop Podman Pod deployment with workaround for kube down termination bug."""
        try:
            if remove:
                logger.info(f"Stopping and removing pod deployment: {pod_file}")
            else:
                logger.info(f"Stopping pod deployment: {pod_file}")
            
            # WORKAROUND: Use podman pod stop before podman play kube --down
            # This addresses the known Podman bug where kube down ignores terminationGracePeriodSeconds
            # and immediately sends SIGKILL instead of proper graceful shutdown
            # Reference: https://github.com/containers/podman/issues/19135
            
            # First, try to gracefully stop the pod using podman pod stop
            pod_name = await self._extract_pod_name_from_file(pod_file)
            if pod_name:
                logger.debug(f"Attempting graceful pod stop for: {pod_name}")
                stop_cmd = ["podman", "pod", "stop", pod_name]
                
                try:
                    stop_process = await asyncio.create_subprocess_exec(
                        *stop_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    stop_stdout, stop_stderr = await stop_process.communicate()
                    
                    if stop_process.returncode == 0:
                        logger.debug(f"Pod {pod_name} stopped gracefully")
                    else:
                        # Pod may already be stopped or not exist, continue with kube down
                        logger.debug(f"Pod stop returned {stop_process.returncode}, continuing with kube down")
                        
                except Exception as e:
                    logger.debug(f"Pod stop failed (expected if pod doesn't exist): {e}")
            
            # Now use podman play kube --down to clean up the pod deployment
            cmd = ["podman", "play", "kube", "--down", pod_file]
            
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
    
    async def _extract_pod_name_from_file(self, pod_file: str) -> str:
        """Extract pod name from Kubernetes YAML file."""
        try:
            import yaml
            with open(pod_file, 'r') as f:
                doc = yaml.safe_load(f)
                if doc and doc.get('kind') == 'Pod':
                    return doc.get('metadata', {}).get('name', '')
        except Exception as e:
            logger.debug(f"Failed to extract pod name from {pod_file}: {e}")
        return ""
    
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
        """Get status of Podman Pod containers for a specific pod file."""
        try:
            # For pod-based deployments, we'll derive the expected pod name from the deployment context
            # and then filter containers that belong to pods with that name pattern
            
            # Get all containers
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
                
                # Extract deployment name from pod file path to match against container names
                # e.g., "deploy/postgres-pod.yaml.deploy.processed" -> "postgres"
                from pathlib import Path
                pod_file_name = Path(pod_file).name
                # Extract deployment type from filename (postgres-pod.yaml -> postgres)
                deployment_type = pod_file_name.split('-')[0]  # "postgres" from "postgres-pod.yaml.deploy.processed"
                
                # Convert to expected format, filtering for containers that match our deployment
                formatted_containers = []
                for container in containers:
                    # Skip infra containers
                    if container.get("IsInfra", False):
                        continue
                        
                    names = container.get("Names", [])
                    name = names[0] if names else "unknown"
                    
                    # Only include containers whose names contain our deployment type
                    # e.g., "unified-postgres-dev-postgres" contains "postgres"
                    if deployment_type in name:
                        state = container.get("State", "unknown").lower()
                        
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
    
    async def _ensure_network_exists(self, env_name: str, project_name: str) -> bool:
        """Ensure environment-specific network exists for proper DNS resolution."""
        network_name = f"{project_name}-{env_name}"
        
        try:
            # Check if network already exists
            if await self._network_exists(network_name):
                logger.debug(f"Network already exists: {network_name}")
                return True
            
            # Create the network
            logger.info(f"Creating network: {network_name}")
            cmd = ["podman", "network", "create", network_name]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Successfully created network: {network_name}")
                return True
            else:
                logger.error(f"Failed to create network {network_name}: {stderr.decode().strip()}")
                return False
                
        except Exception as e:
            logger.error(f"Exception while creating network {network_name}: {e}")
            return False
    
    async def _network_exists(self, network_name: str) -> bool:
        """Check if a network exists."""
        try:
            cmd = ["podman", "network", "ls", "--format", "{{.Name}}"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                networks = stdout.decode().strip().split('\n')
                return network_name in networks
            else:
                logger.warning(f"Failed to list networks: {stderr.decode().strip()}")
                return False
                
        except Exception as e:
            logger.error(f"Exception while checking network {network_name}: {e}")
            return False
    
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
        """Create a named volume without host UID/GID constraints."""
        try:
            cmd = [self.poststack_config.container_runtime, "volume", "create"]
            
            # Add size constraint if specified (Podman format)
            if volume_config.size:
                cmd.extend(["--opt", f"size={volume_config.size}"])
            
            # Don't set UID/GID - containers handle permissions internally
            # or via init containers when needed
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