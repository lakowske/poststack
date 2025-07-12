"""
Core container management library for Poststack

Provides ContainerBuilder and ContainerRunner classes for managing
container image building and runtime operations with comprehensive
error handling and logging integration.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import PoststackConfig
from .logging_config import SubprocessLogHandler
from .models import (
    BuildResult,
    BuildStatus,
    ContainerCleanupResult,
    ContainerOperationError,
    HealthCheckResult,
    RuntimeResult,
    RuntimeStatus,
)

logger = logging.getLogger(__name__)


class ContainerBuilder:
    """
    Manages container image building operations.

    Provides methods for building single images or multiple images in parallel,
    with comprehensive logging and error handling.
    """

    def __init__(
        self,
        config: PoststackConfig,
        log_handler: Optional[SubprocessLogHandler] = None,
    ):
        """Initialize container builder with configuration."""
        self.config = config
        self.log_handler = log_handler or SubprocessLogHandler(
            "container_build", config.log_dir
        )
        self.container_runtime = config.container_runtime

    def build_image(
        self,
        image_name: str,
        dockerfile_path: Path,
        context_path: Optional[Path] = None,
        build_args: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        no_cache: bool = False,
        timeout: int = 600,
    ) -> BuildResult:
        """
        Build a single container image.

        Args:
            image_name: Name for the built image
            dockerfile_path: Path to Dockerfile
            context_path: Build context directory (defaults to dockerfile parent)
            build_args: Build arguments to pass to container build
            tags: Additional tags for the image
            no_cache: Disable build cache
            timeout: Build timeout in seconds

        Returns:
            BuildResult with build status and details
        """
        context_path = context_path or dockerfile_path.parent
        build_args = build_args or {}
        tags = tags or []

        # Create build result
        result = BuildResult(
            image_name=image_name,
            status=BuildStatus.BUILDING,
            dockerfile_path=dockerfile_path,
            context_path=context_path,
            build_args=build_args,
            tags=tags,
        )

        logger.info(f"Building container image: {image_name}")
        logger.debug(f"Dockerfile: {dockerfile_path}, Context: {context_path}")

        # Validate inputs
        if not dockerfile_path.exists():
            error = ContainerOperationError(
                operation="build_image",
                error_type="FileNotFoundError",
                message=f"Dockerfile not found: {dockerfile_path}",
                context={
                    "image_name": image_name,
                    "dockerfile_path": str(dockerfile_path),
                },
            )
            result.status = BuildStatus.FAILED
            result.mark_completed(1)
            logger.error(error.get_detailed_message())
            return result

        if not context_path.exists():
            error = ContainerOperationError(
                operation="build_image",
                error_type="FileNotFoundError",
                message=f"Build context not found: {context_path}",
                context={"image_name": image_name, "context_path": str(context_path)},
            )
            result.status = BuildStatus.FAILED
            result.mark_completed(1)
            logger.error(error.get_detailed_message())
            return result

        # Build command
        cmd = [
            self.container_runtime,
            "build",
            "-t",
            image_name,
            "-f",
            str(dockerfile_path),
        ]

        # Add build arguments
        for arg_name, arg_value in build_args.items():
            cmd.extend(["--build-arg", f"{arg_name}={arg_value}"])

        # Add additional tags
        for tag in tags:
            cmd.extend(["-t", tag])

        # Add no-cache flag
        if no_cache:
            cmd.append("--no-cache")

        # Add context path
        cmd.append(str(context_path))

        # Log command
        self.log_handler.log_command(cmd)
        logger.debug(f"Build command: {' '.join(cmd)}")

        # Execute build
        try:
            start_time = time.time()

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=context_path,
            )

            build_time = time.time() - start_time

            # Log output
            if process.stdout:
                result.add_output(process.stdout, is_error=False)
                self.log_handler.log_output(process.stdout)

            if process.stderr:
                result.add_output(process.stderr, is_error=True)
                self.log_handler.log_output(process.stderr, logging.WARNING)

            # Update result
            result.mark_completed(process.returncode)
            self.log_handler.log_completion(process.returncode, build_time)

            if result.success:
                logger.info(f"Successfully built {image_name} in {build_time:.1f}s")
            else:
                logger.error(
                    f"Failed to build {image_name} (exit code: {process.returncode})"
                )

            return result

        except subprocess.TimeoutExpired:
            error_msg = f"Build timed out after {timeout} seconds"
            result.add_output(error_msg, is_error=True)
            result.status = BuildStatus.FAILED
            result.mark_completed(124)  # Standard timeout exit code
            self.log_handler.log_output(error_msg, logging.ERROR)
            self.log_handler.log_completion(124, timeout)
            logger.error(f"Build timeout for {image_name}")
            return result

        except Exception as e:
            error_msg = f"Build error: {e}"
            result.add_output(error_msg, is_error=True)
            result.status = BuildStatus.FAILED
            result.mark_completed(1)
            self.log_handler.log_output(error_msg, logging.ERROR)
            self.log_handler.log_completion(1, time.time() - start_time)
            logger.error(f"Build exception for {image_name}: {e}")
            return result


    def image_exists(self, image_name: str) -> bool:
        """Check if an image exists locally."""
        try:
            result = subprocess.run(
                [self.container_runtime, "images", "-q", image_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False

    def remove_image(self, image_name: str, force: bool = False) -> bool:
        """Remove a container image."""
        try:
            cmd = [self.container_runtime, "rmi"]
            if force:
                cmd.append("-f")
            cmd.append(image_name)

            result = subprocess.run(cmd, capture_output=True, timeout=30)
            return result.returncode == 0
        except Exception:
            return False


class ContainerRunner:
    """
    Manages container runtime operations.

    Provides methods for starting, stopping, and managing running containers
    with health checks and comprehensive logging.
    """

    def __init__(
        self,
        config: PoststackConfig,
        log_handler: Optional[SubprocessLogHandler] = None,
    ):
        """Initialize container runner with configuration."""
        self.config = config
        self.log_handler = log_handler or SubprocessLogHandler(
            "container_runtime", config.log_dir
        )
        self.container_runtime = config.container_runtime

    def start_container(
        self,
        container_name: str,
        image_name: str,
        ports: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, str]] = None,
        environment: Optional[Dict[str, str]] = None,
        detached: bool = True,
        remove_on_exit: bool = False,
        timeout: int = 60,
    ) -> RuntimeResult:
        """
        Start a container.

        Args:
            container_name: Name for the container
            image_name: Image to run
            ports: Port mappings (host:container)
            volumes: Volume mappings (host:container)
            environment: Environment variables
            detached: Run in detached mode
            remove_on_exit: Remove container when it exits
            timeout: Start timeout in seconds

        Returns:
            RuntimeResult with runtime status and details
        """
        ports = ports or {}
        volumes = volumes or {}
        environment = environment or {}

        result = RuntimeResult(
            container_name=container_name,
            image_name=image_name,
            status=RuntimeStatus.STARTING,
            ports=ports,
            volumes=volumes,
            environment=environment,
        )

        logger.info(f"Starting container: {container_name} from {image_name}")

        # Build run command
        cmd = [
            self.container_runtime,
            "run",
            "--name",
            container_name,
        ]

        if detached:
            cmd.append("-d")

        if remove_on_exit:
            cmd.append("--rm")

        # Add port mappings
        for host_port, container_port in ports.items():
            cmd.extend(["-p", f"{host_port}:{container_port}"])

        # Add volume mappings
        for host_path, container_path in volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

        # Add environment variables
        for env_name, env_value in environment.items():
            cmd.extend(["-e", f"{env_name}={env_value}"])

        cmd.append(image_name)

        # Log command
        self.log_handler.log_command(cmd)
        logger.debug(f"Run command: {' '.join(cmd)}")

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if process.returncode == 0:
                container_id = process.stdout.strip()
                result.mark_started(container_id)
                logger.info(f"Container {container_name} started: {container_id[:12]}")
            else:
                result.status = RuntimeStatus.FAILED
                result.add_logs(process.stderr)
                logger.error(f"Failed to start {container_name}: {process.stderr}")

            # Log output
            if process.stdout:
                self.log_handler.log_output(process.stdout)
            if process.stderr:
                self.log_handler.log_output(process.stderr, logging.WARNING)

            return result

        except subprocess.TimeoutExpired:
            result.status = RuntimeStatus.FAILED
            error_msg = f"Container start timed out after {timeout} seconds"
            result.add_logs(error_msg)
            logger.error(f"Start timeout for {container_name}")
            return result

        except Exception as e:
            result.status = RuntimeStatus.FAILED
            error_msg = f"Start error: {e}"
            result.add_logs(error_msg)
            logger.error(f"Start exception for {container_name}: {e}")
            return result

    def stop_container(self, container_name: str, timeout: int = 30) -> RuntimeResult:
        """Stop a running container."""
        result = RuntimeResult(
            container_name=container_name,
            image_name="",  # Will be filled if container exists
            status=RuntimeStatus.STOPPING,
        )

        logger.info(f"Stopping container: {container_name}")

        try:
            # Check if container exists and is running
            status_result = self.get_container_status(container_name)
            if status_result and status_result.running:
                result.image_name = status_result.image_name
                result.container_id = status_result.container_id

            cmd = [self.container_runtime, "stop", container_name]

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if process.returncode == 0:
                result.mark_stopped(0)
                logger.info(f"Container {container_name} stopped successfully")
            else:
                result.status = RuntimeStatus.FAILED
                logger.error(f"Failed to stop {container_name}: {process.stderr}")

            return result

        except Exception as e:
            result.status = RuntimeStatus.FAILED
            logger.error(f"Stop exception for {container_name}: {e}")
            return result


    def get_container_status(self, container_name: str) -> Optional[RuntimeResult]:
        """Get status of a container."""
        try:
            cmd = [
                self.container_runtime,
                "inspect",
                "--format",
                "{{.State.Status}},{{.Config.Image}},{{.Id}}",
                container_name,
            ]

            process = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if process.returncode == 0:
                status_str, image_name, container_id = process.stdout.strip().split(",")

                status_map = {
                    "running": RuntimeStatus.RUNNING,
                    "exited": RuntimeStatus.STOPPED,
                    "created": RuntimeStatus.STOPPED,
                    "paused": RuntimeStatus.RUNNING,
                    "restarting": RuntimeStatus.STARTING,
                }

                status = status_map.get(status_str, RuntimeStatus.UNKNOWN)

                result = RuntimeResult(
                    container_name=container_name,
                    image_name=image_name,
                    status=status,
                    container_id=container_id,
                )

                return result

            return None

        except Exception:
            return None

    def health_check(
        self, container_name: str, check_type: str = "running"
    ) -> HealthCheckResult:
        """
        Perform health check on a container.

        Args:
            container_name: Name of container to check
            check_type: Type of check ("running", "responsive")

        Returns:
            HealthCheckResult with check status
        """
        start_time = time.time()

        if check_type == "running":
            # Simple running status check
            status = self.get_container_status(container_name)
            passed = status is not None and status.running
            message = "Container is running" if passed else "Container is not running"

        elif check_type == "responsive":
            # More comprehensive responsiveness check
            status = self.get_container_status(container_name)
            if not status or not status.running:
                passed = False
                message = "Container is not running"
            else:
                # Try to get recent logs to verify responsiveness
                try:
                    cmd = [
                        self.container_runtime,
                        "logs",
                        "--tail",
                        "5",
                        container_name,
                    ]
                    result = subprocess.run(cmd, capture_output=True, timeout=5)
                    passed = result.returncode == 0
                    message = (
                        "Container is responsive"
                        if passed
                        else "Container is not responsive"
                    )
                except:
                    passed = False
                    message = "Container responsiveness check failed"
        else:
            passed = False
            message = f"Unknown check type: {check_type}"

        response_time = time.time() - start_time

        return HealthCheckResult(
            container_name=container_name,
            check_type=check_type,
            passed=passed,
            message=message,
            response_time=response_time,
        )

    def cleanup_containers(
        self,
        container_names: Optional[List[str]] = None,
        remove_images: bool = False,
        remove_volumes: bool = False,
    ) -> ContainerCleanupResult:
        """
        Clean up containers and optionally related resources.

        Args:
            container_names: Specific containers to clean (None for all poststack containers)
            remove_images: Also remove associated images
            remove_volumes: Also remove associated volumes

        Returns:
            ContainerCleanupResult with cleanup details
        """
        start_time = time.time()
        result = ContainerCleanupResult()

        logger.info("Starting container cleanup")

        # Get containers to clean
        if container_names is None:
            # Find all poststack containers
            try:
                cmd = [
                    self.container_runtime,
                    "ps",
                    "-a",
                    "--filter",
                    "name=poststack-",
                    "--format",
                    "{{.Names}}",
                ]
                process = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
                if process.returncode == 0:
                    container_names = [
                        name.strip()
                        for name in process.stdout.split("\n")
                        if name.strip()
                    ]
                else:
                    container_names = []
            except Exception as e:
                error = ContainerOperationError(
                    operation="list_containers",
                    error_type=type(e).__name__,
                    message=str(e),
                )
                result.errors.append(error)
                container_names = []

        # Stop and remove containers
        for container_name in container_names:
            try:
                # Stop container
                subprocess.run(
                    [self.container_runtime, "stop", container_name],
                    capture_output=True,
                    timeout=30,
                )

                # Remove container
                remove_result = subprocess.run(
                    [self.container_runtime, "rm", container_name],
                    capture_output=True,
                    timeout=10,
                )

                if remove_result.returncode == 0:
                    result.containers_removed.append(container_name)
                    logger.debug(f"Removed container: {container_name}")

            except Exception as e:
                error = ContainerOperationError(
                    operation="remove_container",
                    error_type=type(e).__name__,
                    message=str(e),
                    context={"container_name": container_name},
                )
                result.errors.append(error)

        # Clean up images if requested
        if remove_images:
            image_names = [
                f"poststack/{name.replace('poststack-', '')}"
                for name in container_names
            ]
            for image_name in image_names:
                try:
                    remove_result = subprocess.run(
                        [self.container_runtime, "rmi", image_name],
                        capture_output=True,
                        timeout=30,
                    )
                    if remove_result.returncode == 0:
                        result.images_removed.append(image_name)
                        logger.debug(f"Removed image: {image_name}")
                except Exception as e:
                    error = ContainerOperationError(
                        operation="remove_image",
                        error_type=type(e).__name__,
                        message=str(e),
                        context={"image_name": image_name},
                    )
                    result.errors.append(error)

        result.cleanup_time = time.time() - start_time

        logger.info(f"Cleanup complete: {result.get_summary()}")
        return result
