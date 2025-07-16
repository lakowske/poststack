"""
Migration integrity tests for poststack.

Tests that validate the core migration functionality works correctly with
real PostgreSQL databases, including applying migrations, tracking state,
and maintaining data integrity.
"""

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import List

import pytest
import psycopg2

from poststack.schema_migration import MigrationRunner, MigrationError
from .database_fixtures import DatabaseManager, MigrationStateValidator, PerformanceTimer

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.database
class TestMigrationIntegrity:
    """Test core migration integrity functionality."""
    
    def test_fresh_migration_application(self, migration_runner, sample_migrations, db_helper):
        """Test applying migrations from scratch to a fresh database."""
        logger.info("Testing fresh migration application")
        
        # Verify initial state is clean
        initial_state = db_helper.get_applied_migrations()
        assert len(initial_state) == 0, "Database should start with no applied migrations"
        
        # Apply all migrations
        result = migration_runner.migrate()
        
        # Verify migration succeeded
        assert result.success, f"Migration should succeed: {result.message}"
        assert result.version == "003", f"Final version should be 003, got {result.version}"
        
        # Verify all migrations were applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 3, f"Should have 3 applied migrations, got {len(applied_migrations)}"
        
        # Verify migration tracking
        expected_versions = ["001", "002", "003"]
        actual_versions = [m[0] for m in applied_migrations]
        assert actual_versions == expected_versions, f"Expected versions {expected_versions}, got {actual_versions}"
        
        # Verify database objects were created
        assert db_helper.schema_exists("test_schema"), "Test schema should exist"
        assert db_helper.table_exists("users", "test_schema"), "Users table should exist"
        assert db_helper.table_exists("posts", "test_schema"), "Posts table should exist"
        
        logger.info("Fresh migration application test passed")
    
    def test_incremental_migration_application(self, migration_runner, sample_migrations, db_helper):
        """Test applying migrations incrementally."""
        logger.info("Testing incremental migration application")
        
        # Apply first migration only
        result = migration_runner.migrate(target_version="001")
        assert result.success, f"First migration should succeed: {result.message}"
        
        # Verify only first migration applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, f"Should have 1 applied migration, got {len(applied_migrations)}"
        assert applied_migrations[0][0] == "001", f"First migration should be 001, got {applied_migrations[0][0]}"
        
        # Apply second migration
        result = migration_runner.migrate(target_version="002")
        assert result.success, f"Second migration should succeed: {result.message}"
        
        # Verify two migrations applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 2, f"Should have 2 applied migrations, got {len(applied_migrations)}"
        
        # Apply remaining migrations
        result = migration_runner.migrate()
        assert result.success, f"Remaining migrations should succeed: {result.message}"
        
        # Verify all migrations applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 3, f"Should have 3 applied migrations, got {len(applied_migrations)}"
        
        logger.info("Incremental migration application test passed")
    
    def test_migration_idempotency(self, migration_runner, sample_migrations, db_helper):
        """Test that migrations are idempotent (safe to run multiple times)."""
        logger.info("Testing migration idempotency")
        
        # Apply migrations first time
        result1 = migration_runner.migrate()
        assert result1.success, f"First migration should succeed: {result1.message}"
        
        # Record initial state
        initial_migrations = db_helper.get_applied_migrations()
        initial_table_count = len(db_helper.fetch_all("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'test_schema'
        """))
        
        # Apply migrations again
        result2 = migration_runner.migrate()
        assert result2.success, f"Second migration should succeed: {result2.message}"
        assert "No pending migrations" in result2.message, "Should report no pending migrations"
        
        # Verify state hasn't changed
        final_migrations = db_helper.get_applied_migrations()
        final_table_count = len(db_helper.fetch_all("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'test_schema'
        """))
        
        assert len(final_migrations) == len(initial_migrations), "Migration count should be same"
        assert final_table_count == initial_table_count, "Table count should be same"
        
        logger.info("Migration idempotency test passed")
    
    def test_migration_checksum_validation(self, migration_runner, sample_migrations, db_helper):
        """Test that migration checksums are validated correctly."""
        logger.info("Testing migration checksum validation")
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Verify checksums are recorded
        applied_migrations = db_helper.get_applied_migrations()
        for version, description, applied_at in applied_migrations:
            checksum = db_helper.fetch_one("""
                SELECT checksum FROM schema_migrations WHERE version = %s
            """, (version,))
            assert checksum is not None, f"Checksum should be recorded for migration {version}"
            assert len(checksum[0]) == 64, f"Checksum should be 64 chars (SHA256), got {len(checksum[0])}"
        
        # Verify checksums match current file content
        verification_result = migration_runner.verify()
        assert verification_result.valid, f"Verification should pass: {verification_result.errors}"
        
        logger.info("Migration checksum validation test passed")
    
    def test_migration_performance(self, migration_runner, sample_migrations, db_helper):
        """Test migration performance is within acceptable limits."""
        logger.info("Testing migration performance")
        
        timer = PerformanceTimer()
        
        # Measure migration time
        timer.start()
        result = migration_runner.migrate()
        timer.stop()
        
        # Verify migration succeeded
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Verify performance
        max_time_ms = 30000  # 30 seconds max
        assert timer.elapsed_ms < max_time_ms, f"Migration took {timer.elapsed_ms}ms (> {max_time_ms}ms)"
        
        # Verify individual migration execution times
        applied_migrations = db_helper.fetch_all("""
            SELECT version, execution_time_ms 
            FROM schema_migrations 
            WHERE execution_time_ms IS NOT NULL
        """)
        
        for version, execution_time in applied_migrations:
            assert execution_time < 10000, f"Migration {version} took {execution_time}ms (> 10s)"
        
        logger.info(f"Migration performance test passed - total time: {timer.elapsed_ms}ms")
    
    def test_migration_transaction_handling(self, migration_runner, temp_migrations_dir, db_helper):
        """Test that migrations are properly transactional."""
        logger.info("Testing migration transaction handling")
        
        # Create migration that will fail
        (temp_migrations_dir / "001_good_migration.sql").write_text("""
            CREATE SCHEMA test_transaction;
            CREATE TABLE test_transaction.good_table (id SERIAL PRIMARY KEY);
        """)
        
        (temp_migrations_dir / "002_bad_migration.sql").write_text("""
            CREATE TABLE test_transaction.bad_table (
                id SERIAL PRIMARY KEY,
                invalid_column INVALID_TYPE  -- This will cause a syntax error
            );
        """)
        
        # Apply first migration (should succeed)
        result1 = migration_runner.migrate(target_version="001")
        assert result1.success, f"First migration should succeed: {result1.message}"
        
        # Verify first migration was applied
        assert db_helper.schema_exists("test_transaction"), "Schema should exist after first migration"
        assert db_helper.table_exists("good_table", "test_transaction"), "Good table should exist"
        
        # Apply second migration (should fail)
        result2 = migration_runner.migrate(target_version="002")
        assert not result2.success, "Second migration should fail"
        
        # Verify first migration is still applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, "Should still have 1 applied migration"
        assert applied_migrations[0][0] == "001", "First migration should still be applied"
        
        # Verify database state is consistent
        assert db_helper.schema_exists("test_transaction"), "Schema should still exist"
        assert db_helper.table_exists("good_table", "test_transaction"), "Good table should still exist"
        assert not db_helper.table_exists("bad_table", "test_transaction"), "Bad table should not exist"
        
        logger.info("Migration transaction handling test passed")
    
    def test_migration_lock_mechanism(self, test_database, temp_migrations_dir):
        """Test that migration locking prevents concurrent migrations."""
        logger.info("Testing migration lock mechanism")
        
        # Create sample migration
        (temp_migrations_dir / "001_lock_test.sql").write_text("""
            CREATE SCHEMA test_lock;
            CREATE TABLE test_lock.test_table (id SERIAL PRIMARY KEY);
        """)
        
        # Create two migration runners
        runner1 = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        runner2 = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Get connection and manually acquire lock
        conn = psycopg2.connect(test_database['connection_url'])
        
        # Ensure migration tables exist
        runner1._ensure_migration_tables()
        
        # Acquire lock manually
        assert runner1._acquire_lock(conn, timeout=1), "Should be able to acquire lock"
        
        try:
            # Try to run migration with second runner (should fail due to lock)
            result = runner2.migrate()
            assert not result.success, "Migration should fail when locked"
            assert "lock" in result.message.lower(), f"Error should mention lock: {result.message}"
            
        finally:
            # Release lock
            runner1._release_lock(conn)
            conn.close()
        
        # Now migration should work
        result = runner2.migrate()
        assert result.success, f"Migration should succeed after lock released: {result.message}"
        
        logger.info("Migration lock mechanism test passed")
    
    def test_migration_discovery(self, migration_runner, sample_migrations):
        """Test that migrations are discovered correctly."""
        logger.info("Testing migration discovery")
        
        # Discover migrations
        discovered_migrations = migration_runner.discover_migrations()
        
        # Verify correct number of migrations
        assert len(discovered_migrations) == 3, f"Should discover 3 migrations, got {len(discovered_migrations)}"
        
        # Verify migrations are in correct order
        versions = [m.version for m in discovered_migrations]
        assert versions == ["001", "002", "003"], f"Expected versions [001, 002, 003], got {versions}"
        
        # Verify migration names
        names = [m.name for m in discovered_migrations]
        expected_names = ["create_schema", "add_indexes", "add_constraints"]
        assert names == expected_names, f"Expected names {expected_names}, got {names}"
        
        # Verify rollback files are found
        for migration in discovered_migrations:
            assert migration.rollback_file is not None, f"Migration {migration.version} should have rollback file"
            assert migration.rollback_file.exists(), f"Rollback file should exist for {migration.version}"
        
        logger.info("Migration discovery test passed")
    
    def test_migration_status_reporting(self, migration_runner, sample_migrations, db_helper):
        """Test that migration status is reported correctly."""
        logger.info("Testing migration status reporting")
        
        # Check initial status
        initial_status = migration_runner.status()
        assert initial_status.current_version is None, "Initial version should be None"
        assert len(initial_status.applied_migrations) == 0, "Should have no applied migrations"
        assert len(initial_status.pending_migrations) == 3, "Should have 3 pending migrations"
        assert not initial_status.is_locked, "Should not be locked initially"
        
        # Apply first migration
        result = migration_runner.migrate(target_version="001")
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Check status after first migration
        status_after_first = migration_runner.status()
        assert status_after_first.current_version == "001", "Current version should be 001"
        assert len(status_after_first.applied_migrations) == 1, "Should have 1 applied migration"
        assert len(status_after_first.pending_migrations) == 2, "Should have 2 pending migrations"
        
        # Apply all remaining migrations
        result = migration_runner.migrate()
        assert result.success, f"Remaining migrations should succeed: {result.message}"
        
        # Check final status
        final_status = migration_runner.status()
        assert final_status.current_version == "003", "Final version should be 003"
        assert len(final_status.applied_migrations) == 3, "Should have 3 applied migrations"
        assert len(final_status.pending_migrations) == 0, "Should have no pending migrations"
        
        logger.info("Migration status reporting test passed")


@pytest.mark.integration
@pytest.mark.database
@pytest.mark.slow
class TestMigrationIntegrityAdvanced:
    """Advanced migration integrity tests."""
    
    def test_large_migration_set(self, test_database, temp_migrations_dir, db_helper):
        """Test with a large number of migrations."""
        logger.info("Testing large migration set")
        
        # Create many migrations
        num_migrations = 50
        for i in range(1, num_migrations + 1):
            version = f"{i:03d}"
            (temp_migrations_dir / f"{version}_migration.sql").write_text(f"""
                CREATE TABLE test_large.table_{version} (
                    id SERIAL PRIMARY KEY,
                    data TEXT DEFAULT 'migration_{version}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            (temp_migrations_dir / f"{version}_migration.rollback.sql").write_text(f"""
                DROP TABLE IF EXISTS test_large.table_{version};
            """)
        
        # Add initial schema creation
        (temp_migrations_dir / "001_migration.sql").write_text("""
            CREATE SCHEMA test_large;
        """ + (temp_migrations_dir / "001_migration.sql").read_text())
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply all migrations
        timer = PerformanceTimer()
        timer.start()
        result = migration_runner.migrate()
        timer.stop()
        
        # Verify success
        assert result.success, f"Large migration set should succeed: {result.message}"
        
        # Verify all migrations applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == num_migrations, f"Should have {num_migrations} applied migrations"
        
        # Verify performance is reasonable
        max_time_ms = 60000  # 60 seconds for 50 migrations
        assert timer.elapsed_ms < max_time_ms, f"Large migration took {timer.elapsed_ms}ms (> {max_time_ms}ms)"
        
        logger.info(f"Large migration set test passed - {num_migrations} migrations in {timer.elapsed_ms}ms")
    
    def test_complex_migration_dependencies(self, test_database, temp_migrations_dir, db_helper):
        """Test migrations with complex dependencies."""
        logger.info("Testing complex migration dependencies")
        
        # Create migrations with dependencies
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_deps;
            CREATE TABLE test_deps.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL
            );
        """)
        
        (temp_migrations_dir / "002_create_posts.sql").write_text("""
            CREATE TABLE test_deps.posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_deps.users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                content TEXT
            );
        """)
        
        (temp_migrations_dir / "003_create_comments.sql").write_text("""
            CREATE TABLE test_deps.comments (
                id SERIAL PRIMARY KEY,
                post_id INTEGER REFERENCES test_deps.posts(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES test_deps.users(id) ON DELETE CASCADE,
                content TEXT NOT NULL
            );
        """)
        
        (temp_migrations_dir / "004_add_indexes.sql").write_text("""
            CREATE INDEX idx_posts_user_id ON test_deps.posts(user_id);
            CREATE INDEX idx_comments_post_id ON test_deps.comments(post_id);
            CREATE INDEX idx_comments_user_id ON test_deps.comments(user_id);
        """)
        
        # Create rollback files
        (temp_migrations_dir / "004_add_indexes.rollback.sql").write_text("""
            DROP INDEX IF EXISTS test_deps.idx_posts_user_id;
            DROP INDEX IF EXISTS test_deps.idx_comments_post_id;
            DROP INDEX IF EXISTS test_deps.idx_comments_user_id;
        """)
        
        (temp_migrations_dir / "003_create_comments.rollback.sql").write_text("""
            DROP TABLE IF EXISTS test_deps.comments;
        """)
        
        (temp_migrations_dir / "002_create_posts.rollback.sql").write_text("""
            DROP TABLE IF EXISTS test_deps.posts;
        """)
        
        (temp_migrations_dir / "001_create_schema.rollback.sql").write_text("""
            DROP SCHEMA IF EXISTS test_deps CASCADE;
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Complex migration should succeed: {result.message}"
        
        # Verify all tables were created
        assert db_helper.table_exists("users", "test_deps"), "Users table should exist"
        assert db_helper.table_exists("posts", "test_deps"), "Posts table should exist"
        assert db_helper.table_exists("comments", "test_deps"), "Comments table should exist"
        
        # Verify foreign key constraints work
        db_helper.execute_sql("INSERT INTO test_deps.users (username) VALUES ('testuser')")
        db_helper.execute_sql("INSERT INTO test_deps.posts (user_id, title) VALUES (1, 'Test Post')")
        db_helper.execute_sql("INSERT INTO test_deps.comments (post_id, user_id, content) VALUES (1, 1, 'Test Comment')")
        
        # Verify indexes exist
        indexes = db_helper.fetch_all("""
            SELECT indexname FROM pg_indexes 
            WHERE schemaname = 'test_deps' AND indexname LIKE 'idx_%'
        """)
        assert len(indexes) == 3, f"Should have 3 indexes, got {len(indexes)}"
        
        logger.info("Complex migration dependencies test passed")
    
    def test_migration_with_data_transformation(self, test_database, temp_migrations_dir, db_helper):
        """Test migrations that transform existing data."""
        logger.info("Testing migration with data transformation")
        
        # Create initial schema and data
        (temp_migrations_dir / "001_create_users.sql").write_text("""
            CREATE SCHEMA test_transform;
            CREATE TABLE test_transform.users (
                id SERIAL PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            INSERT INTO test_transform.users (full_name, email) VALUES
                ('John Doe', 'john@example.com'),
                ('Jane Smith', 'jane@example.com'),
                ('Bob Johnson', 'bob@example.com');
        """)
        
        # Create migration that splits name into first/last
        (temp_migrations_dir / "002_split_names.sql").write_text("""
            -- Add new columns
            ALTER TABLE test_transform.users 
            ADD COLUMN first_name VARCHAR(100),
            ADD COLUMN last_name VARCHAR(100);
            
            -- Transform existing data
            UPDATE test_transform.users 
            SET first_name = SPLIT_PART(full_name, ' ', 1),
                last_name = SPLIT_PART(full_name, ' ', 2);
            
            -- Make new columns NOT NULL
            ALTER TABLE test_transform.users 
            ALTER COLUMN first_name SET NOT NULL,
            ALTER COLUMN last_name SET NOT NULL;
            
            -- Drop old column
            ALTER TABLE test_transform.users DROP COLUMN full_name;
        """)
        
        # Create rollback files
        (temp_migrations_dir / "002_split_names.rollback.sql").write_text("""
            -- Add back full_name column
            ALTER TABLE test_transform.users ADD COLUMN full_name VARCHAR(255);
            
            -- Transform data back
            UPDATE test_transform.users 
            SET full_name = first_name || ' ' || last_name;
            
            -- Make full_name NOT NULL
            ALTER TABLE test_transform.users ALTER COLUMN full_name SET NOT NULL;
            
            -- Drop split columns
            ALTER TABLE test_transform.users 
            DROP COLUMN first_name,
            DROP COLUMN last_name;
        """)
        
        (temp_migrations_dir / "001_create_users.rollback.sql").write_text("""
            DROP SCHEMA IF EXISTS test_transform CASCADE;
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Data transformation migration should succeed: {result.message}"
        
        # Verify data was transformed correctly
        users = db_helper.fetch_all("""
            SELECT first_name, last_name, email 
            FROM test_transform.users 
            ORDER BY email
        """)
        
        expected_users = [
            ('Bob', 'Johnson', 'bob@example.com'),
            ('Jane', 'Smith', 'jane@example.com'),
            ('John', 'Doe', 'john@example.com')
        ]
        
        assert users == expected_users, f"Expected {expected_users}, got {users}"
        
        logger.info("Migration with data transformation test passed")