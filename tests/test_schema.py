"""
Tests for Schema Management using SQL-based migrations

Tests schema management using the new SQL migration system.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from poststack.config import PoststackConfig
from poststack.models import HealthCheckResult, RuntimeResult, RuntimeStatus
from poststack.schema_management import SchemaManager, SchemaManagementError


class TestSchemaManager:
    """Test schema management operations."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)

    @pytest.fixture
    def temp_migrations_dir(self):
        """Create temporary migrations directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            migrations_path = Path(temp_dir) / "migrations"
            migrations_path.mkdir()

            # Create sample migrations
            (migrations_path / "001_initial_schema.sql").write_text("""
-- Description: Create initial schema
CREATE SCHEMA IF NOT EXISTS poststack;
CREATE TABLE poststack.system_info (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
            """)

            (migrations_path / "001_initial_schema.rollback.sql").write_text("""
DROP SCHEMA IF EXISTS poststack CASCADE;
            """)

            yield str(migrations_path)

    @pytest.fixture
    def schema_manager(self, config, temp_migrations_dir):
        """Create schema manager instance."""
        config.migrations_path = temp_migrations_dir
        return SchemaManager(config)

    def test_schema_manager_initialization(self, schema_manager):
        """Test schema manager initialization."""
        assert schema_manager.config is not None
        assert schema_manager.database_manager is not None
        assert schema_manager.migrations_path is not None

    def test_get_migration_runner(self, schema_manager):
        """Test migration runner creation."""
        database_url = "postgresql://test:test@localhost:5432/test"
        with patch('poststack.schema_migration.psycopg2.connect'):
            runner = schema_manager._get_migration_runner(database_url)

            assert runner is not None
            assert runner.database_url == database_url

    @patch('psycopg2.connect')
    def test_initialize_schema_success(self, mock_connect, schema_manager):
        """Test successful schema initialization."""
        # Mock database connection test
        with patch.object(schema_manager.database_manager, 'test_connection') as mock_test:
            mock_test.return_value = HealthCheckResult(
                container_name="test",
                check_type="connection",
                passed=True,
                message="Connection successful"
            )

            # Mock migration runner
            with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
                mock_runner = Mock()
                mock_result = Mock()
                mock_result.success = True
                mock_result.message = "Migrations applied successfully"
                mock_runner.migrate.return_value = mock_result
                mock_runner_factory.return_value = mock_runner

                # Mock schema verification
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

    @patch('psycopg2.connect')
    def test_initialize_schema_connection_failure(self, mock_connect, schema_manager):
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

    def test_update_schema_success(self, schema_manager):
        """Test successful schema update."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_result = Mock()
            mock_result.success = True
            mock_result.message = "Schema updated successfully"
            mock_runner.migrate.return_value = mock_result
            mock_runner_factory.return_value = mock_runner

            result = schema_manager.update_schema("postgresql://localhost/test")

            assert result.success
            mock_runner.migrate.assert_called_once_with(target_version=None)

    def test_update_schema_with_target_version(self, schema_manager):
        """Test schema update with target version."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_result = Mock()
            mock_result.success = True
            mock_result.message = "Schema updated to version 002"
            mock_runner.migrate.return_value = mock_result
            mock_runner_factory.return_value = mock_runner

            result = schema_manager.update_schema("postgresql://localhost/test", target_version="002")

            assert result.success
            mock_runner.migrate.assert_called_once_with(target_version="002")

    def test_rollback_schema(self, schema_manager):
        """Test schema rollback."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_result = Mock()
            mock_result.success = True
            mock_result.message = "Schema rolled back to version 001"
            mock_runner.rollback.return_value = mock_result
            mock_runner_factory.return_value = mock_runner

            result = schema_manager.rollback_schema("postgresql://localhost/test", "001")

            assert result.success
            assert "rolled back" in result.logs
            mock_runner.rollback.assert_called_once_with(target_version="001")

    @patch('psycopg2.connect')
    def test_verify_schema_success(self, mock_connect, schema_manager):
        """Test successful schema verification."""
        # Mock database connection
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.side_effect = [
            (True,),  # schema exists
            ("1.0.0",),  # schema version
        ]
        mock_cursor.fetchall.side_effect = [
            [("system_info",), ("services",), ("containers",), ("certificates",)],  # required tables
            [("schema_migrations",), ("schema_migration_lock",)],  # migration tables
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
            assert result.details["schema_version"] == "1.0.0"
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
            [("schema_migrations",)],  # migration tables
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
        # Mock migration status
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_status = Mock()
            mock_status.current_version = "002"
            mock_status.applied_migrations = []
            mock_status.pending_migrations = []
            mock_status.is_locked = False
            mock_status.lock_info = None
            mock_runner.status.return_value = mock_status
            mock_runner_factory.return_value = mock_runner

            # Mock schema verification
            with patch.object(schema_manager, 'verify_schema') as mock_verify:
                mock_verify.return_value = HealthCheckResult(
                    container_name="verify",
                    check_type="verification",
                    passed=True,
                    message="Schema OK",
                    details={"schema_version": "1.0.0"}
                )

                # Mock database info
                with patch.object(schema_manager.database_manager, 'get_database_info') as mock_info:
                    mock_info.return_value = {"connection": {"database": "test"}}

                    status = schema_manager.get_schema_status("postgresql://localhost/test")

                    assert status["verification"]["passed"] is True
                    assert status["migration"]["current_version"] == "002"
                    assert status["database"]["connection"]["database"] == "test"

    def test_get_migration_status_success(self, schema_manager):
        """Test getting detailed migration status."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()

            # Mock applied migrations
            from datetime import datetime
            applied_migration = Mock()
            applied_migration.version = "001"
            applied_migration.description = "Initial schema"
            applied_migration.applied_at = datetime.now()
            applied_migration.execution_time_ms = 100
            applied_migration.applied_by = "test_user"

            # Mock pending migrations
            pending_migration = Mock()
            pending_migration.version = "002"
            pending_migration.name = "add_indexes"
            pending_migration.get_description.return_value = "Add performance indexes"

            mock_status = Mock()
            mock_status.current_version = "001"
            mock_status.applied_migrations = [applied_migration]
            mock_status.pending_migrations = [pending_migration]
            mock_status.is_locked = False
            mock_status.lock_info = None

            mock_runner.status.return_value = mock_status
            mock_runner_factory.return_value = mock_runner

            status = schema_manager.get_migration_status("postgresql://localhost/test")

            assert status["current_version"] == "001"
            assert len(status["applied_migrations"]) == 1
            assert len(status["pending_migrations"]) == 1
            assert status["applied_migrations"][0]["version"] == "001"
            assert status["pending_migrations"][0]["version"] == "002"

    def test_verify_migrations_success(self, schema_manager):
        """Test successful migration verification."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_verification = Mock()
            mock_verification.valid = True
            mock_verification.errors = []
            mock_verification.warnings = []
            mock_runner.verify.return_value = mock_verification
            mock_runner_factory.return_value = mock_runner

            result = schema_manager.verify_migrations("postgresql://localhost/test")

            assert result["valid"] is True
            assert len(result["errors"]) == 0
            assert len(result["warnings"]) == 0

    def test_verify_migrations_with_errors(self, schema_manager):
        """Test migration verification with errors."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_verification = Mock()
            mock_verification.valid = False
            mock_verification.errors = ["Checksum mismatch for migration 001"]
            mock_verification.warnings = ["Migration 002 file not found"]
            mock_runner.verify.return_value = mock_verification
            mock_runner_factory.return_value = mock_runner

            result = schema_manager.verify_migrations("postgresql://localhost/test")

            assert result["valid"] is False
            assert len(result["errors"]) == 1
            assert len(result["warnings"]) == 1
            assert "Checksum mismatch" in result["errors"][0]

    def test_force_unlock_migrations(self, schema_manager):
        """Test forcing unlock of migrations."""
        with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
            mock_runner = Mock()
            mock_runner.force_unlock.return_value = True
            mock_runner_factory.return_value = mock_runner

            result = schema_manager.force_unlock_migrations("postgresql://localhost/test")

            assert result is True
            mock_runner.force_unlock.assert_called_once()


class TestSchemaIntegration:
    """Integration tests for schema management."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)

    @pytest.fixture
    def temp_migrations_dir(self):
        """Create temporary migrations directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            migrations_path = Path(temp_dir) / "migrations"
            migrations_path.mkdir()

            # Create realistic migrations matching poststack schema
            (migrations_path / "001_initial_schema.sql").write_text("""
-- Description: Create initial poststack schema
CREATE SCHEMA IF NOT EXISTS poststack;

CREATE TABLE poststack.system_info (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE poststack.services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'stopped',
    config JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
            """)

            (migrations_path / "001_initial_schema.rollback.sql").write_text("""
DROP SCHEMA IF EXISTS poststack CASCADE;
            """)

            (migrations_path / "002_add_indexes.sql").write_text("""
-- Description: Add performance indexes
CREATE INDEX idx_system_info_key ON poststack.system_info(key);
CREATE INDEX idx_services_type ON poststack.services(type);
CREATE INDEX idx_services_status ON poststack.services(status);
            """)

            (migrations_path / "002_add_indexes.rollback.sql").write_text("""
DROP INDEX IF EXISTS poststack.idx_system_info_key;
DROP INDEX IF EXISTS poststack.idx_services_type;
DROP INDEX IF EXISTS poststack.idx_services_status;
            """)

            yield str(migrations_path)

    @pytest.mark.skip(reason="Complex database mocking - to be fixed separately")
    def test_complete_schema_workflow_mock(self, config, temp_migrations_dir):
        """Test complete schema workflow with mocked operations."""
        config.migrations_path = temp_migrations_dir
        schema_manager = SchemaManager(config)

        # Mock all database operations
        with patch('psycopg2.connect') as mock_connect:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.side_effect = [
                ("PostgreSQL 15.0", "testdb", "testuser"),  # test_connection basic query
                (5,),  # table count for test_connection
                (True,),  # schema exists check (verify_schema)
                ("1.0.0",),  # schema version (verify_schema)
            ]
            mock_cursor.fetchall.side_effect = [
                [("system_info",), ("services",)],  # required tables
                [("schema_migrations",), ("schema_migration_lock",)],  # migration tables
            ]
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            # Mock socket connectivity test
            with patch('poststack.database_operations.socket.socket') as mock_socket:
                mock_socket_instance = Mock()
                mock_socket_instance.connect_ex.return_value = 0  # Success
                mock_socket.return_value.__enter__.return_value = mock_socket_instance

                # Mock migration operations
                with patch.object(schema_manager, '_get_migration_runner') as mock_runner_factory:
                    mock_runner = Mock()

                    # Mock successful migration
                    mock_result = Mock()
                    mock_result.success = True
                    mock_result.message = "Applied 2 migration(s)"
                    mock_result.version = "002"
                    mock_runner.migrate.return_value = mock_result

                    # Mock migration status
                    mock_status = Mock()
                    mock_status.current_version = "002"
                    mock_status.applied_migrations = []
                    mock_status.pending_migrations = []
                    mock_status.is_locked = False
                    mock_status.lock_info = None
                    mock_runner.status.return_value = mock_status

                    mock_runner_factory.return_value = mock_runner

                    database_url = "postgresql://testuser:testpass@localhost:5432/testdb"

                    # Test connection
                    connection_result = schema_manager.database_manager.test_connection(database_url)
                    assert connection_result.passed

                    # Initialize schema
                    init_result = schema_manager.initialize_schema(database_url)
                    assert init_result.success

                    # Verify schema
                    verify_result = schema_manager.verify_schema(database_url)
                    assert verify_result.passed

                    # Get migration status
                    migration_status = schema_manager.get_migration_status(database_url)
                    assert migration_status["current_version"] == "002"

                    # Get schema status
                    with patch.object(schema_manager.database_manager, 'get_database_info') as mock_db_info:
                        mock_db_info.return_value = {
                            "connection": {"database": "testdb", "user": "testuser"},
                            "server": {"version": "PostgreSQL 15.0"}
                        }

                        status = schema_manager.get_schema_status(database_url)
                        assert status["verification"]["passed"] is True
                        assert status["migration"]["current_version"] == "002"