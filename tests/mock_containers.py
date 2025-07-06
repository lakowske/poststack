"""
Mock container operations for testing

Provides mock implementations of container operations that simulate
real container behavior without requiring actual container runtime.
"""

import time
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import patch

from poststack.container_management import ContainerBuilder, ContainerRunner
from poststack.models import (
    BuildResult,
    BuildStatus,
    ContainerCleanupResult,
    HealthCheckResult,
    RuntimeResult,
    RuntimeStatus,
)


class MockContainerBuilder(ContainerBuilder):
    """Mock container builder for testing."""

    def __init__(self, config, log_handler=None):
        super().__init__(config, log_handler)
        self.build_delay = 0.1  # Simulate build time
        self.force_failures = []  # Images that should fail to build
        self.build_times = {}  # Custom build times for specific images

    def set_build_failure(self, image_name: str):
        """Force a specific image to fail building."""
        self.force_failures.append(image_name)

    def set_build_time(self, image_name: str, build_time: float):
        """Set custom build time for an image."""
        self.build_times[image_name] = build_time

    def build_image(
        self, image_name: str, dockerfile_path: Path, **kwargs
    ) -> BuildResult:
        """Mock build image implementation."""
        result = BuildResult(
            image_name=image_name,
            status=BuildStatus.BUILDING,
            dockerfile_path=dockerfile_path,
            context_path=kwargs.get("context_path", dockerfile_path.parent),
            build_args=kwargs.get("build_args", {}),
            tags=kwargs.get("tags", []),
        )

        # Simulate build time
        build_time = self.build_times.get(image_name, self.build_delay)
        time.sleep(build_time)

        # Check for forced failures
        if image_name in self.force_failures:
            result.status = BuildStatus.FAILED
            result.mark_completed(1)
            result.add_output("Mock build failure", is_error=True)
            return result

        # Check if dockerfile exists (still validate input)
        if not dockerfile_path.exists():
            result.status = BuildStatus.FAILED
            result.mark_completed(1)
            result.add_output(f"Dockerfile not found: {dockerfile_path}", is_error=True)
            return result

        # Simulate successful build
        result.mark_completed(0)
        result.add_output(f"Successfully built {image_name}")
        result.add_output("Step 1/3 : FROM debian:bookworm-slim")
        result.add_output("Step 2/3 : RUN apt-get update")
        result.add_output("Step 3/3 : COPY . /app")

        return result

    def image_exists(self, image_name: str) -> bool:
        """Mock image existence check."""
        # Simulate that built images exist, unless they're in force_failures
        return image_name not in self.force_failures


class MockContainerRunner(ContainerRunner):
    """Mock container runner for testing."""

    def __init__(self, config, log_handler=None):
        super().__init__(config, log_handler)
        self.running_containers = {}  # container_name -> RuntimeResult
        self.force_failures = []  # Containers that should fail to start
        self.start_delay = 0.1  # Simulate startup time

    def set_start_failure(self, container_name: str):
        """Force a specific container to fail starting."""
        self.force_failures.append(container_name)

    def start_container(
        self, container_name: str, image_name: str, **kwargs
    ) -> RuntimeResult:
        """Mock start container implementation."""
        result = RuntimeResult(
            container_name=container_name,
            image_name=image_name,
            status=RuntimeStatus.STARTING,
            ports=kwargs.get("ports", {}),
            volumes=kwargs.get("volumes", {}),
            environment=kwargs.get("environment", {}),
        )

        # Simulate startup time
        time.sleep(self.start_delay)

        # Check for forced failures
        if container_name in self.force_failures:
            result.status = RuntimeStatus.FAILED
            result.add_logs("Mock startup failure")
            return result

        # Simulate successful start
        mock_container_id = f"mock_{container_name}_{int(time.time())}"
        result.mark_started(mock_container_id)

        # Store in running containers
        self.running_containers[container_name] = result

        return result

    def stop_container(self, container_name: str, timeout: int = 30) -> RuntimeResult:
        """Mock stop container implementation."""
        if container_name in self.running_containers:
            result = self.running_containers[container_name]
            result.mark_stopped(0)
            del self.running_containers[container_name]
            return result
        else:
            # Container not running
            result = RuntimeResult(
                container_name=container_name,
                image_name="unknown",
                status=RuntimeStatus.STOPPED,
            )
            return result

    def get_container_status(self, container_name: str) -> Optional[RuntimeResult]:
        """Mock get container status."""
        return self.running_containers.get(container_name)

    def health_check(
        self, container_name: str, check_type: str = "running"
    ) -> HealthCheckResult:
        """Mock health check implementation."""
        start_time = time.time()

        # Small delay to simulate check time
        time.sleep(0.01)

        status = self.get_container_status(container_name)

        if check_type == "running":
            passed = status is not None and status.running
            message = "Container is running" if passed else "Container is not running"
        elif check_type == "responsive":
            if not status or not status.running:
                passed = False
                message = "Container is not running"
            else:
                # Simulate responsiveness check
                passed = True
                message = "Container is responsive"
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
        """Mock cleanup containers implementation."""
        start_time = time.time()
        result = ContainerCleanupResult()

        # Determine containers to clean
        if container_names is None:
            container_names = list(self.running_containers.keys())

        # Mock cleanup operations
        for container_name in container_names:
            # Stop and remove container
            if container_name in self.running_containers:
                del self.running_containers[container_name]
            result.containers_removed.append(container_name)

            # Mock image removal if requested
            if remove_images:
                image_name = f"poststack/{container_name.replace('poststack-', '')}"
                result.images_removed.append(image_name)

            # Mock volume removal if requested
            if remove_volumes:
                volume_name = f"{container_name}_data"
                result.volumes_removed.append(volume_name)

        result.cleanup_time = time.time() - start_time
        return result


def mock_container_operations():
    """Context manager that mocks container operations."""

    def create_mock_builder(config, log_handler=None):
        return MockContainerBuilder(config, log_handler)

    def create_mock_runner(config, log_handler=None):
        return MockContainerRunner(config, log_handler)

    return patch.multiple(
        "poststack.container_management",
        ContainerBuilder=create_mock_builder,
        ContainerRunner=create_mock_runner,
    )


class MockContainerService:
    """High-level mock container service for integration testing."""

    def __init__(self, config):
        self.config = config
        self.builder = MockContainerBuilder(config)
        self.runner = MockContainerRunner(config)
        self.images_built = set()
        self.containers_started = set()

    def build_service_images(self, service_names: List[str]) -> Dict[str, BuildResult]:
        """Build images for multiple services."""
        results = {}

        for service_name in service_names:
            image_name = f"poststack/{service_name}"
            dockerfile_path = Path(f"containers/{service_name}/Dockerfile")

            # Mock dockerfile creation for testing
            dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
            dockerfile_path.write_text(
                f"# Mock Dockerfile for {service_name}\nFROM debian:bookworm-slim\n"
            )

            result = self.builder.build_image(image_name, dockerfile_path)
            results[service_name] = result

            if result.success:
                self.images_built.add(image_name)

        return results

    def start_service_containers(
        self, service_specs: Dict[str, Dict]
    ) -> Dict[str, RuntimeResult]:
        """Start containers for multiple services."""
        results = {}

        for service_name, spec in service_specs.items():
            container_name = f"poststack-{service_name}"
            image_name = spec.get("image", f"poststack/{service_name}")

            # Only start if image was built
            if image_name in self.images_built:
                result = self.runner.start_container(
                    container_name=container_name,
                    image_name=image_name,
                    ports=spec.get("ports", {}),
                    volumes=spec.get("volumes", {}),
                    environment=spec.get("environment", {}),
                )
                results[service_name] = result

                if result.running:
                    self.containers_started.add(container_name)
            else:
                # Create failed result for missing image
                result = RuntimeResult(
                    container_name=container_name,
                    image_name=image_name,
                    status=RuntimeStatus.FAILED,
                )
                result.add_logs(f"Image {image_name} not available")
                results[service_name] = result

        return results

    def health_check_all(self) -> Dict[str, HealthCheckResult]:
        """Perform health checks on all running containers."""
        results = {}

        for container_name in self.containers_started:
            service_name = container_name.replace("poststack-", "")
            result = self.runner.health_check(container_name)
            results[service_name] = result

        return results

    def cleanup_all(self) -> ContainerCleanupResult:
        """Clean up all containers and images."""
        container_names = list(self.containers_started)
        result = self.runner.cleanup_containers(
            container_names=container_names,
            remove_images=True,
            remove_volumes=True,
        )

        # Clear tracking sets
        self.images_built.clear()
        self.containers_started.clear()

        return result
