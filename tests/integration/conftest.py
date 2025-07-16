"""
Integration test configuration and fixtures for Poststack migration tests.

Provides database containers, CLI testing utilities, and test data management
for comprehensive migration testing.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Generator, Optional
from unittest.mock import Mock

import pytest
import psycopg2
from click.testing import CliRunner

from poststack.config import PoststackConfig
from poststack.logging_config import setup_logging
from poststack.schema_migration import MigrationRunner


def detect_container_runtime():
    """
    Detect available container runtime (Docker or Podman) and configure testcontainers.
    
    Returns:
        str: 'docker' or 'podman' or None if neither is available
    """
    # Check for Docker first
    try:
        result = subprocess.run(['docker', '--version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return 'docker'
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Check for Podman
    try:
        result = subprocess.run(['podman', '--version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return 'podman'
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return None


def configure_testcontainers_for_podman():
    """Configure testcontainers to use Podman instead of Docker."""
    # Get the user's runtime directory
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    podman_socket = f'{runtime_dir}/podman/podman.sock'
    
    # Set environment variables for testcontainers to use Podman
    os.environ['DOCKER_HOST'] = f'unix://{podman_socket}'
    os.environ['TESTCONTAINERS_RYUK_DISABLED'] = 'true'
    
    # Ensure the socket directory exists
    socket_dir = os.path.dirname(podman_socket)
    os.makedirs(socket_dir, exist_ok=True)
    
    # Start Podman socket if not running
    if not os.path.exists(podman_socket):
        try:
            subprocess.Popen(['podman', 'system', 'service', '--timeout=30', f'unix://{podman_socket}'], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)  # Give it time to start
        except Exception:
            pass  # Service might already be running or not needed


@pytest.fixture(scope="session")
def postgresql_container():
    """
    Create a PostgreSQL container for integration testing.
    
    This fixture uses testcontainers to create an isolated PostgreSQL instance
    for testing. Automatically detects Docker or Podman and configures accordingly.
    Falls back to a mock if no container runtime is available.
    """
    # Detect container runtime
    runtime = detect_container_runtime()
    
    if runtime == 'podman':
        configure_testcontainers_for_podman()
    elif runtime is None:
        pytest.skip("No container runtime (Docker or Podman) available for integration tests")
    
    try:
        from testcontainers.postgres import PostgresContainer
        
        # Start PostgreSQL container
        postgres = PostgresContainer("postgres:15")
        postgres.start()
        
        # Wait for container to be ready
        connection_url = postgres.get_connection_url()
        
        # Fix connection URL format for psycopg2
        if connection_url.startswith('postgresql+psycopg2://'):
            connection_url = connection_url.replace('postgresql+psycopg2://', 'postgresql://')
        
        max_retries = 30
        for i in range(max_retries):
            try:
                conn = psycopg2.connect(connection_url)
                conn.close()
                break
            except psycopg2.OperationalError:
                if i == max_retries - 1:
                    raise
                time.sleep(1)
        
        yield {
            'container': postgres,
            'connection_url': connection_url,
            'host': postgres.get_container_host_ip(),
            'port': postgres.get_exposed_port(5432),
            'database': postgres.dbname,
            'user': postgres.username,
            'password': postgres.password
        }
        
        # Cleanup
        postgres.stop()
        
    except ImportError:
        # Fallback to mock if testcontainers not available
        pytest.skip("testcontainers not available - install with: pip install testcontainers")


@pytest.fixture(scope="session")
def integration_db_config(postgresql_container):
    """Create database configuration for integration tests."""
    return {
        'host': postgresql_container['host'],
        'port': postgresql_container['port'],
        'database': postgresql_container['database'],
        'user': postgresql_container['user'],
        'password': postgresql_container['password'],
        'connection_url': postgresql_container['connection_url']
    }


@pytest.fixture
def test_database(integration_db_config):
    """
    Create a fresh test database for each test.
    
    This fixture creates a new database for each test to ensure isolation.
    """
    # Create unique database name
    db_name = f"test_{int(time.time() * 1000)}_{os.getpid()}"
    
    # Connect to PostgreSQL and create test database
    conn = psycopg2.connect(
        host=integration_db_config['host'],
        port=integration_db_config['port'],
        database=integration_db_config['database'],
        user=integration_db_config['user'],
        password=integration_db_config['password']
    )
    conn.autocommit = True
    
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {db_name}")
    
    conn.close()
    
    # Create database URL for test
    test_db_url = (
        f"postgresql://{integration_db_config['user']}:{integration_db_config['password']}"
        f"@{integration_db_config['host']}:{integration_db_config['port']}/{db_name}"
    )
    
    test_config = {
        'host': integration_db_config['host'],
        'port': integration_db_config['port'],
        'database': db_name,
        'user': integration_db_config['user'],
        'password': integration_db_config['password'],
        'connection_url': test_db_url
    }
    
    yield test_config
    
    # Cleanup - drop test database
    conn = psycopg2.connect(
        host=integration_db_config['host'],
        port=integration_db_config['port'],
        database=integration_db_config['database'],
        user=integration_db_config['user'],
        password=integration_db_config['password']
    )
    conn.autocommit = True
    
    with conn.cursor() as cursor:
        # Terminate connections to test database
        cursor.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
              AND pid <> pg_backend_pid()
        """)
        
        # Drop test database
        cursor.execute(f"DROP DATABASE IF EXISTS {db_name}")
    
    conn.close()


@pytest.fixture
def migration_runner(test_database, temp_migrations_dir):
    """Create a migration runner for testing."""
    return MigrationRunner(
        database_url=test_database['connection_url'],
        migrations_path=str(temp_migrations_dir)
    )


@pytest.fixture
def temp_migrations_dir():
    """Create temporary directory for test migrations."""
    temp_dir = tempfile.mkdtemp(prefix="poststack_test_migrations_")
    migrations_path = Path(temp_dir) / "migrations"
    migrations_path.mkdir()
    
    yield migrations_path
    
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def cli_runner(test_database, temp_migrations_dir):
    """Create CLI test helper for testing commands."""
    from .cli_helpers import CLITestHelper
    return CLITestHelper(test_database['connection_url'], str(temp_migrations_dir))


@pytest.fixture
def test_config(test_database, temp_migrations_dir):
    """Create test configuration for poststack."""
    return PoststackConfig(
        database_url=test_database['connection_url'],
        migrations_path=str(temp_migrations_dir),
        log_level="DEBUG",
        verbose=True,
        debug=True,
        test_mode=True
    )


@pytest.fixture
def integration_logger():
    """Set up logging for integration tests."""
    return setup_logging(
        log_level="DEBUG",
        verbose=True,
        enable_file_logging=False
    )


@pytest.fixture
def sample_migrations(temp_migrations_dir):
    """Create sample migration files for testing."""
    # Migration 001: Create basic schema
    (temp_migrations_dir / "001_create_schema.sql").write_text("""
-- Description: Create basic test schema
CREATE SCHEMA IF NOT EXISTS test_schema;

CREATE TABLE test_schema.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE test_schema.posts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES test_schema.users(id),
    title VARCHAR(255) NOT NULL,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
    """)
    
    (temp_migrations_dir / "001_create_schema.rollback.sql").write_text("""
-- Rollback: Create basic test schema
DROP SCHEMA IF EXISTS test_schema CASCADE;
    """)
    
    # Migration 002: Add indexes
    (temp_migrations_dir / "002_add_indexes.sql").write_text("""
-- Description: Add performance indexes
CREATE INDEX idx_users_username ON test_schema.users(username);
CREATE INDEX idx_users_email ON test_schema.users(email);
CREATE INDEX idx_posts_user_id ON test_schema.posts(user_id);
CREATE INDEX idx_posts_created_at ON test_schema.posts(created_at);
    """)
    
    (temp_migrations_dir / "002_add_indexes.rollback.sql").write_text("""
-- Rollback: Add performance indexes
DROP INDEX IF EXISTS test_schema.idx_users_username;
DROP INDEX IF EXISTS test_schema.idx_users_email;
DROP INDEX IF EXISTS test_schema.idx_posts_user_id;
DROP INDEX IF EXISTS test_schema.idx_posts_created_at;
    """)
    
    # Migration 003: Add constraints
    (temp_migrations_dir / "003_add_constraints.sql").write_text("""
-- Description: Add data constraints
ALTER TABLE test_schema.users 
ADD CONSTRAINT chk_username_length CHECK (LENGTH(username) >= 3);

ALTER TABLE test_schema.users
ADD CONSTRAINT chk_email_format CHECK (email ~ '^[^@]+@[^@]+\\.[^@]+$');

ALTER TABLE test_schema.posts
ADD CONSTRAINT chk_title_not_empty CHECK (LENGTH(TRIM(title)) > 0);
    """)
    
    (temp_migrations_dir / "003_add_constraints.rollback.sql").write_text("""
-- Rollback: Add data constraints
ALTER TABLE test_schema.users DROP CONSTRAINT IF EXISTS chk_username_length;
ALTER TABLE test_schema.users DROP CONSTRAINT IF EXISTS chk_email_format;
ALTER TABLE test_schema.posts DROP CONSTRAINT IF EXISTS chk_title_not_empty;
    """)
    
    return temp_migrations_dir


@pytest.fixture
def edge_case_migrations(temp_migrations_dir):
    """Create edge case migration files for testing problematic scenarios."""
    # Migration that will be "applied" but not tracked
    (temp_migrations_dir / "004_orphan_migration.sql").write_text("""
-- Description: This migration will be applied but not tracked
CREATE TABLE test_schema.orphan_table (
    id SERIAL PRIMARY KEY,
    data TEXT
);
    """)
    
    (temp_migrations_dir / "004_orphan_migration.rollback.sql").write_text("""
-- Rollback: Remove orphan table
DROP TABLE IF EXISTS test_schema.orphan_table;
    """)
    
    # Migration that will be tracked but not applied
    (temp_migrations_dir / "005_phantom_migration.sql").write_text("""
-- Description: This migration will be tracked but not applied
CREATE TABLE test_schema.phantom_table (
    id SERIAL PRIMARY KEY,
    phantom_data TEXT
);
    """)
    
    (temp_migrations_dir / "005_phantom_migration.rollback.sql").write_text("""
-- Rollback: Remove phantom table
DROP TABLE IF EXISTS test_schema.phantom_table;
    """)
    
    # Migration with syntax error
    (temp_migrations_dir / "006_broken_migration.sql").write_text("""
-- Description: This migration has a syntax error
CREATE TABLE test_schema.broken_table (
    id SERIAL PRIMARY KEY,
    invalid_column INVALID_TYPE
);
    """)
    
    (temp_migrations_dir / "006_broken_migration.rollback.sql").write_text("""
-- Rollback: Remove broken table
DROP TABLE IF EXISTS test_schema.broken_table;
    """)
    
    return temp_migrations_dir


@pytest.fixture
def database_connection(test_database):
    """Create a direct database connection for testing."""
    conn = psycopg2.connect(test_database['connection_url'])
    
    yield conn
    
    conn.close()


@pytest.fixture
def database_cursor(database_connection):
    """Create a database cursor for testing."""
    cursor = database_connection.cursor()
    
    yield cursor
    
    cursor.close()


class DatabaseTestHelper:
    """Helper class for database testing operations."""
    
    def __init__(self, connection_url: str):
        self.connection_url = connection_url
    
    def execute_sql(self, sql: str, params: tuple = None) -> None:
        """Execute SQL statement."""
        with psycopg2.connect(self.connection_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                conn.commit()
    
    def fetch_one(self, sql: str, params: tuple = None) -> Optional[tuple]:
        """Fetch one row from SQL query."""
        with psycopg2.connect(self.connection_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
    
    def fetch_all(self, sql: str, params: tuple = None) -> list:
        """Fetch all rows from SQL query."""
        with psycopg2.connect(self.connection_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
    
    def table_exists(self, table_name: str, schema: str = "public") -> bool:
        """Check if table exists."""
        result = self.fetch_one("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            )
        """, (schema, table_name))
        return result[0] if result else False
    
    def schema_exists(self, schema_name: str) -> bool:
        """Check if schema exists."""
        result = self.fetch_one("""
            SELECT EXISTS (
                SELECT FROM information_schema.schemata 
                WHERE schema_name = %s
            )
        """, (schema_name,))
        return result[0] if result else False
    
    def get_applied_migrations(self) -> list:
        """Get applied migrations from tracking table."""
        try:
            return self.fetch_all("""
                SELECT version, description, applied_at 
                FROM schema_migrations 
                ORDER BY version
            """)
        except psycopg2.Error:
            return []
    
    def manually_apply_migration(self, migration_sql: str) -> None:
        """Apply migration SQL without tracking."""
        self.execute_sql(migration_sql)
    
    def manually_track_migration(self, version: str, description: str, checksum: str) -> None:
        """Add migration to tracking table without applying."""
        self.execute_sql("""
            INSERT INTO schema_migrations (version, description, checksum, applied_by)
            VALUES (%s, %s, %s, 'test_system')
        """, (version, description, checksum))


@pytest.fixture
def db_helper(test_database):
    """Create database helper for testing."""
    return DatabaseTestHelper(test_database['connection_url'])


# Test markers
def pytest_configure(config):
    """Configure pytest markers for integration tests."""
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "slow: marks tests as slow running")
    config.addinivalue_line("markers", "database: marks tests requiring database")
    config.addinivalue_line("markers", "cli: marks tests using CLI commands")
    config.addinivalue_line("markers", "edge_case: marks tests for edge cases")
    config.addinivalue_line("markers", "recovery: marks tests for recovery scenarios")


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests based on location and name."""
    for item in items:
        # Auto-mark integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        
        # Auto-mark database tests
        if "database" in item.nodeid or "db" in item.nodeid:
            item.add_marker(pytest.mark.database)
        
        # Auto-mark CLI tests
        if "cli" in item.nodeid or "command" in item.nodeid:
            item.add_marker(pytest.mark.cli)
        
        # Auto-mark slow tests
        if "slow" in item.nodeid or "performance" in item.nodeid:
            item.add_marker(pytest.mark.slow)
        
        # Auto-mark edge case tests
        if "edge_case" in item.nodeid or "edge" in item.nodeid:
            item.add_marker(pytest.mark.edge_case)
        
        # Auto-mark recovery tests
        if "recovery" in item.nodeid or "repair" in item.nodeid:
            item.add_marker(pytest.mark.recovery)


# Test data directory
@pytest.fixture(scope="session")
def test_data_dir():
    """Get test data directory."""
    return Path(__file__).parent / "test_data"