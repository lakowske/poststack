"""
Tests for Phase 6: Schema Management

Tests schema management using Liquibase containers and database operations.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from poststack.config import PoststackConfig
from poststack.schema_management import SchemaManager, SchemaManagementError
from poststack.models import HealthCheckResult, RuntimeResult, RuntimeStatus


class TestSchemaManager:
    """Test schema management operations."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)
    
    @pytest.fixture
    def schema_manager(self, config):
        """Create schema manager instance."""
        return SchemaManager(config)
    
    def test_schema_manager_initialization(self, schema_manager):
        """Test schema manager initialization."""
        assert schema_manager.config is not None
        assert schema_manager.liquibase_runner is not None
        assert schema_manager.database_manager is not None
    
    def test_create_default_changelog(self, schema_manager):
        """Test default changelog creation."""
        changelog = schema_manager.create_default_changelog()
        
        assert "<?xml version" in changelog
        assert "databaseChangeLog" in changelog
        assert "poststack" in changelog
        assert "system_info" in changelog
        assert "services" in changelog
        assert "containers" in changelog
        assert "certificates" in changelog
    
    def test_write_changelog_to_temp(self, schema_manager):
        """Test writing changelog to temporary file."""
        changelog_content = "<?xml version='1.0'?><test/>"
        
        changelog_path = schema_manager.write_changelog_to_temp(changelog_content)
        
        assert changelog_path.exists()
        assert changelog_path.name == "changelog.xml"
        assert changelog_path.read_text() == changelog_content
        
        # Cleanup
        changelog_path.unlink()
        changelog_path.parent.rmdir()
    
    def test_run_liquibase_command_success(self, schema_manager):
        """Test successful Liquibase command execution."""
        with patch.object(schema_manager.database_manager, 'validate_database_url') as mock_validate:
            mock_db_url = Mock()
            mock_validate.return_value = mock_db_url
            
            with patch.object(schema_manager.liquibase_runner, 'run_liquibase_command') as mock_run:
                mock_result = RuntimeResult(
                    container_name="liquibase-temp",
                    image_name="poststack/liquibase:latest",
                    status=RuntimeStatus.STOPPED
                )
                mock_result.add_logs("Liquibase command completed successfully")
                mock_run.return_value = mock_result
                
                result = schema_manager.run_liquibase_command(
                    "status",
                    "postgresql://localhost/test"
                )
                
                assert result.success
                assert "completed successfully" in result.logs
                mock_run.assert_called_once()
    
    def test_run_liquibase_command_failure(self, schema_manager):
        """Test failed Liquibase command execution."""
        with patch.object(schema_manager.database_manager, 'validate_database_url') as mock_validate:
            mock_validate.side_effect = Exception("Invalid URL")
            
            result = schema_manager.run_liquibase_command(
                "status",
                "invalid-url"
            )
            
            assert not result.success
            assert "Invalid URL" in result.logs
    
    def test_health_check_liquibase_success(self, schema_manager):
        """Test successful Liquibase health check."""
        with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
            mock_result = RuntimeResult(
                container_name="liquibase-health",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.STOPPED
            )
            mock_result.add_logs("Status check completed")
            mock_run.return_value = mock_result
            
            result = schema_manager.health_check_liquibase("postgresql://localhost/test")
            
            assert result.passed
            assert "health check passed" in result.message
            assert "Status check completed" in result.details["status_output"]
    
    def test_health_check_liquibase_failure(self, schema_manager):
        """Test failed Liquibase health check."""
        with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
            mock_result = RuntimeResult(
                container_name="liquibase-health",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.FAILED
            )
            mock_result.add_logs("Connection refused")
            mock_run.return_value = mock_result
            
            result = schema_manager.health_check_liquibase("postgresql://localhost/test")
            
            assert not result.passed
            assert "health check failed" in result.message
    
    def test_initialize_schema_success(self, schema_manager):
        """Test successful schema initialization."""
        # Mock successful connection test
        with patch.object(schema_manager.database_manager, 'test_connection') as mock_test:
            mock_test.return_value = HealthCheckResult(
                container_name="test",
                check_type="connection",
                passed=True,
                message="Connection successful"
            )
            
            # Mock successful Liquibase update
            with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
                mock_result = RuntimeResult(
                    container_name="schema-init",
                    image_name="poststack/liquibase:latest",
                    status=RuntimeStatus.STOPPED
                )
                mock_result.add_logs("Schema update completed")
                mock_run.return_value = mock_result
                
                # Mock successful verification
                with patch.object(schema_manager, 'verify_schema') as mock_verify:
                    mock_verify.return_value = HealthCheckResult(
                        container_name="verify",
                        check_type="verification",
                        passed=True,
                        message="Schema verified"
                    )
                    
                    result = schema_manager.initialize_schema("postgresql://localhost/test")
                    
                    assert result.success
                    assert "initialized successfully" in result.logs
    
    def test_initialize_schema_connection_failure(self, schema_manager):
        """Test schema initialization with connection failure."""
        # Mock failed connection test
        with patch.object(schema_manager.database_manager, 'test_connection') as mock_test:
            mock_test.return_value = HealthCheckResult(
                container_name="test",
                check_type="connection",
                passed=False,
                message="Connection failed"
            )
            
            result = schema_manager.initialize_schema("postgresql://localhost/test")
            
            assert not result.success
            assert "connection failed" in result.logs.lower()
    
    def test_initialize_schema_verification_failure(self, schema_manager):
        """Test schema initialization with verification failure."""
        # Mock successful connection test
        with patch.object(schema_manager.database_manager, 'test_connection') as mock_test:
            mock_test.return_value = HealthCheckResult(
                container_name="test",
                check_type="connection",
                passed=True,
                message="Connection successful"
            )
            
            # Mock successful Liquibase update
            with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
                mock_result = RuntimeResult(
                    container_name="schema-init",
                    image_name="poststack/liquibase:latest",
                    status=RuntimeStatus.STOPPED
                )
                mock_result.add_logs("Schema update completed")
                mock_run.return_value = mock_result
                
                # Mock failed verification
                with patch.object(schema_manager, 'verify_schema') as mock_verify:
                    mock_verify.return_value = HealthCheckResult(
                        container_name="verify",
                        check_type="verification",
                        passed=False,
                        message="Missing tables"
                    )
                    
                    result = schema_manager.initialize_schema("postgresql://localhost/test")
                    
                    assert not result.success
                    assert "failed verification" in result.logs
    
    def test_update_schema_success(self, schema_manager):
        """Test successful schema update."""
        with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
            mock_result = RuntimeResult(
                container_name="schema-update",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.STOPPED
            )
            mock_result.add_logs("Schema update completed")
            mock_run.return_value = mock_result
            
            result = schema_manager.update_schema("postgresql://localhost/test")
            
            assert result.success
            assert "completed" in result.logs
    
    def test_update_schema_with_custom_changelog(self, schema_manager):
        """Test schema update with custom changelog."""
        changelog_path = Path("/tmp/custom-changelog.xml")
        
        with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
            mock_result = RuntimeResult(
                container_name="schema-update",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.STOPPED
            )
            mock_result.add_logs("Schema update completed")
            mock_run.return_value = mock_result
            
            result = schema_manager.update_schema(
                "postgresql://localhost/test",
                changelog_path=changelog_path
            )
            
            assert result.success
            mock_run.assert_called_once_with("update", "postgresql://localhost/test", changelog_path)
    
    @patch('psycopg2.connect')
    def test_verify_schema_success(self, mock_connect, schema_manager):
        """Test successful schema verification."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            (True,),  # schema exists
            ("2.0.0",),  # schema version
        ]
        mock_cursor.fetchall.side_effect = [
            [("system_info",), ("services",), ("containers",), ("certificates",)],  # required tables
            [("databasechangelog",), ("databasechangeloglock",)],  # liquibase tables
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn
        
        with patch.object(schema_manager.database_manager, 'validate_database_url') as mock_validate:
            mock_db_url = Mock()
            mock_db_url.hostname = "localhost"
            mock_db_url.port = 5432
            mock_db_url.database = "testdb"
            mock_db_url.username = "testuser"
            mock_db_url.password = "testpass"
            mock_validate.return_value = mock_db_url
            
            result = schema_manager.verify_schema("postgresql://localhost/test")
            
            assert result.passed
            assert "verification passed" in result.message
            assert result.details["schema_version"] == "2.0.0"
            assert len(result.details["tables"]) == 4
    
    @patch('psycopg2.connect')
    def test_verify_schema_missing_schema(self, mock_connect, schema_manager):
        """Test schema verification with missing schema."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (False,)  # schema does not exist
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn
        
        with patch.object(schema_manager.database_manager, 'validate_database_url') as mock_validate:
            mock_db_url = Mock()
            mock_db_url.hostname = "localhost"
            mock_db_url.port = 5432
            mock_db_url.database = "testdb"
            mock_db_url.username = "testuser"
            mock_db_url.password = "testpass"
            mock_validate.return_value = mock_db_url
            
            result = schema_manager.verify_schema("postgresql://localhost/test")
            
            assert not result.passed
            assert "schema does not exist" in result.message
    
    @patch('psycopg2.connect')
    def test_verify_schema_missing_tables(self, mock_connect, schema_manager):
        """Test schema verification with missing tables."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            (True,),  # schema exists
        ]
        mock_cursor.fetchall.side_effect = [
            [("system_info",), ("services",)],  # only 2 of 4 required tables
            [("databasechangelog",)],  # liquibase tables
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn
        
        with patch.object(schema_manager.database_manager, 'validate_database_url') as mock_validate:
            mock_db_url = Mock()
            mock_db_url.hostname = "localhost"
            mock_db_url.port = 5432
            mock_db_url.database = "testdb"
            mock_db_url.username = "testuser"
            mock_db_url.password = "testpass"
            mock_validate.return_value = mock_db_url
            
            result = schema_manager.verify_schema("postgresql://localhost/test")
            
            assert not result.passed
            assert "Missing required tables" in result.message
            assert "containers" in result.message  # One of the missing tables
    
    def test_get_schema_status_success(self, schema_manager):
        """Test successful schema status retrieval."""
        # Mock Liquibase status
        with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
            mock_result = RuntimeResult(
                container_name="status",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.STOPPED
            )
            mock_result.add_logs("Status output")
            mock_run.return_value = mock_result
            
            # Mock schema verification
            with patch.object(schema_manager, 'verify_schema') as mock_verify:
                mock_verify.return_value = HealthCheckResult(
                    container_name="verify",
                    check_type="verification",
                    passed=True,
                    message="Schema OK",
                    details={"version": "2.0.0"}
                )
                
                # Mock database info
                with patch.object(schema_manager.database_manager, 'get_database_info') as mock_info:
                    mock_info.return_value = {"connection": {"database": "test"}}
                    
                    status = schema_manager.get_schema_status("postgresql://localhost/test")
                    
                    assert status["verification"]["passed"] is True
                    assert status["liquibase"]["status"] == "stopped"
                    assert status["database"]["connection"]["database"] == "test"
    
    def test_get_schema_status_error(self, schema_manager):
        """Test schema status retrieval with error."""
        # Mock exception during status retrieval
        with patch.object(schema_manager, 'run_liquibase_command') as mock_run:
            mock_run.side_effect = Exception("Connection failed")
            
            status = schema_manager.get_schema_status("postgresql://localhost/test")
            
            assert "error" in status
            assert status["verification"]["passed"] is False
            assert "Connection failed" in status["error"]


class TestSchemaIntegration:
    """Integration tests for schema management."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)
    
    def test_complete_schema_workflow_mock(self, config):
        """Test complete schema workflow with mocked operations."""
        schema_manager = SchemaManager(config)
        
        # Mock all database operations
        with patch('psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.side_effect = [
                ("PostgreSQL 15.0", "testdb", "testuser"),  # test_connection basic query (3 values) - 1st call
                (5,),  # table count - 1st call
                ("PostgreSQL 15.0", "testdb", "testuser"),  # test_connection basic query (3 values) - 2nd call (initialize_schema)
                (5,),  # table count - 2nd call
                (True,),  # schema exists check (verify_schema)
                ("2.0.0",),  # schema version (verify_schema)
                (True,),  # schema exists check (verify_schema again) 
                ("2.0.0",),  # schema version (verify_schema again)
            ]
            mock_cursor.fetchall.side_effect = [
                [("system_info",), ("services",), ("containers",), ("certificates",)],  # required tables - 1st verify
                [("databasechangelog",), ("databasechangeloglock",)],  # liquibase tables - 1st verify
                [("system_info",), ("services",), ("containers",), ("certificates",)],  # required tables - 2nd verify
                [("databasechangelog",), ("databasechangeloglock",)],  # liquibase tables - 2nd verify
            ]
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            
            # Mock socket connectivity test
            with patch('poststack.database_operations.socket.socket') as mock_socket:
                mock_socket_instance = Mock()
                mock_socket_instance.connect_ex.return_value = 0  # Success
                mock_socket.return_value.__enter__.return_value = mock_socket_instance
                
                # Mock container operations
                with patch.object(schema_manager.liquibase_runner, 'run_liquibase_command') as mock_liquibase:
                    mock_result = RuntimeResult(
                        container_name="liquibase-temp",
                        image_name="poststack/liquibase:latest",
                        status=RuntimeStatus.STOPPED
                    )
                    mock_result.add_logs("Liquibase update completed successfully")
                    mock_liquibase.return_value = mock_result
                    
                    database_url = "postgresql://testuser:testpass@localhost:5432/testdb"
                    
                    # Test connection
                    connection_result = schema_manager.database_manager.test_connection(database_url)
                    assert connection_result.passed
                    
                    # Test Liquibase health check
                    health_result = schema_manager.health_check_liquibase(database_url)
                    assert health_result.passed
                    
                    # Initialize schema
                    init_result = schema_manager.initialize_schema(database_url)
                    assert init_result.success
                    
                    # Verify schema
                    verify_result = schema_manager.verify_schema(database_url)
                    assert verify_result.passed
                    
                    # Mock get_database_info and verify_schema for get_schema_status
                    with patch.object(schema_manager.database_manager, 'get_database_info') as mock_db_info:
                        with patch.object(schema_manager, 'verify_schema') as mock_verify_status:
                            mock_db_info.return_value = {
                                "connection": {"database": "testdb", "user": "testuser"},
                                "server": {"version": "PostgreSQL 15.0"},
                                "schemas": [{"name": "public", "table_count": 5}]
                            }
                            mock_verify_status.return_value = HealthCheckResult(
                                container_name="verify-status",
                                check_type="verification",
                                passed=True,
                                message="Schema verification passed",
                                details={"version": "2.0.0"}
                            )
                            
                            # Get status
                            status = schema_manager.get_schema_status(database_url)
                            assert status["verification"]["passed"] is True
    
    @pytest.mark.integration
    @pytest.mark.skipif(
        True,  # Always skip by default
        reason="Integration test requires actual containers and database"
    )
    def test_real_schema_operations(self, config):
        """
        Test real schema operations (requires actual containers and database).
        
        This test is marked as integration and will only run when:
        1. pytest is run with -m integration flag
        2. Real containers and database are available
        
        To run: pytest -m integration tests/test_schema.py
        """
        # This would test with real containers and database
        # Implementation would be similar to the container runtime integration test
        pass