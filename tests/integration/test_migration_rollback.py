"""
Migration rollback tests for poststack.

Tests that validate rollback functionality works correctly, including 
rolling back to specific versions, handling data preservation, and 
maintaining database integrity during rollback operations.
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
class TestMigrationRollback:
    """Test core migration rollback functionality."""
    
    def test_basic_rollback_functionality(self, migration_runner, sample_migrations, db_helper):
        """Test basic rollback from latest version to previous version."""
        logger.info("Testing basic rollback functionality")
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Verify all migrations applied
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 3, f"Should have 3 applied migrations"
        
        # Rollback to version 002
        rollback_result = migration_runner.rollback(target_version="002")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify rollback state
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 2, f"Should have 2 applied migrations after rollback"
        
        # Verify correct migrations remain
        versions = [m[0] for m in applied_migrations]
        assert versions == ["001", "002"], f"Expected versions [001, 002], got {versions}"
        
        # Verify database objects were removed
        assert db_helper.schema_exists("test_schema"), "Schema should still exist"
        assert db_helper.table_exists("users", "test_schema"), "Users table should still exist"
        assert db_helper.table_exists("posts", "test_schema"), "Posts table should still exist"
        
        logger.info("Basic rollback functionality test passed")
    
    def test_rollback_to_specific_version(self, migration_runner, sample_migrations, db_helper):
        """Test rolling back to a specific version."""
        logger.info("Testing rollback to specific version")
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Rollback to version 001
        rollback_result = migration_runner.rollback(target_version="001")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify rollback state
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, f"Should have 1 applied migration after rollback"
        assert applied_migrations[0][0] == "001", f"Should have version 001, got {applied_migrations[0][0]}"
        
        # Verify database state
        assert db_helper.schema_exists("test_schema"), "Schema should exist"
        assert db_helper.table_exists("users", "test_schema"), "Users table should exist"
        assert not db_helper.table_exists("posts", "test_schema"), "Posts table should not exist"
        
        logger.info("Rollback to specific version test passed")
    
    def test_rollback_with_data_preservation(self, test_database, temp_migrations_dir, db_helper):
        """Test that rollback preserves data when possible."""
        logger.info("Testing rollback with data preservation")
        
        # Create migrations that add and remove columns
        (temp_migrations_dir / "001_create_users.sql").write_text("""
            CREATE SCHEMA test_data;
            CREATE TABLE test_data.users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL
            );
        """)
        
        (temp_migrations_dir / "002_add_profile_fields.sql").write_text("""
            ALTER TABLE test_data.users 
            ADD COLUMN first_name VARCHAR(100),
            ADD COLUMN last_name VARCHAR(100),
            ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        """)
        
        # Create rollback files
        (temp_migrations_dir / "002_add_profile_fields.rollback.sql").write_text("""
            ALTER TABLE test_data.users 
            DROP COLUMN IF EXISTS first_name,
            DROP COLUMN IF EXISTS last_name,
            DROP COLUMN IF EXISTS created_at;
        """)
        
        (temp_migrations_dir / "001_create_users.rollback.sql").write_text("""
            DROP SCHEMA IF EXISTS test_data CASCADE;
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Insert test data
        db_helper.execute_sql("""
            INSERT INTO test_data.users (username, email, first_name, last_name)
            VALUES ('testuser', 'test@example.com', 'Test', 'User')
        """)
        
        # Verify data exists
        users = db_helper.fetch_all("SELECT username, email, first_name, last_name FROM test_data.users")
        assert len(users) == 1, "Should have 1 user"
        assert users[0] == ('testuser', 'test@example.com', 'Test', 'User'), "User data should match"
        
        # Rollback to version 001
        rollback_result = migration_runner.rollback(target_version="001")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify core data preserved
        users = db_helper.fetch_all("SELECT username, email FROM test_data.users")
        assert len(users) == 1, "Should still have 1 user"
        assert users[0] == ('testuser', 'test@example.com'), "Core user data should be preserved"
        
        # Verify additional columns removed
        columns = db_helper.fetch_all("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = 'test_data' AND table_name = 'users'
        """)
        column_names = [col[0] for col in columns]
        assert 'first_name' not in column_names, "first_name column should be removed"
        assert 'last_name' not in column_names, "last_name column should be removed"
        assert 'created_at' not in column_names, "created_at column should be removed"
        
        logger.info("Rollback with data preservation test passed")
    
    def test_rollback_transaction_handling(self, test_database, temp_migrations_dir, db_helper):
        """Test that rollback operations are properly transactional."""
        logger.info("Testing rollback transaction handling")
        
        # Create migrations
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_rollback_tx;
            CREATE TABLE test_rollback_tx.test_table (id SERIAL PRIMARY KEY);
        """)
        
        (temp_migrations_dir / "002_good_migration.sql").write_text("""
            CREATE TABLE test_rollback_tx.good_table (id SERIAL PRIMARY KEY);
        """)
        
        # Create rollback files - one valid, one invalid
        (temp_migrations_dir / "002_good_migration.rollback.sql").write_text("""
            DROP TABLE test_rollback_tx.good_table;
            -- Invalid SQL to cause rollback failure
            INVALID SQL STATEMENT;
        """)
        
        (temp_migrations_dir / "001_create_schema.rollback.sql").write_text("""
            DROP SCHEMA IF EXISTS test_rollback_tx CASCADE;
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Verify initial state
        assert db_helper.schema_exists("test_rollback_tx"), "Schema should exist"
        assert db_helper.table_exists("test_table", "test_rollback_tx"), "test_table should exist"
        assert db_helper.table_exists("good_table", "test_rollback_tx"), "good_table should exist"
        
        # Attempt rollback (should fail due to invalid SQL)
        rollback_result = migration_runner.rollback(target_version="001")
        assert not rollback_result.success, "Rollback should fail due to invalid SQL"
        
        # Verify database state is unchanged due to transaction rollback
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 2, "Should still have 2 applied migrations"
        
        assert db_helper.schema_exists("test_rollback_tx"), "Schema should still exist"
        assert db_helper.table_exists("test_table", "test_rollback_tx"), "test_table should still exist"
        assert db_helper.table_exists("good_table", "test_rollback_tx"), "good_table should still exist"
        
        logger.info("Rollback transaction handling test passed")
    
    def test_rollback_performance(self, test_database, temp_migrations_dir, db_helper):
        """Test that rollback operations complete within reasonable time."""
        logger.info("Testing rollback performance")
        
        # Create multiple migrations for performance testing
        num_migrations = 10
        for i in range(1, num_migrations + 1):
            version = f"{i:03d}"
            (temp_migrations_dir / f"{version}_migration.sql").write_text(f"""
                CREATE TABLE test_performance.table_{version} (
                    id SERIAL PRIMARY KEY,
                    data TEXT DEFAULT 'test_data_{version}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            (temp_migrations_dir / f"{version}_migration.rollback.sql").write_text(f"""
                DROP TABLE IF EXISTS test_performance.table_{version};
            """)
        
        # Add schema creation to first migration
        (temp_migrations_dir / "001_migration.sql").write_text("""
            CREATE SCHEMA test_performance;
        """ + (temp_migrations_dir / "001_migration.sql").read_text())
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Measure rollback time
        timer = PerformanceTimer()
        timer.start()
        rollback_result = migration_runner.rollback(target_version="005")
        timer.stop()
        
        # Verify rollback succeeded
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify performance
        max_time_ms = 15000  # 15 seconds max for rollback
        assert timer.elapsed_ms < max_time_ms, f"Rollback took {timer.elapsed_ms}ms (> {max_time_ms}ms)"
        
        # Verify correct final state
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 5, f"Should have 5 applied migrations after rollback"
        
        logger.info(f"Rollback performance test passed - rollback time: {timer.elapsed_ms}ms")
    
    def test_rollback_with_dependencies(self, test_database, temp_migrations_dir, db_helper):
        """Test rollback with complex table dependencies."""
        logger.info("Testing rollback with dependencies")
        
        # Create migrations with foreign key dependencies
        (temp_migrations_dir / "001_create_users.sql").write_text("""
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
                title VARCHAR(255) NOT NULL
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
        
        # Create rollback files in correct dependency order
        (temp_migrations_dir / "003_create_comments.rollback.sql").write_text("""
            DROP TABLE IF EXISTS test_deps.comments;
        """)
        
        (temp_migrations_dir / "002_create_posts.rollback.sql").write_text("""
            DROP TABLE IF EXISTS test_deps.posts;
        """)
        
        (temp_migrations_dir / "001_create_users.rollback.sql").write_text("""
            DROP SCHEMA IF EXISTS test_deps CASCADE;
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Insert test data to verify dependencies
        db_helper.execute_sql("INSERT INTO test_deps.users (username) VALUES ('testuser')")
        db_helper.execute_sql("INSERT INTO test_deps.posts (user_id, title) VALUES (1, 'Test Post')")
        db_helper.execute_sql("INSERT INTO test_deps.comments (post_id, user_id, content) VALUES (1, 1, 'Test Comment')")
        
        # Rollback to version 001
        rollback_result = migration_runner.rollback(target_version="001")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify correct state
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 1, "Should have 1 applied migration"
        
        # Verify tables were removed in correct order
        assert db_helper.table_exists("users", "test_deps"), "Users table should exist"
        assert not db_helper.table_exists("posts", "test_deps"), "Posts table should not exist"
        assert not db_helper.table_exists("comments", "test_deps"), "Comments table should not exist"
        
        # Verify data is preserved
        users = db_helper.fetch_all("SELECT username FROM test_deps.users")
        assert len(users) == 1, "Should have 1 user"
        assert users[0][0] == 'testuser', "User data should be preserved"
        
        logger.info("Rollback with dependencies test passed")
    
    def test_rollback_validation_and_safety(self, migration_runner, sample_migrations, db_helper):
        """Test rollback validation and safety checks."""
        logger.info("Testing rollback validation and safety")
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Test invalid rollback targets
        invalid_result = migration_runner.rollback(target_version="999")
        assert not invalid_result.success, "Rollback to invalid version should fail"
        assert "not found" in invalid_result.message.lower(), "Error should mention version not found"
        
        # Test rollback to future version
        future_result = migration_runner.rollback(target_version="004")
        assert not future_result.success, "Rollback to future version should fail"
        
        # Test rollback to current version
        current_result = migration_runner.rollback(target_version="003")
        assert current_result.success, "Rollback to current version should succeed"
        assert "already at" in current_result.message.lower() or "no rollback" in current_result.message.lower(), "Should indicate already at target"
        
        # Verify state unchanged
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 3, "Should still have 3 applied migrations"
        
        logger.info("Rollback validation and safety test passed")
    
    def test_rollback_status_reporting(self, migration_runner, sample_migrations, db_helper):
        """Test that rollback operations report status correctly."""
        logger.info("Testing rollback status reporting")
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Check initial status
        initial_status = migration_runner.status()
        assert initial_status.current_version == "003", "Should be at version 003"
        assert len(initial_status.applied_migrations) == 3, "Should have 3 applied migrations"
        
        # Rollback to version 002
        rollback_result = migration_runner.rollback(target_version="002")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Check status after rollback
        status_after_rollback = migration_runner.status()
        assert status_after_rollback.current_version == "002", "Should be at version 002"
        assert len(status_after_rollback.applied_migrations) == 2, "Should have 2 applied migrations"
        assert len(status_after_rollback.pending_migrations) == 1, "Should have 1 pending migration"
        
        # Verify rollback result contains useful information
        assert "rolled back" in rollback_result.message.lower(), "Message should mention rollback"
        assert "002" in rollback_result.message, "Message should mention target version"
        
        logger.info("Rollback status reporting test passed")


@pytest.mark.integration
@pytest.mark.database
@pytest.mark.slow
class TestMigrationRollbackAdvanced:
    """Advanced migration rollback tests."""
    
    def test_rollback_unified_project_scenario(self, test_database, db_helper):
        """Test rollback using unified project scenario data."""
        logger.info("Testing rollback with unified project scenario")
        
        # Use unified project scenario data
        scenario_path = Path(__file__).parent / "test_data" / "scenario_unified"
        
        # Create migration runner with unified scenario
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(scenario_path)
        )
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Verify complex schema was created
        assert db_helper.schema_exists("unified"), "Unified schema should exist"
        assert db_helper.table_exists("certificates", "unified"), "Certificates table should exist"
        assert db_helper.table_exists("dns_records", "unified"), "DNS records table should exist"
        
        # Rollback to version 002 (before DNS records)
        rollback_result = migration_runner.rollback(target_version="002")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify DNS tables were removed
        assert not db_helper.table_exists("dns_records", "unified"), "DNS records table should be removed"
        assert not db_helper.table_exists("dns_zones", "unified"), "DNS zones table should be removed"
        
        # Verify certificates table still exists
        assert db_helper.table_exists("certificates", "unified"), "Certificates table should still exist"
        
        logger.info("Rollback with unified project scenario test passed")
    
    def test_rollback_data_transformation_reversal(self, test_database, temp_migrations_dir, db_helper):
        """Test that rollback properly reverses data transformations."""
        logger.info("Testing rollback data transformation reversal")
        
        # Create migration that transforms data
        (temp_migrations_dir / "001_create_users.sql").write_text("""
            CREATE SCHEMA test_transform;
            CREATE TABLE test_transform.users (
                id SERIAL PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL
            );
            
            INSERT INTO test_transform.users (full_name, email) VALUES
                ('John Doe', 'john@example.com'),
                ('Jane Smith', 'jane@example.com');
        """)
        
        # Create migration that splits names
        (temp_migrations_dir / "002_split_names.sql").write_text("""
            -- Add new columns
            ALTER TABLE test_transform.users 
            ADD COLUMN first_name VARCHAR(100),
            ADD COLUMN last_name VARCHAR(100);
            
            -- Transform data
            UPDATE test_transform.users 
            SET first_name = SPLIT_PART(full_name, ' ', 1),
                last_name = SPLIT_PART(full_name, ' ', 2);
            
            -- Remove old column
            ALTER TABLE test_transform.users DROP COLUMN full_name;
        """)
        
        # Create rollback that reverses transformation
        (temp_migrations_dir / "002_split_names.rollback.sql").write_text("""
            -- Add back full_name column
            ALTER TABLE test_transform.users ADD COLUMN full_name VARCHAR(255);
            
            -- Reverse transformation
            UPDATE test_transform.users 
            SET full_name = first_name || ' ' || last_name;
            
            -- Remove split columns
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
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Verify transformed data
        users = db_helper.fetch_all("SELECT first_name, last_name FROM test_transform.users ORDER BY first_name")
        assert len(users) == 2, "Should have 2 users"
        assert users[0] == ('Jane', 'Smith'), "First user should be Jane Smith"
        assert users[1] == ('John', 'Doe'), "Second user should be John Doe"
        
        # Rollback to version 001
        rollback_result = migration_runner.rollback(target_version="001")
        assert rollback_result.success, f"Rollback should succeed: {rollback_result.message}"
        
        # Verify data transformation was reversed
        users = db_helper.fetch_all("SELECT full_name FROM test_transform.users ORDER BY full_name")
        assert len(users) == 2, "Should have 2 users"
        assert users[0] == ('Jane Smith',), "First user should be Jane Smith"
        assert users[1] == ('John Doe',), "Second user should be John Doe"
        
        # Verify split columns were removed
        columns = db_helper.fetch_all("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = 'test_transform' AND table_name = 'users'
        """)
        column_names = [col[0] for col in columns]
        assert 'first_name' not in column_names, "first_name column should be removed"
        assert 'last_name' not in column_names, "last_name column should be removed"
        assert 'full_name' in column_names, "full_name column should exist"
        
        logger.info("Rollback data transformation reversal test passed")
    
    def test_rollback_with_missing_rollback_files(self, test_database, temp_migrations_dir, db_helper):
        """Test rollback behavior when rollback files are missing."""
        logger.info("Testing rollback with missing rollback files")
        
        # Create migration without rollback file
        (temp_migrations_dir / "001_create_schema.sql").write_text("""
            CREATE SCHEMA test_missing;
            CREATE TABLE test_missing.test_table (id SERIAL PRIMARY KEY);
        """)
        
        # Create second migration with rollback file
        (temp_migrations_dir / "002_add_table.sql").write_text("""
            CREATE TABLE test_missing.another_table (id SERIAL PRIMARY KEY);
        """)
        
        (temp_migrations_dir / "002_add_table.rollback.sql").write_text("""
            DROP TABLE IF EXISTS test_missing.another_table;
        """)
        
        # Create migration runner
        migration_runner = MigrationRunner(
            database_url=test_database['connection_url'],
            migrations_path=str(temp_migrations_dir)
        )
        
        # Apply all migrations
        result = migration_runner.migrate()
        assert result.success, f"Migration should succeed: {result.message}"
        
        # Attempt rollback (should fail due to missing rollback file)
        rollback_result = migration_runner.rollback(target_version="001")
        assert not rollback_result.success, "Rollback should fail when rollback file is missing"
        assert "rollback file" in rollback_result.message.lower(), "Error should mention rollback file"
        
        # Verify no changes were made
        applied_migrations = db_helper.get_applied_migrations()
        assert len(applied_migrations) == 2, "Should still have 2 applied migrations"
        
        logger.info("Rollback with missing rollback files test passed")