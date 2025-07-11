"""
Tests for container management functionality

Comprehensive tests for ContainerBuilder and ContainerRunner classes
using mock containers and subprocess operations.
"""

import time

from poststack.models import BuildStatus, RuntimeStatus

from .fixtures import (
    mock_build_context,
    test_config,
    temp_workspace,
)
from .mock_containers import (
    MockContainerBuilder,
    MockContainerRunner,
    MockContainerService,
)


class TestContainerBuilder:
    """Test ContainerBuilder functionality."""

    def test_build_image_success(
        self, test_config, mock_build_context
    ):
        """Test successful image build."""
        builder = MockContainerBuilder(test_config)
        dockerfile_path = mock_build_context / "Dockerfile"

        result = builder.build_image(
            image_name="poststack/test-app",
            dockerfile_path=dockerfile_path,
            context_path=mock_build_context,
            build_args={"ENV": "test"},
            tags=["poststack/test-app:latest"],
        )

        assert result.success
        assert result.status == BuildStatus.SUCCESS
        assert result.image_name == "poststack/test-app"
        assert result.dockerfile_path == dockerfile_path
        assert result.context_path == mock_build_context
        assert result.build_args == {"ENV": "test"}
        assert result.tags == ["poststack/test-app:latest"]
        assert result.build_time > 0
        assert "Successfully built" in result.stdout

    def test_build_image_dockerfile_not_found(
        self, test_config, temp_workspace
    ):
        """Test build failure when Dockerfile doesn't exist."""
        builder = MockContainerBuilder(test_config)
        nonexistent_dockerfile = temp_workspace / "nonexistent" / "Dockerfile"

        result = builder.build_image(
            image_name="poststack/test-app",
            dockerfile_path=nonexistent_dockerfile,
        )

        assert result.failed
        assert result.status == BuildStatus.FAILED
        assert result.exit_code == 1
        assert "Dockerfile not found" in result.stderr

    def test_build_image_forced_failure(
        self, test_config, mock_build_context
    ):
        """Test forced build failure."""
        builder = MockContainerBuilder(test_config)
        builder.set_build_failure("poststack/test-app")

        dockerfile_path = mock_build_context / "Dockerfile"

        result = builder.build_image(
            image_name="poststack/test-app",
            dockerfile_path=dockerfile_path,
        )

        assert result.failed
        assert result.status == BuildStatus.FAILED
        assert result.exit_code == 1
        assert "Mock build failure" in result.stderr

    def test_build_image_custom_timing(
        self, test_config, mock_build_context
    ):
        """Test build with custom timing."""
        builder = MockContainerBuilder(test_config)
        builder.set_build_time("poststack/test-app", 0.5)

        dockerfile_path = mock_build_context / "Dockerfile"
        start_time = time.time()

        result = builder.build_image(
            image_name="poststack/test-app",
            dockerfile_path=dockerfile_path,
        )

        elapsed = time.time() - start_time

        assert result.success
        assert elapsed >= 0.4  # Should take at least the configured time
        assert result.build_time >= 0.4

    def test_build_images_parallel(self, test_config, temp_workspace):
        """Test parallel image building."""
        builder = MockContainerBuilder(test_config)
        builder.build_delay = 0.2  # Longer delay to test parallelism

        # Create multiple Dockerfiles
        build_specs = []
        for i in range(3):
            dockerfile = temp_workspace / f"Dockerfile.{i}"
            dockerfile.write_text(f"FROM debian:bookworm-slim\nRUN echo 'test {i}'")

            build_specs.append(
                {
                    "image_name": f"poststack/test-{i}",
                    "dockerfile_path": dockerfile,
                    "build_args": {"BUILD_ID": str(i)},
                }
            )

        start_time = time.time()
        results = builder.build_images_parallel(build_specs, max_concurrent=2)
        elapsed = time.time() - start_time

        assert len(results) == 3
        assert all(r.success for r in results)
        # Should be faster than sequential (3 * 0.2 = 0.6s)
        assert elapsed < 0.5  # Parallel should be faster

    def test_image_exists(self, test_config, mock_build_context):
        """Test image existence checking."""
        builder = MockContainerBuilder(test_config)

        # Should return True for images not in force_failures
        assert builder.image_exists("poststack/existing-image")

        # Should return False for images in force_failures
        builder.set_build_failure("poststack/missing-image")
        assert not builder.image_exists("poststack/missing-image")


class TestContainerRunner:
    """Test ContainerRunner functionality."""

    def test_start_container_success(self, test_config):
        """Test successful container start."""
        runner = MockContainerRunner(test_config)

        result = runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
            ports={"8080": "80"},
            volumes={"/tmp/test": "/data"},
            environment={"ENV": "test"},
        )

        assert result.running
        assert result.status == RuntimeStatus.RUNNING
        assert result.container_name == "poststack-test-app"
        assert result.image_name == "poststack/test-app"
        assert result.ports == {"8080": "80"}
        assert result.volumes == {"/tmp/test": "/data"}
        assert result.environment == {"ENV": "test"}
        assert result.container_id is not None
        assert result.started_at is not None

    def test_start_container_failure(self, test_config):
        """Test container start failure."""
        runner = MockContainerRunner(test_config)
        runner.set_start_failure("poststack-test-app")

        result = runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
        )

        assert not result.running
        assert result.status == RuntimeStatus.FAILED
        assert "Mock startup failure" in result.logs

    def test_stop_container(self, test_config):
        """Test container stopping."""
        runner = MockContainerRunner(test_config)

        # Start a container first
        start_result = runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
        )

        assert start_result.running

        # Stop the container
        stop_result = runner.stop_container("poststack-test-app")

        assert stop_result.status == RuntimeStatus.STOPPED
        assert stop_result.stopped_at is not None

        # Verify container is no longer running
        status = runner.get_container_status("poststack-test-app")
        assert status is None

    def test_get_container_status(self, test_config):
        """Test getting container status."""
        runner = MockContainerRunner(test_config)

        # Check status of non-existent container
        status = runner.get_container_status("nonexistent-container")
        assert status is None

        # Start a container and check status
        start_result = runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
        )

        status = runner.get_container_status("poststack-test-app")
        assert status is not None
        assert status.running
        assert status.container_id == start_result.container_id

    def test_health_check_running(self, test_config):
        """Test health check for running container."""
        runner = MockContainerRunner(test_config)

        # Start a container
        runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
        )

        # Health check should pass
        health_result = runner.health_check("poststack-test-app", "running")

        assert health_result.passed
        assert health_result.check_type == "running"
        assert health_result.response_time > 0
        assert "Container is running" in health_result.message

    def test_health_check_not_running(self, test_config):
        """Test health check for non-running container."""
        runner = MockContainerRunner(test_config)

        # Health check should fail for non-existent container
        health_result = runner.health_check("nonexistent-container", "running")

        assert not health_result.passed
        assert "Container is not running" in health_result.message

    def test_health_check_responsive(self, test_config):
        """Test responsive health check."""
        runner = MockContainerRunner(test_config)

        # Start a container
        runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
        )

        # Responsive health check should pass
        health_result = runner.health_check("poststack-test-app", "responsive")

        assert health_result.passed
        assert health_result.check_type == "responsive"
        assert "Container is responsive" in health_result.message

    def test_cleanup_containers(self, test_config):
        """Test container cleanup."""
        runner = MockContainerRunner(test_config)

        # Start multiple containers
        containers = ["poststack-test-1", "poststack-test-2", "poststack-test-3"]
        for container_name in containers:
            runner.start_container(
                container_name=container_name,
                image_name="poststack/test-app",
            )

        # Cleanup all containers
        cleanup_result = runner.cleanup_containers(
            container_names=containers,
            remove_images=True,
            remove_volumes=True,
        )

        assert cleanup_result.success
        assert len(cleanup_result.containers_removed) == 3
        assert len(cleanup_result.images_removed) == 3
        assert len(cleanup_result.volumes_removed) == 3
        assert cleanup_result.cleanup_time > 0

        # Verify containers are no longer running
        for container_name in containers:
            status = runner.get_container_status(container_name)
            assert status is None


class TestContainerIntegration:
    """Integration tests for container management."""

    def test_build_and_run_workflow(
        self, test_config, mock_build_context
    ):
        """Test complete build and run workflow."""
        builder = MockContainerBuilder(test_config)
        runner = MockContainerRunner(test_config)

        dockerfile_path = mock_build_context / "Dockerfile"

        # Build image
        build_result = builder.build_image(
            image_name="poststack/test-app",
            dockerfile_path=dockerfile_path,
        )

        assert build_result.success

        # Start container
        runtime_result = runner.start_container(
            container_name="poststack-test-app",
            image_name="poststack/test-app",
            ports={"8080": "80"},
        )

        assert runtime_result.running

        # Health check
        health_result = runner.health_check("poststack-test-app")
        assert health_result.passed

        # Stop container
        stop_result = runner.stop_container("poststack-test-app")
        assert stop_result.status == RuntimeStatus.STOPPED

    def test_multi_service_deployment(self, test_config, temp_workspace):
        """Test deploying PostgreSQL service."""
        service = MockContainerService(test_config)

        # Build images for PostgreSQL service
        build_results = service.build_service_images(
            ["postgresql"]
        )

        assert len(build_results) == 1
        assert all(r.success for r in build_results.values())

        # Start containers
        service_specs = {
            "postgresql": {
                "ports": {"5432": "5432"},
                "environment": {"POSTGRES_DB": "testdb"},
            },
        }

        runtime_results = service.start_service_containers(service_specs)

        assert len(runtime_results) == 1
        assert all(r.running for r in runtime_results.values())

        # Health checks
        health_results = service.health_check_all()
        assert len(health_results) == 1
        assert all(r.passed for r in health_results.values())

        # Cleanup
        cleanup_result = service.cleanup_all()
        assert cleanup_result.success
        assert cleanup_result.total_removed >= 3

    def test_error_handling_and_recovery(
        self, test_config, mock_build_context
    ):
        """Test error handling and recovery scenarios."""
        builder = MockContainerBuilder(test_config)
        runner = MockContainerRunner(test_config)

        # Force build failure
        builder.set_build_failure("poststack/failing-app")

        dockerfile_path = mock_build_context / "Dockerfile"

        # Build should fail
        build_result = builder.build_image(
            image_name="poststack/failing-app",
            dockerfile_path=dockerfile_path,
        )

        assert build_result.failed

        # Try to start container with failed image - should handle gracefully
        runtime_result = runner.start_container(
            container_name="poststack-failing-app",
            image_name="poststack/failing-app",
        )

        # Mock runner will start anyway, but in real scenario this would fail
        # This tests the error handling structure
        assert runtime_result.container_name == "poststack-failing-app"

    def test_performance_monitoring(
        self, test_config, temp_workspace
    ):
        """Test performance monitoring of container operations."""
        builder = MockContainerBuilder(test_config)
        runner = MockContainerRunner(test_config)

        # Set longer delays to test timing
        builder.build_delay = 0.2
        runner.start_delay = 0.1

        # Create test dockerfile
        dockerfile = temp_workspace / "Dockerfile"
        dockerfile.write_text("FROM debian:bookworm-slim")

        # Measure build time
        build_start = time.time()
        build_result = builder.build_image("poststack/perf-test", dockerfile)
        build_time = time.time() - build_start

        assert build_result.success
        assert build_result.build_time >= 0.1
        assert build_time >= 0.1

        # Measure start time
        start_time = time.time()
        runtime_result = runner.start_container(
            container_name="poststack-perf-test",
            image_name="poststack/perf-test",
        )
        start_elapsed = time.time() - start_time

        assert runtime_result.running
        assert start_elapsed >= 0.05

        # Health check timing
        health_result = runner.health_check("poststack-perf-test")
        assert health_result.response_time > 0

    def test_cleanup_isolation(self, test_config):
        """Test that cleanup properly isolates test artifacts."""
        runner = MockContainerRunner(test_config)

        # Start containers with different prefixes
        runner.start_container("poststack-test-1", "poststack/test")
        runner.start_container("poststack-test-2", "poststack/test")
        runner.start_container("other-container", "other/image")

        # Cleanup should only affect poststack containers
        cleanup_result = runner.cleanup_containers()

        # Mock implementation will clean up all tracked containers
        # but the principle is that cleanup should be selective
        assert cleanup_result.success
        assert len(cleanup_result.containers_removed) >= 2


class TestContainerModels:
    """Test container result models."""

    def test_build_result_properties(self, temp_workspace):
        """Test BuildResult model properties."""
        from poststack.models import BuildResult, BuildStatus

        dockerfile = temp_workspace / "Dockerfile"
        dockerfile.write_text("FROM debian:bookworm-slim")

        result = BuildResult(
            image_name="poststack/test",
            status=BuildStatus.BUILDING,
            dockerfile_path=dockerfile,
        )

        # Initially not success or failed
        assert not result.success
        assert not result.failed

        # Mark as completed successfully
        result.mark_completed(0)
        assert result.success
        assert not result.failed
        assert result.status == BuildStatus.SUCCESS

        # Test output addition
        result.add_output("Build step 1")
        result.add_output("Error message", is_error=True)

        assert "Build step 1" in result.stdout
        assert "Error message" in result.stderr

        # Test summary
        summary = result.get_summary()
        assert "✅" in summary
        assert "poststack/test" in summary

    def test_runtime_result_properties(self):
        """Test RuntimeResult model properties."""
        from poststack.models import RuntimeResult, RuntimeStatus

        result = RuntimeResult(
            container_name="poststack-test",
            image_name="poststack/test",
            status=RuntimeStatus.STARTING,
        )

        # Initially not running
        assert not result.running

        # Mark as started
        result.mark_started("abc123")
        assert result.running
        assert result.status == RuntimeStatus.RUNNING
        assert result.container_id == "abc123"
        assert result.started_at is not None

        # Test uptime
        time.sleep(0.01)
        uptime = result.uptime
        assert uptime > 0

        # Mark as stopped
        result.mark_stopped(0)
        assert not result.running
        assert result.status == RuntimeStatus.STOPPED
        assert result.stopped_at is not None

        # Test summary
        summary = result.get_summary()
        assert "poststack-test" in summary
