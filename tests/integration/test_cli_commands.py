"""
CLI command tests for poststack.

Tests that validate the CLI interface works correctly with real databases,
including proper exit codes, output formatting, error handling, and 
end-to-end integration scenarios.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Any

import pytest
import psycopg2

from poststack.schema_migration import MigrationRunner
from .cli_helpers import CLITestHelper, CLIResult
from .database_fixtures import DatabaseManager, PerformanceTimer

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.database
class TestCLICommands:
    """Test core CLI command functionality."""
    
    def test_migrate_command_basic(self, test_database, sample_migrations, cli_runner):
        """Test basic migrate command functionality."""
        logger.info("Testing basic migrate command")
        
        # Run migrate command
        result = cli_runner.run_command("db", ["migrate"])
        
        # Verify command succeeded
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        assert "success" in result.output.lower() or "migrated" in result.output.lower(), "Output should indicate success"
        
        # Verify migrations were applied
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert len(versions) == 3, f"Should have 3 applied migrations, got {len(versions)}"
        assert versions == ["001", "002", "003"], f"Expected versions [001, 002, 003], got {versions}"
        
        logger.info("Basic migrate command test passed")
    
    def test_migrate_command_with_target(self, test_database, sample_migrations, cli_runner):
        """Test migrate command with target version."""
        logger.info("Testing migrate command with target version")
        
        # Run migrate command with target
        result = cli_runner.run_command("db", ["migrate", "--target", "002"])
        
        # Verify command succeeded
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Verify correct migrations were applied
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert len(versions) == 2, f"Should have 2 applied migrations, got {len(versions)}"
        assert versions == ["001", "002"], f"Expected versions [001, 002], got {versions}"
        
        logger.info("Migrate command with target test passed")
    
    def test_rollback_command_basic(self, test_database, sample_migrations, cli_runner):
        """Test basic rollback command functionality."""
        logger.info("Testing basic rollback command")
        
        # First apply all migrations
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Run rollback command
        result = cli_runner.run_command("db", ["rollback", "002", "--confirm"])
        
        # Verify command succeeded
        assert result.exit_code == 0, f"Rollback command should succeed: {result.error}"
        assert "rolled back" in result.output.lower() or "rollback" in result.output.lower(), "Output should indicate rollback"
        
        # Verify rollback was applied
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert len(versions) == 2, f"Should have 2 applied migrations after rollback, got {len(versions)}"
        assert versions == ["001", "002"], f"Expected versions [001, 002], got {versions}"
        
        logger.info("Basic rollback command test passed")
    
    def test_status_command(self, test_database, sample_migrations, cli_runner):
        """Test status command functionality."""
        logger.info("Testing status command")
        
        # Run status command before any migrations
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status command should succeed: {result.error}"
        assert "pending" in result.output.lower() or "not applied" in result.output.lower(), "Should show pending migrations"
        
        # Apply first migration
        result = cli_runner.run_command("db", ["migrate", "--target", "001"])
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Run status command after migration
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status command should succeed: {result.error}"
        assert "001" in result.output, "Should show applied migration 001"
        assert "applied" in result.output.lower() or "current" in result.output.lower(), "Should show migration status"
        
        logger.info("Status command test passed")
    
    def test_verify_command(self, test_database, sample_migrations, cli_runner):
        """Test verify command functionality."""
        logger.info("Testing verify command")
        
        # Apply migrations
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Run verify command
        result = cli_runner.run_command("db", ["verify-migrations"])
        assert result.exit_code == 0, f"Verify command should succeed: {result.error}"
        assert "verified successfully" in result.output.lower() or "valid" in result.output.lower(), "Should show verification success"
        
        logger.info("Verify command test passed")
    
    def test_recover_command(self, test_database, temp_migrations_dir, cli_runner):
        """Test recover command functionality."""
        logger.info("Testing recover command")
        
        # Create simple migration
        (temp_migrations_dir / "001_create_test.sql").write_text("""
            CREATE SCHEMA test_recover;
            CREATE TABLE test_recover.test_table (id SERIAL PRIMARY KEY);
        """)
        
        # Apply migration manually without tracking
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("CREATE SCHEMA test_recover")
        cursor.execute("CREATE TABLE test_recover.test_table (id SERIAL PRIMARY KEY)")
        conn.commit()
        conn.close()
        
        # Run recover command
        result = cli_runner.run_command("db", ["recover"])
        assert result.exit_code == 0, f"Recover command should succeed: {result.error}"
        assert "recovery" in result.output.lower() or "recovered" in result.output.lower(), "Should show recovery success"
        
        # Verify recovery worked
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert len(versions) == 1, f"Should have 1 recovered migration, got {len(versions)}"
        assert versions[0] == "001", f"Expected version 001, got {versions[0]}"
        
        logger.info("Recover command test passed")
    
    def test_diagnose_command(self, test_database, temp_migrations_dir, cli_runner):
        """Test diagnose command functionality."""
        logger.info("Testing diagnose command")
        
        # Create migration
        (temp_migrations_dir / "001_create_test.sql").write_text("""
            CREATE SCHEMA test_diagnose;
            CREATE TABLE test_diagnose.test_table (id SERIAL PRIMARY KEY);
        """)
        
        # Apply migration
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Run diagnose command
        result = cli_runner.run_command("db", ["diagnose"])
        assert result.exit_code == 0, f"Diagnose command should succeed: {result.error}"
        assert "diagnostic" in result.output.lower() or "check" in result.output.lower(), "Should show diagnostic output"
        
        logger.info("Diagnose command test passed")
    
    def test_command_error_handling(self, test_database, cli_runner):
        """Test CLI command error handling."""
        logger.info("Testing command error handling")
        
        # Test invalid command
        result = cli_runner.run_command("invalid_command")
        assert result.exit_code != 0, "Invalid command should fail"
        assert "error" in result.error.lower() or "unknown" in result.error.lower(), "Should show error message"
        
        # Test migrate with invalid target
        result = cli_runner.run_command("db", ["migrate", "--target", "999"])
        assert result.exit_code != 0, "Invalid target should fail"
        
        # Test rollback without migrations
        result = cli_runner.run_command("db", ["rollback", "001", "--confirm"])
        assert result.exit_code != 0, "Rollback without migrations should fail"
        
        logger.info("Command error handling test passed")
    
    def test_json_output_format(self, test_database, sample_migrations, cli_runner):
        """Test JSON output format."""
        logger.info("Testing JSON output format")
        
        # Run status command with JSON output
        result = cli_runner.run_command("db", ["migration-status", "--format", "json"])
        assert result.exit_code == 0, f"Status command should succeed: {result.error}"
        
        # Verify JSON output
        try:
            status_data = json.loads(result.output)
            assert isinstance(status_data, dict), "Should return JSON object"
            assert "current_version" in status_data or "status" in status_data, "Should contain status information"
        except json.JSONDecodeError:
            pytest.fail("Output should be valid JSON")
        
        logger.info("JSON output format test passed")
    
    def test_verbose_output(self, test_database, sample_migrations, cli_runner):
        """Test verbose output mode."""
        logger.info("Testing verbose output")
        
        # Run migrate command with verbose output
        result = cli_runner.run_command("db", ["migrate", "--verbose"])
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Verify verbose output contains more details
        assert len(result.output.split('\n')) > 5, "Verbose output should contain multiple lines"
        assert "migration" in result.output.lower(), "Should contain migration details"
        
        logger.info("Verbose output test passed")
    
    def test_dry_run_mode(self, test_database, sample_migrations, cli_runner):
        """Test dry run mode."""
        logger.info("Testing dry run mode")
        
        # Run migrate command in dry run mode
        result = cli_runner.run_command("db", ["migrate", "--dry-run"])
        assert result.exit_code == 0, f"Migrate dry run should succeed: {result.error}"
        assert "dry run" in result.output.lower() or "would apply" in result.output.lower(), "Should indicate dry run"
        
        # Verify no migrations were actually applied
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations")
        versions = cursor.fetchall()
        conn.close()
        
        assert len(versions) == 0, "Dry run should not apply any migrations"
        
        logger.info("Dry run mode test passed")


@pytest.mark.integration
@pytest.mark.database
class TestCLICommandsAdvanced:
    """Advanced CLI command tests."""
    
    def test_cli_performance_measurement(self, test_database, sample_migrations, cli_runner):
        """Test CLI command performance measurement."""
        logger.info("Testing CLI performance measurement")
        
        # Measure migrate command performance
        timer = PerformanceTimer()
        timer.start()
        result = cli_runner.run_command("db", ["migrate"])
        timer.stop()
        
        # Verify command succeeded
        assert result.exit_code == 0, f"Migrate command should succeed: {result.error}"
        
        # Verify reasonable performance
        max_time_ms = 10000  # 10 seconds max
        assert timer.elapsed_ms < max_time_ms, f"Migrate took {timer.elapsed_ms}ms (> {max_time_ms}ms)"
        
        logger.info(f"CLI performance test passed - migrate: {timer.elapsed_ms}ms")
    
    def test_cli_database_connection_handling(self, test_database, sample_migrations, cli_runner):
        """Test CLI database connection handling."""
        logger.info("Testing CLI database connection handling")
        
        # Test with valid connection
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status with valid connection should succeed: {result.error}"
        
        # Test with invalid connection
        cli_runner.database_url = "postgresql://invalid:invalid@localhost:5432/invalid"
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code != 0, "Status with invalid connection should fail"
        assert "connection" in result.error.lower() or "database" in result.error.lower(), "Should show connection error"
        
        logger.info("CLI database connection handling test passed")
    
    def test_cli_concurrent_operations(self, test_database, sample_migrations, cli_runner):
        """Test CLI concurrent operations handling."""
        logger.info("Testing CLI concurrent operations")
        
        # Start first migration (this should acquire lock)
        result1 = cli_runner.run_command("db", ["migrate"])
        assert result1.exit_code == 0, f"First migrate should succeed: {result1.stderr}"
        
        # Create second CLI runner
        cli_runner2 = CLITestHelper(test_database['connection_url'], str(temp_migrations_dir))
        
        # Try to run second migration while first is in progress
        # (This should fail or wait depending on implementation)
        result2 = cli_runner2.run_command("db", ["migrate"])
        
        # Either should succeed (if idempotent) or fail with lock error
        if result2.exit_code != 0:
            assert "lock" in result2.stderr.lower() or "already" in result2.stderr.lower(), "Should mention lock or already applied"
        
        logger.info("CLI concurrent operations test passed")
    
    def test_cli_unified_project_scenario(self, test_database, cli_runner):
        """Test CLI with unified project scenario."""
        logger.info("Testing CLI with unified project scenario")
        
        # Use unified project scenario data
        scenario_path = Path(__file__).parent / "test_data" / "scenario_unified"
        cli_runner.migrations_path = str(scenario_path)
        
        # Run migrate command
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Migrate should succeed: {result.error}"
        
        # Verify complex schema was created
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        
        # Check for unified schema
        cursor.execute("""
            SELECT schema_name FROM information_schema.schemata 
            WHERE schema_name = 'unified'
        """)
        assert cursor.fetchone() is not None, "Unified schema should exist"
        
        # Check for certificates table
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'unified' AND table_name = 'certificates'
        """)
        assert cursor.fetchone() is not None, "Certificates table should exist"
        
        conn.close()
        
        # Test rollback
        result = cli_runner.run_command("db", ["rollback", "002", "--confirm"])
        assert result.exit_code == 0, f"Rollback should succeed: {result.error}"
        
        logger.info("CLI unified project scenario test passed")
    
    def test_cli_workflow_integration(self, test_database, sample_migrations, cli_runner):
        """Test complete CLI workflow integration."""
        logger.info("Testing CLI workflow integration")
        
        # Step 1: Check initial status
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        
        # Step 2: Apply migrations
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Migrate should succeed: {result.error}"
        
        # Step 3: Verify migrations
        result = cli_runner.run_command("db", ["verify-migrations"])
        assert result.exit_code == 0, f"Verify should succeed: {result.error}"
        
        # Step 4: Check status after migration
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        assert "003" in result.output, "Should show current version"
        
        # Step 5: Rollback
        result = cli_runner.run_command("db", ["rollback", "002", "--confirm"])
        assert result.exit_code == 0, f"Rollback should succeed: {result.error}"
        
        # Step 6: Verify rollback
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        assert "002" in result.output, "Should show rollback version"
        
        # Step 7: Re-apply migrations
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Re-migrate should succeed: {result.error}"
        
        # Step 8: Final verification
        result = cli_runner.run_command("db", ["verify-migrations"])
        assert result.exit_code == 0, f"Final verify should succeed: {result.error}"
        
        logger.info("CLI workflow integration test passed")
    
    def test_cli_recovery_workflow(self, test_database, temp_migrations_dir, cli_runner):
        """Test CLI recovery workflow."""
        logger.info("Testing CLI recovery workflow")
        
        # Create migration
        (temp_migrations_dir / "001_create_test.sql").write_text("""
            CREATE SCHEMA test_recovery_cli;
            CREATE TABLE test_recovery_cli.test_table (id SERIAL PRIMARY KEY);
        """)
        
        # Apply migration manually without tracking (simulating unified project issue)
        conn = psycopg2.connect(test_database['connection_url'])
        cursor = conn.cursor()
        cursor.execute("CREATE SCHEMA test_recovery_cli")
        cursor.execute("CREATE TABLE test_recovery_cli.test_table (id SERIAL PRIMARY KEY)")
        conn.commit()
        conn.close()
        
        # Step 1: Diagnose the issue
        result = cli_runner.run_command("db", ["diagnose"])
        assert result.exit_code == 0, f"Diagnose should succeed: {result.error}"
        
        # Step 2: Check status (should show inconsistency)
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        
        # Step 3: Recover from inconsistency
        result = cli_runner.run_command("db", ["recover"])
        assert result.exit_code == 0, f"Recover should succeed: {result.error}"
        
        # Step 4: Verify recovery
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        assert "001" in result.output, "Should show recovered migration"
        
        # Step 5: Verify integrity
        result = cli_runner.run_command("db", ["verify-migrations"])
        assert result.exit_code == 0, f"Verify should succeed: {result.error}"
        
        logger.info("CLI recovery workflow test passed")
    
    def test_cli_error_recovery(self, test_database, temp_migrations_dir, cli_runner):
        """Test CLI error recovery scenarios."""
        logger.info("Testing CLI error recovery")
        
        # Create migration that will fail
        (temp_migrations_dir / "001_good_migration.sql").write_text("""
            CREATE SCHEMA test_error;
            CREATE TABLE test_error.test_table (id SERIAL PRIMARY KEY);
        """)
        
        (temp_migrations_dir / "002_bad_migration.sql").write_text("""
            CREATE TABLE test_error.bad_table (
                id SERIAL PRIMARY KEY,
                invalid_column INVALID_TYPE  -- This will fail
            );
        """)
        
        # Apply first migration
        result = cli_runner.run_command("db", ["migrate", "--target", "001"])
        assert result.exit_code == 0, f"First migrate should succeed: {result.error}"
        
        # Apply second migration (should fail)
        result = cli_runner.run_command("db", ["migrate", "--target", "002"])
        assert result.exit_code != 0, "Second migrate should fail"
        
        # Check status after failure
        result = cli_runner.run_command("db", ["migration-status"])
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        assert "001" in result.output, "Should show only first migration applied"
        
        # Fix the migration file
        (temp_migrations_dir / "002_bad_migration.sql").write_text("""
            CREATE TABLE test_error.good_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255)
            );
        """)
        
        # Try migration again
        result = cli_runner.run_command("db", ["migrate", "--target", "002"])
        assert result.exit_code == 0, f"Fixed migrate should succeed: {result.error}"
        
        logger.info("CLI error recovery test passed")


@pytest.mark.integration
@pytest.mark.database 
@pytest.mark.slow
class TestCLICommandsPerformance:
    """Performance tests for CLI commands."""
    
    def test_cli_large_migration_set_performance(self, test_database, temp_migrations_dir, cli_runner):
        """Test CLI performance with large migration sets."""
        logger.info("Testing CLI performance with large migration sets")
        
        # Create many migrations
        num_migrations = 50
        for i in range(1, num_migrations + 1):
            version = f"{i:03d}"
            (temp_migrations_dir / f"{version}_migration.sql").write_text(f"""
                CREATE TABLE test_performance.table_{version} (
                    id SERIAL PRIMARY KEY,
                    data TEXT DEFAULT 'test_data_{version}'
                );
            """)
        
        # Add schema creation to first migration
        (temp_migrations_dir / "001_migration.sql").write_text("""
            CREATE SCHEMA test_performance;
        """ + (temp_migrations_dir / "001_migration.sql").read_text())
        
        # Measure migration time
        timer = PerformanceTimer()
        timer.start()
        result = cli_runner.run_command("db", ["migrate"])
        timer.stop()
        
        # Verify command succeeded
        assert result.exit_code == 0, f"Migrate should succeed: {result.error}"
        
        # Verify reasonable performance
        max_time_ms = 120000  # 2 minutes max for 50 migrations
        assert timer.elapsed_ms < max_time_ms, f"Migration took {timer.elapsed_ms}ms (> {max_time_ms}ms)"
        
        logger.info(f"CLI large migration performance test passed - {num_migrations} migrations in {timer.elapsed_ms}ms")
    
    def test_cli_command_response_time(self, test_database, sample_migrations, cli_runner):
        """Test CLI command response times."""
        logger.info("Testing CLI command response times")
        
        # Apply migrations first
        result = cli_runner.run_command("db", ["migrate"])
        assert result.exit_code == 0, f"Migrate should succeed: {result.error}"
        
        # Test status command response time
        timer = PerformanceTimer()
        timer.start()
        result = cli_runner.run_command("db", ["migration-status"])
        timer.stop()
        
        assert result.exit_code == 0, f"Status should succeed: {result.error}"
        assert timer.elapsed_ms < 5000, f"Status took {timer.elapsed_ms}ms (> 5s)"
        
        # Test verify command response time
        timer.start()
        result = cli_runner.run_command("db", ["verify-migrations"])
        timer.stop()
        
        assert result.exit_code == 0, f"Verify should succeed: {result.error}"
        assert timer.elapsed_ms < 10000, f"Verify took {timer.elapsed_ms}ms (> 10s)"
        
        logger.info("CLI command response time test passed")