"""
Tests for SQL-based schema migration system

Tests the schema migration functionality for managing database schema changes.
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from poststack.schema_migration import (
    Migration,
    MigrationRunner,
    MigrationError,
)


class TestMigration:
    """Test Migration class functionality."""

    def test_migration_initialization(self):
        """Test migration initialization with SQL files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test migration files
            migration_file = temp_path / "001_test_migration.sql"
            rollback_file = temp_path / "001_test_migration.rollback.sql"

            migration_file.write_text("CREATE TABLE test (id SERIAL);")
            rollback_file.write_text("DROP TABLE test;")

            migration = Migration(migration_file, rollback_file)

            assert migration.version == "001"
            assert migration.name == "test_migration"
            assert migration.migration_file == migration_file
            assert migration.rollback_file == rollback_file

    def test_migration_version_parsing(self):
        """Test migration version parsing from filename."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            test_cases = [
                ("001_initial_schema.sql", "001"),
                ("042_add_indexes.sql", "042"),
                ("123_complex_migration.sql", "123"),
            ]

            for filename, expected_version in test_cases:
                migration_file = temp_path / filename
                migration_file.write_text("SELECT 1;")

                migration = Migration(migration_file)
                assert migration.version == expected_version

    def test_migration_invalid_filename(self):
        """Test migration with invalid filename format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Invalid filename (no number prefix)
            migration_file = temp_path / "invalid_migration.sql"
            migration_file.write_text("SELECT 1;")

            migration = Migration(migration_file)
            with pytest.raises(MigrationError, match="Invalid migration filename"):
                # Access the version property to trigger validation
                _ = migration.version

    def test_migration_checksum(self):
        """Test migration checksum calculation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            migration_file = temp_path / "001_test.sql"
            migration_file.write_text("CREATE TABLE test (id SERIAL);")

            migration = Migration(migration_file)
            checksum1 = migration.checksum

            # Same content should produce same checksum
            checksum2 = migration.checksum
            assert checksum1 == checksum2

            # Different content should produce different checksum
            migration_file.write_text("CREATE TABLE test2 (id SERIAL);")
            migration2 = Migration(migration_file)
            assert migration2.checksum != checksum1

    def test_migration_get_description(self):
        """Test extracting description from SQL comments."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            migration_file = temp_path / "001_test.sql"
            migration_file.write_text("""
-- Migration: Test migration
-- Author: test
-- Description: This is a test migration
CREATE TABLE test (id SERIAL);
            """)

            migration = Migration(migration_file)
            description = migration.get_description()
            assert description == "This is a test migration"

    def test_migration_get_description_fallback(self):
        """Test description fallback to filename."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            migration_file = temp_path / "001_create_user_table.sql"
            migration_file.write_text("CREATE TABLE users (id SERIAL);")

            migration = Migration(migration_file)
            description = migration.get_description()
            assert description == "Create User Table"


class TestMigrationRunner:
    """Test MigrationRunner functionality."""

    @pytest.fixture
    def temp_migrations_dir(self):
        """Create temporary migrations directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            migrations_path = Path(temp_dir) / "migrations"
            migrations_path.mkdir()
            yield migrations_path

    @pytest.fixture
    def sample_migrations(self, temp_migrations_dir):
        """Create sample migration files."""
        # Migration 001
        (temp_migrations_dir / "001_initial_schema.sql").write_text("""
-- Description: Create initial schema
CREATE SCHEMA test;
CREATE TABLE test.users (id SERIAL PRIMARY KEY, name VARCHAR(255));
        """)

        (temp_migrations_dir / "001_initial_schema.rollback.sql").write_text("""
DROP SCHEMA test CASCADE;
        """)

        # Migration 002
        (temp_migrations_dir / "002_add_indexes.sql").write_text("""
-- Description: Add performance indexes
CREATE INDEX idx_users_name ON test.users(name);
        """)

        (temp_migrations_dir / "002_add_indexes.rollback.sql").write_text("""
DROP INDEX test.idx_users_name;
        """)

        return temp_migrations_dir

    def test_discover_migrations(self, sample_migrations):
        """Test migration discovery."""
        # Mock the database connection to avoid actual connections
        with patch('poststack.schema_migration.psycopg2.connect'):
            runner = MigrationRunner("postgresql://test", str(sample_migrations))
            migrations = runner.discover_migrations()

            assert len(migrations) == 2
            assert migrations[0].version == "001"
            assert migrations[1].version == "002"
            assert migrations[0].name == "initial_schema"
            assert migrations[1].name == "add_indexes"

    @patch('poststack.schema_migration.psycopg2.connect')
    def test_ensure_migration_tables(self, mock_connect, sample_migrations):
        """Test migration tracking tables creation."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        MigrationRunner("postgresql://test", str(sample_migrations))

        # Verify migration tables are created
        assert mock_cursor.execute.call_count >= 3

        # Check that the correct SQL was executed
        calls = mock_cursor.execute.call_args_list
        create_calls = [call[0][0] for call in calls if "CREATE TABLE" in call[0][0]]

        assert any("schema_migrations" in sql for sql in create_calls)
        assert any("schema_migration_lock" in sql for sql in create_calls)

    @patch('poststack.schema_migration.psycopg2.connect')
    def test_get_applied_migrations(self, mock_connect, sample_migrations):
        """Test retrieving applied migrations."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        # Mock applied migrations data
        mock_cursor.fetchall.return_value = [
            ("001", "Initial schema", datetime.now(), 100, "abc123", "test_user"),
            ("002", "Add indexes", datetime.now(), 50, "def456", "test_user"),
        ]

        runner = MigrationRunner("postgresql://test", str(sample_migrations))
        applied = runner.get_applied_migrations()

        assert len(applied) == 2
        assert applied[0].version == "001"
        assert applied[1].version == "002"
        assert applied[0].description == "Initial schema"
        assert applied[1].description == "Add indexes"

    @patch('poststack.schema_migration.psycopg2.connect')
    def test_get_pending_migrations(self, mock_connect, sample_migrations):
        """Test retrieving pending migrations."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        # Mock only migration 001 as applied
        mock_cursor.fetchall.return_value = [
            ("001", "Initial schema", datetime.now(), 100, "abc123", "test_user"),
        ]

        runner = MigrationRunner("postgresql://test", str(sample_migrations))
        pending = runner.get_pending_migrations()

        assert len(pending) == 1
        assert pending[0].version == "002"
        assert pending[0].name == "add_indexes"

    @patch('poststack.schema_migration.psycopg2.connect')
    @patch('poststack.schema_migration.os.environ.get')
    def test_migrate_success(self, mock_env_get, mock_connect, sample_migrations):
        """Test successful migration execution."""
        mock_env_get.return_value = "test_user"

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        # Mock no applied migrations initially
        mock_cursor.fetchall.return_value = []

        # Mock successful lock acquisition
        mock_cursor.rowcount = 1

        runner = MigrationRunner("postgresql://test", str(sample_migrations))
        result = runner.migrate()

        assert result.success
        assert "2 migration(s)" in result.message
        assert result.version == "002"  # Last applied migration

    @patch('poststack.schema_migration.psycopg2.connect')
    def test_acquire_lock_timeout(self, mock_connect, sample_migrations):
        """Test migration lock timeout."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        # Mock lock never acquired (rowcount always 0)
        mock_cursor.rowcount = 0

        runner = MigrationRunner("postgresql://test", str(sample_migrations))

        # Use very short timeout for test
        with patch('time.time', side_effect=[0, 1, 2, 3, 310]):  # Simulate 310 seconds passing
            acquired = runner._acquire_lock(mock_conn, timeout=300)

        assert not acquired

    @patch('poststack.schema_migration.psycopg2.connect')
    def test_verify_migrations_success(self, mock_connect, sample_migrations):
        """Test successful migration verification."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        # Mock applied migrations with matching checksums
        applied_migrations = [
            ("001", "Initial schema", datetime.now(), 100, "checksum1", "test_user"),
            ("002", "Add indexes", datetime.now(), 50, "checksum2", "test_user"),
        ]
        mock_cursor.fetchall.return_value = applied_migrations

        runner = MigrationRunner("postgresql://test", str(sample_migrations))

        # Mock checksums to match
        with patch.object(runner, 'discover_migrations') as mock_discover:
            mock_migrations = []
            for version, _, _, _, checksum, _ in applied_migrations:
                mock_migration = Mock()
                mock_migration.version = version
                mock_migration.checksum = checksum
                mock_migrations.append(mock_migration)
            mock_discover.return_value = mock_migrations

            verification = runner.verify()

            assert verification.valid
            assert len(verification.errors) == 0

    @patch('poststack.schema_migration.psycopg2.connect')
    def test_verify_migrations_checksum_mismatch(self, mock_connect, sample_migrations):
        """Test migration verification with checksum mismatch."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=None)
        mock_connect.return_value = mock_conn

        # Mock applied migration with different checksum
        mock_cursor.fetchall.return_value = [
            ("001", "Initial schema", datetime.now(), 100, "old_checksum", "test_user"),
        ]

        runner = MigrationRunner("postgresql://test", str(sample_migrations))

        # Mock migration with different checksum
        with patch.object(runner, 'discover_migrations') as mock_discover:
            mock_migration = Mock()
            mock_migration.version = "001"
            mock_migration.checksum = "new_checksum"
            mock_discover.return_value = [mock_migration]

            verification = runner.verify()

            assert not verification.valid
            assert len(verification.errors) == 1
            assert "Checksum mismatch" in verification.errors[0]


class TestMigrationIntegration:
    """Integration tests for migration functionality."""

    @pytest.fixture
    def temp_migrations_dir(self):
        """Create temporary migrations directory with real SQL."""
        with tempfile.TemporaryDirectory() as temp_dir:
            migrations_path = Path(temp_dir) / "migrations"
            migrations_path.mkdir()

            # Create realistic migrations
            (migrations_path / "001_create_users.sql").write_text("""
-- Description: Create users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
            """)

            (migrations_path / "001_create_users.rollback.sql").write_text("""
DROP TABLE users;
            """)

            yield migrations_path

    def test_migration_file_parsing(self, temp_migrations_dir):
        """Test parsing real migration files."""
        with patch('poststack.schema_migration.psycopg2.connect'):
            runner = MigrationRunner("postgresql://test", str(temp_migrations_dir))
            migrations = runner.discover_migrations()

            assert len(migrations) == 1
            migration = migrations[0]

            assert migration.version == "001"
            assert migration.name == "create_users"
            assert "CREATE TABLE users" in migration.get_sql()
            assert "DROP TABLE users" in migration.get_rollback_sql()
            assert migration.get_description() == "Create users table"

    def test_migration_checksum_consistency(self, temp_migrations_dir):
        """Test that checksums are consistent for same content."""
        with patch('poststack.schema_migration.psycopg2.connect'):
            runner = MigrationRunner("postgresql://test", str(temp_migrations_dir))
            migrations = runner.discover_migrations()

            migration = migrations[0]
            checksum1 = migration.checksum
            checksum2 = migration.checksum

            assert checksum1 == checksum2
            assert len(checksum1) == 64  # SHA-256 hex length
