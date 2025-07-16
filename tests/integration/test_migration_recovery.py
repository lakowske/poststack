"""
Migration recovery tests for poststack.

Tests that validate recovery functionality for various migration failure scenarios,
including inconsistent states, missing files, corrupted data, and other edge cases
that can occur in real-world deployments.
"""

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any

import pytest
import psycopg2
from psycopg2 import sql

from poststack.schema_migration import MigrationRunner, MigrationError
from .database_fixtures import DatabaseManager, MigrationStateValidator, PerformanceTimer

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.database
class TestMigrationRecovery:
    """Test core migration recovery functionality."""
    
    def test_recover_from_missing_tracking(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery from migrations applied but not tracked (unified project scenario)."""
        logger.info("Testing recovery from missing tracking")
        
        # Create sample migrations
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_recovery;
            CREATE TABLE test_recovery.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL
            );
        """)
        
        (temp_migrations_dir / "002_add_posts.sql").write_text("""
            CREATE TABLE test_recovery.posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_recovery.users(id),
                title VARCHAR(255) NOT NULL
            );
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Ensure migration tables exist
        migration_runner._ensure_migration_tables()
        
        # Apply migrations manually without tracking (simulating unified project scenario)
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Execute migration 001 manually
        cursor.execute("""
            CREATE SCHEMA test_recovery;
            CREATE TABLE test_recovery.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL
            );
        """)
        
        # Execute migration 002 manually
        cursor.execute("""
            CREATE TABLE test_recovery.posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_recovery.users(id),
                title VARCHAR(255) NOT NULL
            );
        """)
        
        conn.commit()
        conn.close()
        
        # Verify schema exists but no migrations tracked
        assert db_helper.schema_exists("test_recovery"), "Schema should exist"
        assert db_helper.table_exists("users", "test_recovery"), "Users table should exist"
        assert db_helper.table_exists("posts", "test_recovery"), "Posts table should exist"
        
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 0, "Should have no tracked migrations"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify migrations are now tracked
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 2, f"Should have 2 tracked migrations after recovery"
        
        # Verify migration versions are correct
        versions = [m[0] for m in applied_migrations]
        assert versions == ["001", "002"], f"Expected versions [001, 002], got {versions}"
        
        # Verify checksums are calculated
        for version, _, _ in applied_migrations:
            checksum = db_helper.fetch_one("""
                SELECT checksum FROM schema_migrations WHERE version = %s
            """, (version,))
            assert checksum is not None, f"Checksum should exist for migration {version}"
            assert len(checksum[0]) == 64, f"Checksum should be 64 chars (SHA256)"
        
        logger.info("Recovery from missing tracking test passed")
    
    def test_recover_from_partial_migration(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery from partially applied migration."""
        logger.info("Testing recovery from partial migration")
        
        # Create migration
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_partial;
            CREATE TABLE test_partial.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL
            );
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Ensure migration tables exist
        migration_runner._ensure_migration_tables()
        
        # Manually create partial state - schema exists but table missing
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Create schema but not table
        cursor.execute("CREATE SCHEMA test_partial")
        
        # Mark migration as applied but with failure
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at, checksum, success)
            VALUES ('001', 'create_schema', CURRENT_TIMESTAMP, 'dummy_checksum', FALSE)
        """)
        
        conn.commit()
        conn.close()
        
        # Verify partial state
        assert db_helper.schema_exists("test_partial"), "Schema should exist"
        assert not db_helper.table_exists("users", "test_partial"), "Users table should not exist"
        
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 0, "Should have no successful migrations"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify migration was completed
        assert db_helper.table_exists("users", "test_partial"), "Users table should exist after recovery"
        
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, "Should have 1 successful migration after recovery"
        
        logger.info("Recovery from partial migration test passed")
    
    def test_recover_from_checksum_mismatch(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery from migration checksum mismatches."""
        logger.info("Testing recovery from checksum mismatch")
        
        # Create initial migration
        migration_file = temp_migrations_dir / "001_create_schema.sql"
        migration_file.write_text("""
            CREATE SCHEMA test_checksum;
            CREATE TABLE test_checksum.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL
            );
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migration normally
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Modify migration file (simulating file change)
        migration_file.write_text("""
            CREATE SCHEMA test_checksum;
            CREATE TABLE test_checksum.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                email VARCHAR(255) -- Added field
            );
        """)
        
        # Verify checksum mismatch is detected
        verification_result = migration_runner.verify()
        assert not verification_result.valid, "Verification should fail due to checksum mismatch"
        assert "checksum mismatch" in verification_result.errors[0].lower(), "Error should mention checksum mismatch"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify checksum was updated
        verification_result = migration_runner.verify()
        assert verification_result.valid, "Verification should pass after recovery"
        
        logger.info("Recovery from checksum mismatch test passed")
    
    def test_recover_from_missing_migration_files(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery when migration files are missing."""
        logger.info("Testing recovery from missing migration files")
        
        # Create migrations
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_missing;
            CREATE TABLE test_missing.users (id SERIAL PRIMARY KEY);
        """)
        
        (temp_migrations_dir / "002_add_posts.sql").write_text("""
            CREATE TABLE test_missing.posts (id SERIAL PRIMARY KEY);
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Remove migration file
        (temp_migrations_dir / "001_create_schema.sql").unlink()
        
        # Verify migration discovery fails
        discovered_migrations = migration_runner.discover_migrations()
        assert len(discovered_migrations) == 1, "Should only discover 1 migration"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify recovery handled missing file
        assert "missing migration file" in recovery_result.message.lower(), "Recovery should mention missing file"
        
        logger.info("Recovery from missing migration files test passed")
    
    def test_recover_from_corrupted_migration_table(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery from corrupted migration table."""
        logger.info("Testing recovery from corrupted migration table")
        
        # Create migration
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_corrupt;
            CREATE TABLE test_corrupt.users (id SERIAL PRIMARY KEY);
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migration
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Corrupt migration table
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Insert invalid data
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at, checksum, success)
            VALUES ('invalid', 'corrupted', CURRENT_TIMESTAMP, 'bad_checksum', TRUE)
        """)
        
        # Duplicate version
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at, checksum, success)
            VALUES ('001', 'duplicate', CURRENT_TIMESTAMP, 'another_checksum', TRUE)
        """)
        
        conn.commit()
        conn.close()
        
        # Verify corruption
        status = migration_runner.status()
        assert len(status.applied_migrations) > 1, "Should have corrupted data"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify corruption was cleaned up
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, "Should have 1 valid migration after recovery"
        assert applied_migrations[0][0] == "001", "Should have correct version"
        
        logger.info("Recovery from corrupted migration table test passed")
    
    def test_recover_from_stuck_lock(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery from stuck migration lock."""
        logger.info("Testing recovery from stuck lock")
        
        # Create migration
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_lock;
            CREATE TABLE test_lock.users (id SERIAL PRIMARY KEY);
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Ensure migration tables exist
        migration_runner._ensure_migration_tables()
        
        # Manually create stuck lock
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Insert lock record (simulating stuck process)
        cursor.execute("""
            INSERT INTO schema_migrations_lock (locked_at, process_id, hostname)
            VALUES (CURRENT_TIMESTAMP - INTERVAL '2 hours', 99999, 'stuck_host')
        """)
        
        conn.commit()
        conn.close()
        
        # Verify migration is blocked
        status = migration_runner.status()
        assert status.is_locked, "Should be locked"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify lock was cleared
        status = migration_runner.status()
        assert not status.is_locked, "Should not be locked after recovery"
        
        # Verify migration can now proceed
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed after recovery: {result.message}"
        
        logger.info("Recovery from stuck lock test passed")
    
    def test_recover_with_force_option(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery with force option for dangerous operations."""
        logger.info("Testing recovery with force option")
        
        # Create migration
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_force;
            CREATE TABLE test_force.users (id SERIAL PRIMARY KEY);
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migration
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Create dangerous inconsistent state
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Remove tracking but keep schema
        cursor.execute("DELETE FROM schema_migrations")
        conn.commit()
        conn.close()
        
        # Verify dangerous state
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 0, "Should have no tracked migrations"
        assert db_helper.schema_exists("test_force"), "Schema should still exist"
        
        # Recovery without force should be cautious
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # With force, should be more aggressive
        recovery_result = migration_runner.recover(force=True)
        assert recovery_result.success, f"Forced recovery should succeed: {recovery_result.message}"
        
        logger.info("Recovery with force option test passed")
    
    def test_recovery_diagnostics(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery diagnostic functionality."""
        logger.info("Testing recovery diagnostics")
        
        # Create migrations
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_diag;
            CREATE TABLE test_diag.users (id SERIAL PRIMARY KEY);
        """)
        
        (temp_migrations_dir / "002_add_posts.sql").write_text("""
            CREATE TABLE test_diag.posts (id SERIAL PRIMARY KEY);
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply first migration
        result = migration_runner.migrate(target_version="001")
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Create various inconsistent states
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Apply second migration manually without tracking
        cursor.execute("CREATE TABLE test_diag.posts (id SERIAL PRIMARY KEY)")
        
        # Add invalid migration record
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at, checksum, success)
            VALUES ('003', 'nonexistent', CURRENT_TIMESTAMP, 'fake_checksum', TRUE)
        """)
        
        conn.commit()
        conn.close()
        
        # Run diagnostics
        diagnostic_result = migration_runner.diagnose()
        assert diagnostic_result.success, f"Diagnostics should succeed: {diagnostic_result.message}"
        
        # Verify diagnostic findings
        assert "inconsistencies found" in diagnostic_result.message.lower(), "Should find inconsistencies"
        assert len(diagnostic_result.issues) > 0, "Should report issues"
        
        # Verify issue types
        issue_types = [issue.type for issue in diagnostic_result.issues]
        assert "missing_tracking" in issue_types, "Should detect missing tracking"
        assert "invalid_migration" in issue_types, "Should detect invalid migration"
        
        logger.info("Recovery diagnostics test passed")


@pytest.mark.integration
@pytest.mark.database
@pytest.mark.slow
class TestMigrationRecoveryAdvanced:
    """Advanced migration recovery tests."""
    
    def test_recover_unified_project_scenario(self, test_database, db_helper):
        """Test recovery from unified project's actual scenario."""
        logger.info("Testing recovery from unified project scenario")
        
        # Use unified project scenario data
        scenario_path = Path(__file__).parent / "test_data" / "scenario_unified"
        
        # Create migration runner with unified scenario
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(scenario_path)
        )
        
        # Ensure migration tables exist
        migration_runner._ensure_migration_tables()
        
        # Simulate unified project's actual state:
        # - Only migration 001 tracked
        # - But migrations 002, 003, 004 actually applied
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Apply all migrations manually in correct order
        migration_files = sorted(scenario_path.glob("*.sql"))
        migration_files = [f for f in migration_files if not f.name.endswith('.rollback.sql')]
        
        for migration_file in migration_files:
            logger.info(f"Applying migration file: {migration_file.name}")
            with open(migration_file, 'r') as f:
                cursor.execute(f.read())
        
        # Only track migration 001
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at, checksum)
            VALUES ('001', 'create_unified_schema', CURRENT_TIMESTAMP, 'dummy_checksum')
        """)
        
        conn.commit()
        conn.close()
        
        # Verify inconsistent state
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, "Should have 1 tracked migration"
        
        # But schema should have all objects
        assert db_helper.schema_exists("unified"), "Unified schema should exist"
        assert db_helper.table_exists("certificates", "unified"), "Certificates table should exist"
        assert db_helper.table_exists("dns_records", "unified"), "DNS records table should exist"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify all migrations are now tracked
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 4, f"Should have 4 tracked migrations after recovery"
        
        # Verify versions are correct
        versions = [m[0] for m in applied_migrations]
        assert versions == ["001", "002", "003", "004"], f"Expected all versions, got {versions}"
        
        logger.info("Recovery from unified project scenario test passed")
    
    def test_recover_with_data_preservation(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery preserves existing data."""
        logger.info("Testing recovery with data preservation")
        
        # Create migration with data
        (temp_migrations_dir / "001_create_users.sql").write_text("""
            CREATE SCHEMA test_preserve;
            CREATE TABLE test_preserve.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                email VARCHAR(255)
            );
            
            INSERT INTO test_preserve.users (username, email) VALUES
                ('user1', 'user1@example.com'),
                ('user2', 'user2@example.com');
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migration manually without tracking
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE SCHEMA test_preserve;
            CREATE TABLE test_preserve.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                email VARCHAR(255)
            );
        """)
        
        # Insert additional data
        cursor.execute("""
            INSERT INTO test_preserve.users (username, email) VALUES
                ('user1', 'user1@example.com'),
                ('user2', 'user2@example.com'),
                ('user3', 'user3@example.com');
        """)
        
        conn.commit()
        conn.close()
        
        # Verify data exists
        users = db_helper.fetch_all("SELECT username FROM test_preserve.users ORDER BY username")
        assert len(users) == 3, "Should have 3 users"
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify data was preserved
        users = db_helper.fetch_all("SELECT username FROM test_preserve.users ORDER BY username")
        assert len(users) == 3, "Should still have 3 users after recovery"
        
        # Verify migration is tracked
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, "Should have 1 tracked migration"
        
        logger.info("Recovery with data preservation test passed")
    
    def test_recover_complex_dependency_scenario(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery with complex object dependencies."""
        logger.info("Testing recovery with complex dependencies")
        
        # Create migrations with complex dependencies
        (temp_migrations_dir / "001_create_base.sql").write_text("""
            CREATE SCHEMA test_complex;
            CREATE TABLE test_complex.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL
            );
            
            CREATE TABLE test_complex.posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_complex.users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL
            );
        """)
        
        (temp_migrations_dir / "002_add_functions.sql").write_text("""
            CREATE OR REPLACE FUNCTION test_complex.get_user_posts(user_id INTEGER)
            RETURNS TABLE(post_id INTEGER, post_title VARCHAR(255)) AS $$
            BEGIN
                RETURN QUERY
                SELECT p.id, p.title
                FROM test_complex.posts p
                WHERE p.user_id = get_user_posts.user_id;
            END;
            $$ LANGUAGE plpgsql;
            
            CREATE OR REPLACE FUNCTION test_complex.notify_post_change()
            RETURNS TRIGGER AS $$
            BEGIN
                PERFORM pg_notify('post_change', NEW.id::text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            
            CREATE TRIGGER post_change_trigger
                AFTER INSERT OR UPDATE ON test_complex.posts
                FOR EACH ROW
                EXECUTE FUNCTION test_complex.notify_post_change();
        """)
        
        (temp_migrations_dir / "003_add_indexes.sql").write_text("""
            CREATE INDEX idx_posts_user_id ON test_complex.posts(user_id);
            CREATE INDEX idx_posts_title ON test_complex.posts(title);
            CREATE UNIQUE INDEX idx_users_username ON test_complex.users(username);
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations manually in wrong order (simulating complex issue)
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Apply migration 001
        cursor.execute("""
            CREATE SCHEMA test_complex;
            CREATE TABLE test_complex.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL
            );
            
            CREATE TABLE test_complex.posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES test_complex.users(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL
            );
        """)
        
        # Apply migration 003 (indexes) before 002 (functions)
        cursor.execute("""
            CREATE INDEX idx_posts_user_id ON test_complex.posts(user_id);
            CREATE INDEX idx_posts_title ON test_complex.posts(title);
            CREATE UNIQUE INDEX idx_users_username ON test_complex.users(username);
        """)
        
        # Track only migration 001
        cursor.execute("""
            INSERT INTO schema_migrations (version, description, applied_at, checksum, success)
            VALUES ('001', 'create_base', CURRENT_TIMESTAMP, 'dummy_checksum', TRUE)
        """)
        
        conn.commit()
        conn.close()
        
        # Use recovery functionality
        recovery_result = migration_runner.recover()
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify recovery handled complex dependencies
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 3, f"Should have 3 tracked migrations"
        
        # Verify all objects exist
        assert db_helper.table_exists("users", "test_complex"), "Users table should exist"
        assert db_helper.table_exists("posts", "test_complex"), "Posts table should exist"
        
        # Verify functions exist
        functions = db_helper.fetch_all("""
            SELECT routine_name FROM information_schema.routines
            WHERE routine_schema = 'test_complex'
        """)
        function_names = [f[0] for f in functions]
        assert 'get_user_posts' in function_names, "get_user_posts function should exist"
        assert 'notify_post_change' in function_names, "notify_post_change function should exist"
        
        # Verify indexes exist
        indexes = db_helper.fetch_all("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'test_complex'
        """)
        index_names = [i[0] for i in indexes]
        assert 'idx_posts_user_id' in index_names, "posts user_id index should exist"
        assert 'idx_posts_title' in index_names, "posts title index should exist"
        
        logger.info("Recovery with complex dependencies test passed")
    
    def test_recovery_performance_with_large_schema(self, test_database, temp_migrations_dir, db_helper):
        """Test recovery performance with large schema."""
        logger.info("Testing recovery performance with large schema")
        
        # Create many migrations
        num_migrations = 20
        for i in range(1, num_migrations + 1):
            version = f"{i:03d}"
            (temp_migrations_dir / f"{version}_migration.sql").write_text(f"""
                CREATE TABLE test_large.table_{version} (
                    id SERIAL PRIMARY KEY,
                    data TEXT DEFAULT 'test_data_{version}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX idx_table_{version}_data ON test_large.table_{version}(data);
            """)
        
        # Add schema creation to first migration
        (temp_migrations_dir / "001_migration.sql").write_text("""
            CREATE SCHEMA test_large;
        """ + (temp_migrations_dir / "001_migration.sql").read_text())
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply all migrations manually without tracking
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Apply schema creation
        cursor.execute("CREATE SCHEMA test_large")
        
        # Apply all table/index creations
        for i in range(1, num_migrations + 1):
            version = f"{i:03d}"
            cursor.execute(f"""
                CREATE TABLE test_large.table_{version} (
                    id SERIAL PRIMARY KEY,
                    data TEXT DEFAULT 'test_data_{version}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX idx_table_{version}_data ON test_large.table_{version}(data);
            """)
        
        conn.commit()
        conn.close()
        
        # Measure recovery time
        timer = PerformanceTimer()
        timer.start()
        recovery_result = migration_runner.recover()
        timer.stop()
        
        # Verify recovery succeeded
        assert recovery_result.success, f"Recovery should succeed: {recovery_result.message}"
        
        # Verify performance
        max_time_ms = 30000  # 30 seconds max
        assert timer.elapsed_ms < max_time_ms, f"Recovery took {timer.elapsed_ms}ms (> {max_time_ms}ms)"
        
        # Verify all migrations tracked
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == num_migrations, f"Should have {num_migrations} tracked migrations"
        
        logger.info(f"Recovery performance test passed - {num_migrations} migrations in {timer.elapsed_ms}ms")