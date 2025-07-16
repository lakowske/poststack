"""
Database fixture management for integration tests.

Provides utilities for creating, managing, and cleaning up PostgreSQL test databases
with specialized fixtures for different migration testing scenarios.
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional, Tuple

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from poststack.schema_migration import MigrationRunner, AppliedMigration

logger = logging.getLogger(__name__)


@dataclass
class DatabaseState:
    """Represents the current state of a test database."""
    connection_url: str
    applied_migrations: List[AppliedMigration]
    schema_exists: bool
    migration_tables_exist: bool
    table_count: int
    inconsistencies: List[str]


class DatabaseManager:
    """Manages test database lifecycle and state."""
    
    def __init__(self, db_config: Dict[str, str]):
        self.db_config = db_config
        self.connection_url = db_config['connection_url']
        
    @contextmanager
    def get_connection(self, autocommit: bool = False) -> Generator[psycopg2.extensions.connection, None, None]:
        """Get database connection with automatic cleanup."""
        conn = psycopg2.connect(self.connection_url)
        if autocommit:
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        try:
            yield conn
        finally:
            conn.close()
    
    def get_database_state(self) -> DatabaseState:
        """Get current database state for validation."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Check if migration tables exist
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'schema_migrations'
                    )
                """)
                migration_tables_exist = cursor.fetchone()[0]
                
                # Get applied migrations
                applied_migrations = []
                if migration_tables_exist:
                    cursor.execute("""
                        SELECT version, description, applied_at, 
                               execution_time_ms, checksum, applied_by
                        FROM schema_migrations
                        ORDER BY version
                    """)
                    for row in cursor.fetchall():
                        applied_migrations.append(AppliedMigration(
                            version=row[0],
                            description=row[1],
                            applied_at=row[2],
                            execution_time_ms=row[3],
                            checksum=row[4],
                            applied_by=row[5]
                        ))
                
                # Check if poststack schema exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.schemata 
                        WHERE schema_name = 'poststack'
                    )
                """)
                schema_exists = cursor.fetchone()[0]
                
                # Count tables
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                """)
                table_count = cursor.fetchone()[0]
                
                # Check for inconsistencies (basic check)
                inconsistencies = []
                if applied_migrations and not schema_exists:
                    inconsistencies.append("Applied migrations exist but poststack schema missing")
                if not applied_migrations and schema_exists:
                    inconsistencies.append("Poststack schema exists but no applied migrations")
                
                return DatabaseState(
                    connection_url=self.connection_url,
                    applied_migrations=applied_migrations,
                    schema_exists=schema_exists,
                    migration_tables_exist=migration_tables_exist,
                    table_count=table_count,
                    inconsistencies=inconsistencies
                )
    
    def create_inconsistent_state(self, scenario: str) -> None:
        """Create specific inconsistent database states for testing."""
        logger.info(f"Creating inconsistent state: {scenario}")
        
        if scenario == "missing_tracking":
            # Apply migrations manually without tracking
            self.execute_sql("""
                CREATE SCHEMA IF NOT EXISTS test_schema;
                CREATE TABLE test_schema.test_table (id SERIAL PRIMARY KEY);
            """)
            
        elif scenario == "orphaned_tracking":
            # Create migration tracking without actual schema
            self.ensure_migration_tables()
            self.execute_sql("""
                INSERT INTO schema_migrations (version, description, checksum, applied_by)
                VALUES ('001', 'Orphaned migration', 'fake_checksum', 'test')
            """)
            
        elif scenario == "checksum_mismatch":
            # Create migration with wrong checksum
            self.ensure_migration_tables()
            self.execute_sql("""
                CREATE SCHEMA IF NOT EXISTS test_schema;
                CREATE TABLE test_schema.test_table (id SERIAL PRIMARY KEY);
            """)
            self.execute_sql("""
                INSERT INTO schema_migrations (version, description, checksum, applied_by)
                VALUES ('001', 'Checksum mismatch', 'wrong_checksum', 'test')
            """)
            
        elif scenario == "partial_migration":
            # Simulate partial migration failure
            self.ensure_migration_tables()
            self.execute_sql("""
                CREATE SCHEMA IF NOT EXISTS test_schema;
                -- Missing table that should be created
            """)
            self.execute_sql("""
                INSERT INTO schema_migrations (version, description, checksum, applied_by)
                VALUES ('001', 'Partial migration', 'partial_checksum', 'test')
            """)
            
        else:
            raise ValueError(f"Unknown inconsistent state scenario: {scenario}")
    
    def ensure_migration_tables(self) -> None:
        """Ensure migration tracking tables exist."""
        self.execute_sql("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                description TEXT,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                execution_time_ms INTEGER,
                checksum VARCHAR(64) NOT NULL,
                applied_by VARCHAR(255),
                sql_up TEXT,
                sql_down TEXT
            );
            
            CREATE TABLE IF NOT EXISTS schema_migration_lock (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                locked BOOLEAN NOT NULL DEFAULT FALSE,
                locked_at TIMESTAMP,
                locked_by VARCHAR(255)
            );
            
            INSERT INTO schema_migration_lock (id, locked)
            VALUES (1, FALSE)
            ON CONFLICT (id) DO NOTHING;
        """)
    
    def execute_sql(self, sql: str) -> None:
        """Execute SQL statement."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                conn.commit()
    
    def clear_database(self) -> None:
        """Clear all database objects."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Drop all schemas except system ones
                cursor.execute("""
                    SELECT schema_name 
                    FROM information_schema.schemata 
                    WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'public')
                """)
                schemas = cursor.fetchall()
                
                for (schema_name,) in schemas:
                    cursor.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
                
                # Drop migration tracking tables
                cursor.execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
                cursor.execute("DROP TABLE IF EXISTS schema_migration_lock CASCADE")
                
                conn.commit()
    
    def wait_for_connectivity(self, timeout: int = 30) -> bool:
        """Wait for database to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        return True
            except psycopg2.OperationalError:
                time.sleep(1)
        return False


class MigrationTestScenarios:
    """Provides predefined migration scenarios for testing."""
    
    @staticmethod
    def create_unified_project_scenario(db_manager: DatabaseManager, migrations_dir) -> None:
        """Recreate the exact scenario found in the unified project."""
        # First apply all migrations manually
        migrations = [
            ("001", "Create User Table", """
                CREATE SCHEMA IF NOT EXISTS unified;
                CREATE TABLE unified.users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """),
            ("002", "Add User Creation Notify", """
                CREATE OR REPLACE FUNCTION unified.notify_user_created()
                RETURNS TRIGGER AS $$
                BEGIN
                    PERFORM pg_notify('user_created', NEW.id::text);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                
                CREATE TRIGGER user_created_trigger
                    AFTER INSERT ON unified.users
                    FOR EACH ROW
                    EXECUTE FUNCTION unified.notify_user_created();
            """),
            ("003", "Add Certificate Management", """
                CREATE TABLE unified.certificates (
                    id SERIAL PRIMARY KEY,
                    domain VARCHAR(255) NOT NULL,
                    certificate_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """),
            ("004", "Add DNS Records", """
                CREATE TABLE unified.dns_records (
                    id SERIAL PRIMARY KEY,
                    domain VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(10) NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        ]
        
        # Apply all migrations manually
        db_manager.ensure_migration_tables()
        for version, description, sql in migrations:
            db_manager.execute_sql(sql)
        
        # Only track migration 001
        db_manager.execute_sql("""
            INSERT INTO schema_migrations (version, description, checksum, applied_by)
            VALUES ('001', 'Create User Table', 'fake_checksum_001', 'system')
        """)
        
        logger.info("Created unified project scenario with tracking inconsistency")
    
    @staticmethod
    def create_rollback_scenario(db_manager: DatabaseManager, migrations_dir) -> None:
        """Create scenario for testing rollback functionality."""
        # Apply migrations in sequence
        migrations = [
            ("001", "CREATE SCHEMA test_rollback; CREATE TABLE test_rollback.table1 (id SERIAL);"),
            ("002", "CREATE TABLE test_rollback.table2 (id SERIAL);"),
            ("003", "CREATE TABLE test_rollback.table3 (id SERIAL);"),
        ]
        
        db_manager.ensure_migration_tables()
        for i, (version, sql) in enumerate(migrations):
            db_manager.execute_sql(sql)
            db_manager.execute_sql(f"""
                INSERT INTO schema_migrations (version, description, checksum, applied_by)
                VALUES ('{version}', 'Migration {version}', 'checksum_{version}', 'system')
            """)
        
        logger.info("Created rollback scenario with 3 applied migrations")
    
    @staticmethod
    def create_performance_scenario(db_manager: DatabaseManager, table_count: int = 100) -> None:
        """Create scenario for performance testing."""
        db_manager.ensure_migration_tables()
        db_manager.execute_sql("CREATE SCHEMA IF NOT EXISTS performance_test")
        
        # Create many tables to simulate large migration
        for i in range(table_count):
            db_manager.execute_sql(f"""
                CREATE TABLE performance_test.table_{i:04d} (
                    id SERIAL PRIMARY KEY,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        
        logger.info(f"Created performance scenario with {table_count} tables")


class MigrationStateValidator:
    """Validates migration state consistency."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def validate_clean_state(self) -> List[str]:
        """Validate that database is in clean state."""
        errors = []
        state = self.db_manager.get_database_state()
        
        if state.applied_migrations:
            errors.append(f"Found {len(state.applied_migrations)} applied migrations in clean state")
        
        if state.schema_exists:
            errors.append("Found poststack schema in clean state")
        
        if state.table_count > 2:  # Migration tables are expected
            errors.append(f"Found {state.table_count} tables in clean state")
        
        return errors
    
    def validate_migrated_state(self, expected_migrations: List[str]) -> List[str]:
        """Validate that migrations were applied correctly."""
        errors = []
        state = self.db_manager.get_database_state()
        
        applied_versions = {m.version for m in state.applied_migrations}
        expected_versions = set(expected_migrations)
        
        missing = expected_versions - applied_versions
        extra = applied_versions - expected_versions
        
        if missing:
            errors.append(f"Missing migrations: {missing}")
        
        if extra:
            errors.append(f"Extra migrations: {extra}")
        
        if not state.migration_tables_exist:
            errors.append("Migration tracking tables missing")
        
        return errors
    
    def validate_inconsistent_state(self, expected_inconsistencies: List[str]) -> List[str]:
        """Validate that expected inconsistencies exist."""
        errors = []
        state = self.db_manager.get_database_state()
        
        found_inconsistencies = set(state.inconsistencies)
        expected_inconsistencies = set(expected_inconsistencies)
        
        missing = expected_inconsistencies - found_inconsistencies
        if missing:
            errors.append(f"Expected inconsistencies not found: {missing}")
        
        return errors


# Performance timing utilities
class PerformanceTimer:
    """Utility for timing database operations."""
    
    def __init__(self):
        self.start_time = None
        self.end_time = None
    
    def start(self):
        """Start timing."""
        self.start_time = time.time()
    
    def stop(self):
        """Stop timing."""
        self.end_time = time.time()
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        if self.start_time is None or self.end_time is None:
            return 0.0
        return self.end_time - self.start_time
    
    @property
    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        return int(self.elapsed * 1000)