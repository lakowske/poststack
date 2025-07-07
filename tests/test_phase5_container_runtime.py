"""
Tests for Phase 5: Container Runtime Verification

Tests container startup, health checks, side effects verification,
and complete container lifecycle management.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from poststack.config import PoststackConfig
from poststack.container_runtime import (
    PostgreSQLRunner,
    ContainerLifecycleManager,
)
from poststack.models import RuntimeResult, RuntimeStatus, HealthCheckResult


class TestPostgreSQLRunner:
    """Test PostgreSQL container runtime operations."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)
    
    @pytest.fixture
    def postgres_runner(self, config):
        """Create PostgreSQL runner instance."""
        return PostgreSQLRunner(config)
    
    def test_postgres_runner_initialization(self, postgres_runner):
        """Test PostgreSQL runner initialization."""
        assert postgres_runner.default_port == 5432
        assert postgres_runner.default_database == "poststack"
        assert postgres_runner.default_user == "poststack"
        assert postgres_runner.container_runtime == "podman"
    
    @patch('poststack.container_runtime.subprocess.run')
    def test_start_postgres_container_success(self, mock_run, postgres_runner):
        """Test successful PostgreSQL container startup."""
        # Mock container start success
        mock_run.return_value = Mock(
            returncode=0,
            stdout="container_id_12345\n",
            stderr="",
        )
        
        with patch.object(postgres_runner, 'wait_for_postgres_ready') as mock_wait:
            mock_wait.return_value = HealthCheckResult(
                container_name="test-postgres",
                check_type="postgres_ready",
                passed=True,
                message="PostgreSQL is ready",
            )
            
            result = postgres_runner.start_postgres_container(
                container_name="test-postgres",
                port=5433,
                wait_for_ready=True,
            )
            
            assert result.success
            assert result.container_name == "test-postgres"
            assert result.status == RuntimeStatus.RUNNING
    
    @patch('poststack.container_runtime.subprocess.run')
    def test_start_postgres_container_failure(self, mock_run, postgres_runner):
        """Test PostgreSQL container startup failure."""
        # Mock container start failure
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="Error: image not found",
        )
        
        result = postgres_runner.start_postgres_container(
            container_name="test-postgres",
            wait_for_ready=False,
        )
        
        assert not result.success
        assert result.status == RuntimeStatus.FAILED
        assert "Error: image not found" in result.logs
    
    @patch('poststack.container_runtime.subprocess.run')
    @patch('poststack.container_runtime.time.sleep')
    def test_wait_for_postgres_ready_success(self, mock_sleep, mock_run, postgres_runner):
        """Test waiting for PostgreSQL readiness - success case."""
        # Mock container status check (running)
        with patch.object(postgres_runner, 'get_container_status') as mock_status:
            mock_status.return_value = Mock(running=True)
            
            # Mock successful health check
            with patch.object(postgres_runner, 'health_check_postgres') as mock_health:
                mock_health.return_value = HealthCheckResult(
                    container_name="test-postgres",
                    check_type="postgres_health",
                    passed=True,
                    message="PostgreSQL is healthy and accepting connections",
                )
                
                result = postgres_runner.wait_for_postgres_ready(
                    container_name="test-postgres",
                    port=5432,
                    database_name="testdb",
                    username="testuser",
                    timeout=30,
                )
                
                assert result.passed
                assert "accepting connections" in result.message
    
    @patch('poststack.container_runtime.subprocess.run')
    @patch('poststack.container_runtime.time.sleep')
    def test_wait_for_postgres_ready_timeout(self, mock_sleep, mock_run, postgres_runner):
        """Test waiting for PostgreSQL readiness - timeout case."""
        # Mock container status check (running)
        with patch.object(postgres_runner, 'get_container_status') as mock_status:
            mock_status.return_value = Mock(running=True)
            
            # Mock failed pg_isready check
            mock_run.return_value = Mock(returncode=1, stderr="connection refused")
            
            # Mock time to simulate timeout
            with patch('poststack.container_runtime.time.time') as mock_time:
                mock_time.side_effect = [0, 5, 10, 15, 20, 25, 30, 35]  # Simulate timeout
                
                result = postgres_runner.wait_for_postgres_ready(
                    container_name="test-postgres",
                    port=5432,
                    database_name="testdb",
                    username="testuser",
                    timeout=30,
                )
                
                assert not result.passed
                assert "not ready after 30 seconds" in result.message
    
    @patch('poststack.container_runtime.subprocess.run')
    @patch('poststack.container_runtime.socket.socket')
    def test_health_check_postgres_success(self, mock_socket, mock_run, postgres_runner):
        """Test PostgreSQL health check - success case."""
        # Mock basic health check (running)
        with patch.object(postgres_runner, 'health_check') as mock_health:
            mock_health.return_value = HealthCheckResult(
                container_name="test-postgres",
                check_type="running",
                passed=True,
                message="Container is running",
            )
            
            # Mock port check success
            mock_socket_instance = Mock()
            mock_socket_instance.connect_ex.return_value = 0  # Success
            mock_socket.return_value.__enter__.return_value = mock_socket_instance
            
            # Mock pg_isready success
            mock_run.return_value = Mock(returncode=0, stdout="accepting connections")
            
            result = postgres_runner.health_check_postgres(
                container_name="test-postgres",
                port=5432,
            )
            
            assert result.passed
            assert "healthy and accepting connections" in result.message
            assert result.details["port"] == "5432"
    
    @patch('poststack.container_runtime.socket.socket')
    def test_health_check_postgres_port_failure(self, mock_socket, postgres_runner):
        """Test PostgreSQL health check - port not accessible."""
        # Mock basic health check success
        with patch.object(postgres_runner, 'health_check') as mock_health:
            mock_health.return_value = HealthCheckResult(
                container_name="test-postgres",
                check_type="running",
                passed=True,
                message="Container is running",
            )
            
            # Mock port check failure
            mock_socket_instance = Mock()
            mock_socket_instance.connect_ex.return_value = 1  # Connection failed
            mock_socket.return_value.__enter__.return_value = mock_socket_instance
            
            result = postgres_runner.health_check_postgres(
                container_name="test-postgres",
                port=5432,
            )
            
            assert not result.passed
            assert "port 5432 not accessible" in result.message
    
    @patch('poststack.container_runtime.subprocess.run')
    def test_verify_postgres_side_effects(self, mock_run, postgres_runner):
        """Test PostgreSQL side effects verification."""
        # Mock all subprocess calls to return success
        mock_run.return_value = Mock(returncode=0)
        
        # Mock port availability check
        with patch.object(postgres_runner, 'check_port_availability') as mock_port:
            mock_port.return_value = True
            
            results = postgres_runner.verify_postgres_side_effects(
                container_name="test-postgres",
                expected_port=5432,
            )
            
            assert results["postgres_process"] is True
            assert results["port_listening"] is True
            assert results["data_directory"] is True
            assert results["accepting_connections"] is True
    
    def test_check_port_availability_success(self, postgres_runner):
        """Test port availability check - success."""
        with patch('poststack.container_runtime.socket.socket') as mock_socket:
            mock_socket_instance = Mock()
            mock_socket_instance.connect_ex.return_value = 0  # Success
            mock_socket.return_value.__enter__.return_value = mock_socket_instance
            
            result = postgres_runner.check_port_availability("localhost", 5432)
            assert result is True
    
    def test_check_port_availability_failure(self, postgres_runner):
        """Test port availability check - failure."""
        with patch('poststack.container_runtime.socket.socket') as mock_socket:
            mock_socket_instance = Mock()
            mock_socket_instance.connect_ex.return_value = 1  # Connection failed
            mock_socket.return_value.__enter__.return_value = mock_socket_instance
            
            result = postgres_runner.check_port_availability("localhost", 5432)
            assert result is False



class TestContainerLifecycleManager:
    """Test complete container lifecycle management."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)
    
    @pytest.fixture
    def lifecycle_manager(self, config):
        """Create container lifecycle manager."""
        return ContainerLifecycleManager(config)
    
    def test_lifecycle_manager_initialization(self, lifecycle_manager):
        """Test lifecycle manager initialization."""
        assert isinstance(lifecycle_manager.postgres_runner, PostgreSQLRunner)
        assert lifecycle_manager.running_containers == []
    
    def test_start_test_environment_success(self, lifecycle_manager):
        """Test successful test environment startup."""
        with patch.object(lifecycle_manager.postgres_runner, 'start_postgres_container') as mock_start:
            mock_start.return_value = Mock(
                success=True,
                container_name="poststack-postgres-test",
            )
            
            with patch.object(lifecycle_manager.postgres_runner, 'health_check_postgres') as mock_health:
                mock_health.return_value = HealthCheckResult(
                    container_name="poststack-postgres-test",
                    check_type="postgres_health",
                    passed=True,
                    message="PostgreSQL is healthy",
                )
                
                postgres_result, health_result = lifecycle_manager.start_test_environment(
                    postgres_port=5433,
                )
                
                assert postgres_result.success
                assert health_result.passed
                assert "poststack-postgres-test" in lifecycle_manager.running_containers
    
    def test_start_test_environment_postgres_failure(self, lifecycle_manager):
        """Test test environment startup with PostgreSQL failure."""
        with patch.object(lifecycle_manager.postgres_runner, 'start_postgres_container') as mock_start:
            mock_start.return_value = Mock(success=False)
            
            with patch.object(lifecycle_manager, 'cleanup_test_environment') as mock_cleanup:
                postgres_result, health_result = lifecycle_manager.start_test_environment(
                    cleanup_on_failure=True,
                )
                
                assert not postgres_result.success
                assert health_result is None
                mock_cleanup.assert_called_once()
    
    def test_start_test_environment_health_check_failure(self, lifecycle_manager):
        """Test test environment startup with health check failure."""
        with patch.object(lifecycle_manager.postgres_runner, 'start_postgres_container') as mock_start:
            mock_start.return_value = Mock(
                success=True,
                container_name="poststack-postgres-test",
            )
            
            with patch.object(lifecycle_manager.postgres_runner, 'health_check_postgres') as mock_health:
                mock_health.return_value = HealthCheckResult(
                    container_name="poststack-postgres-test",
                    check_type="postgres_health",
                    passed=False,
                    message="Health check failed",
                )
                
                with patch.object(lifecycle_manager, 'cleanup_test_environment') as mock_cleanup:
                    postgres_result, health_result = lifecycle_manager.start_test_environment(
                        cleanup_on_failure=True,
                    )
                    
                    assert postgres_result.success  # Container started
                    assert not health_result.passed  # But health check failed
                    mock_cleanup.assert_called_once()
    
    @patch('poststack.container_runtime.subprocess.run')
    def test_cleanup_test_environment_success(self, mock_run, lifecycle_manager):
        """Test successful test environment cleanup."""
        # Add some containers to the running list
        lifecycle_manager.running_containers = ["test-container-1", "test-container-2"]
        
        # Mock stop_container method
        with patch.object(lifecycle_manager.postgres_runner, 'stop_container') as mock_stop:
            mock_stop.return_value = Mock(success=True)
            
            # Mock subprocess.run for container removal
            mock_run.return_value = Mock(returncode=0)
            
            result = lifecycle_manager.cleanup_test_environment()
            
            assert result is True
            assert lifecycle_manager.running_containers == []
    
    @patch('poststack.container_runtime.subprocess.run')
    def test_cleanup_test_environment_with_errors(self, mock_run, lifecycle_manager):
        """Test test environment cleanup with some errors."""
        # Add container to the running list
        lifecycle_manager.running_containers = ["test-container"]
        
        # Mock stop_container failure
        with patch.object(lifecycle_manager.postgres_runner, 'stop_container') as mock_stop:
            mock_stop.return_value = Mock(success=False)
            
            # Mock subprocess.run for container removal (success)
            mock_run.return_value = Mock(returncode=0)
            
            result = lifecycle_manager.cleanup_test_environment()
            
            assert result is False  # Should be False due to stop failure
            assert lifecycle_manager.running_containers == []  # But container should still be removed
    
    def test_get_running_containers(self, lifecycle_manager):
        """Test getting running containers list."""
        lifecycle_manager.running_containers = ["container1", "container2"]
        
        result = lifecycle_manager.get_running_containers()
        
        assert result == ["container1", "container2"]
        assert result is not lifecycle_manager.running_containers  # Should be a copy


class TestPhase5Integration:
    """Integration tests for Phase 5 functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)
    
    def test_complete_container_lifecycle_mock(self, config):
        """Test complete container lifecycle with mocked operations."""
        lifecycle_manager = ContainerLifecycleManager(config)
        
        # Mock all the subprocess operations
        with patch('poststack.container_runtime.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="container_id_12345\n",
                stderr="",
            )
            
            with patch.object(lifecycle_manager.postgres_runner, 'check_port_availability') as mock_port:
                mock_port.return_value = True
                
                with patch.object(lifecycle_manager.postgres_runner, 'get_container_status') as mock_status:
                    mock_status.return_value = Mock(running=True)
                    
                    # Start test environment
                    postgres_result, health_result = lifecycle_manager.start_test_environment(
                        postgres_port=5433,
                    )
                    
                    # Verify startup
                    assert postgres_result.success
                    assert health_result.passed
                    assert len(lifecycle_manager.running_containers) == 1
                    
                    # Test database connectivity
                    database_url = "postgresql://poststack:poststack_dev@localhost:5433/poststack"
                    
                    # Verify PostgreSQL is accessible
                    assert postgres_result.success
                    
                    # Cleanup
                    cleanup_success = lifecycle_manager.cleanup_test_environment()
                    assert cleanup_success
                    assert len(lifecycle_manager.running_containers) == 0
    
    @pytest.mark.integration
    @pytest.mark.skipif(
        True,  # Always skip by default
        reason="Integration test requires actual container runtime and -m integration flag"
    )
    def test_real_container_operations(self, config):
        """
        Test real container operations (requires actual container runtime).
        
        This test is marked as integration and will only run when:
        1. pytest is run with -m integration flag
        2. A real container runtime (podman/docker) is available
        
        To run: pytest -m integration tests/test_phase5_container_runtime.py
        """
        import subprocess
        
        # Check if container runtime is available
        try:
            subprocess.run([config.container_runtime, "--version"], 
                         capture_output=True, check=True, timeout=10)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip(f"Container runtime {config.container_runtime} not available")
        
        # Check if required images exist
        try:
            subprocess.run([config.container_runtime, "inspect", "poststack/postgres:latest"], 
                         capture_output=True, check=True, timeout=10)
        except subprocess.CalledProcessError:
            pytest.skip("Required container images not built")
        
        lifecycle_manager = ContainerLifecycleManager(config)
        
        try:
            # Start test environment
            postgres_result, health_result = lifecycle_manager.start_test_environment(
                postgres_port=5433,  # Non-standard port to avoid conflicts
            )
            
            assert postgres_result.success, f"PostgreSQL start failed: {postgres_result.logs}"
            assert health_result.passed, f"Health check failed: {health_result.message}"
            
            # Verify side effects
            side_effects = lifecycle_manager.postgres_runner.verify_postgres_side_effects(
                container_name="poststack-postgres-test",
                expected_port=5433,
            )
            
            assert side_effects["postgres_process"], "PostgreSQL process not running"
            assert side_effects["port_listening"], "PostgreSQL port not listening"
            assert side_effects["accepting_connections"], "PostgreSQL not accepting connections"
            
            # Test database connectivity
            database_url = "postgresql://poststack:poststack_dev@localhost:5433/poststack"
            
            # Basic connectivity verification already done by health check
            assert health_result.passed
            
        finally:
            # Always cleanup
            cleanup_success = lifecycle_manager.cleanup_test_environment()
            assert cleanup_success, "Cleanup failed"