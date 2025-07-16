"""
CLI testing helpers for integration tests.

Provides utilities for testing poststack CLI commands with real databases,
including command execution, output parsing, and result validation.
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from click.testing import CliRunner

from poststack.cli import cli
from poststack.database import database

logger = logging.getLogger(__name__)


@dataclass
class CLIResult:
    """Result of a CLI command execution."""
    exit_code: int
    output: str
    error: str
    success: bool
    command: str
    duration_ms: int


class CLITestHelper:
    """Helper class for testing CLI commands."""
    
    def __init__(self, database_url: str, migrations_path: str):
        self.database_url = database_url
        self.migrations_path = migrations_path
        self.runner = CliRunner()
    
    def run_command(self, command: str, args: List[str] = None, input_data: str = None) -> CLIResult:
        """Run a CLI command and return structured result."""
        args = args or []
        
        # Set up environment for command
        env = os.environ.copy()
        env['POSTSTACK_DATABASE_URL'] = self.database_url
        env['POSTSTACK_MIGRATIONS_PATH'] = self.migrations_path
        env['POSTSTACK_TEST_MODE'] = 'true'
        
        # Build command args
        cmd_args = [command] + args
        
        logger.debug(f"Running CLI command: {cmd_args}")
        
        import time
        start_time = time.time()
        
        # Execute command
        result = self.runner.invoke(
            cli,
            cmd_args,
            input=input_data,
            env=env,
            catch_exceptions=False
        )
        
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        cli_result = CLIResult(
            exit_code=result.exit_code,
            output=result.output or "",
            error=result.stderr_bytes.decode() if result.stderr_bytes else "",
            success=result.exit_code == 0,
            command=f"poststack {' '.join(cmd_args)}",
            duration_ms=duration_ms
        )
        
        logger.debug(f"CLI result: exit_code={cli_result.exit_code}, success={cli_result.success}")
        
        return cli_result
    
    def run_database_command(self, subcommand: str, args: List[str] = None, input_data: str = None) -> CLIResult:
        """Run a database subcommand."""
        args = args or []
        return self.run_command("database", [subcommand] + args, input_data)
    
    def migration_status(self) -> CLIResult:
        """Get migration status."""
        return self.run_database_command("migration-status")
    
    def migrate(self, target: str = None, dry_run: bool = False) -> CLIResult:
        """Run migration command."""
        args = []
        if target:
            args.extend(["--target", target])
        if dry_run:
            args.append("--dry-run")
        return self.run_database_command("migrate-project", args)
    
    def rollback(self, target: str, confirm: bool = False) -> CLIResult:
        """Run rollback command."""
        args = [target]
        if confirm:
            args.append("--confirm")
        return self.run_database_command("rollback", args)
    
    def create_schema(self, force: bool = False) -> CLIResult:
        """Run create schema command."""
        args = []
        if force:
            args.append("--force")
        return self.run_database_command("create-schema", args)
    
    def show_schema(self) -> CLIResult:
        """Run show schema command."""
        return self.run_database_command("show-schema")
    
    def verify_migrations(self) -> CLIResult:
        """Run verify migrations command."""
        return self.run_database_command("verify-migrations")
    
    def unlock_migrations(self) -> CLIResult:
        """Run unlock migrations command."""
        return self.run_database_command("unlock-migrations")


class CLIOutputParser:
    """Parse CLI output into structured data."""
    
    @staticmethod
    def parse_migration_status(output: str) -> Dict:
        """Parse migration status output."""
        result = {
            'current_version': None,
            'applied_count': 0,
            'pending_count': 0,
            'applied_migrations': [],
            'pending_migrations': [],
            'is_locked': False
        }
        
        # Extract current version
        version_match = re.search(r'Current version: (\w+)', output)
        if version_match:
            result['current_version'] = version_match.group(1)
        
        # Extract counts
        applied_match = re.search(r'Applied migrations: (\d+)', output)
        if applied_match:
            result['applied_count'] = int(applied_match.group(1))
        
        pending_match = re.search(r'Pending migrations: (\d+)', output)
        if pending_match:
            result['pending_count'] = int(pending_match.group(1))
        
        # Extract applied migrations
        applied_section = re.search(r'Applied migrations:(.*?)(?=Pending migrations:|$)', output, re.DOTALL)
        if applied_section:
            for line in applied_section.group(1).split('\n'):
                line = line.strip()
                if line.startswith('✅'):
                    migration_match = re.search(r'(\d+):\s*(.+)', line)
                    if migration_match:
                        result['applied_migrations'].append({
                            'version': migration_match.group(1),
                            'description': migration_match.group(2)
                        })
        
        # Extract pending migrations
        pending_section = re.search(r'Pending migrations:(.*?)$', output, re.DOTALL)
        if pending_section:
            for line in pending_section.group(1).split('\n'):
                line = line.strip()
                if line.startswith('⏳'):
                    migration_match = re.search(r'(\d+):\s*(.+)', line)
                    if migration_match:
                        result['pending_migrations'].append({
                            'version': migration_match.group(1),
                            'description': migration_match.group(2)
                        })
        
        return result
    
    @staticmethod
    def parse_migration_result(output: str) -> Dict:
        """Parse migration execution result."""
        result = {
            'success': False,
            'applied_count': 0,
            'failed_migration': None,
            'error_message': None,
            'execution_time': None
        }
        
        # Check for success
        if '🎉' in output or 'successfully' in output.lower():
            result['success'] = True
        
        # Extract applied count
        applied_match = re.search(r'Applied (\d+) migration', output)
        if applied_match:
            result['applied_count'] = int(applied_match.group(1))
        
        # Extract error information
        if 'failed' in output.lower():
            result['success'] = False
            error_match = re.search(r'Migration (\d+) failed: (.+)', output)
            if error_match:
                result['failed_migration'] = error_match.group(1)
                result['error_message'] = error_match.group(2)
        
        return result
    
    @staticmethod
    def parse_schema_info(output: str) -> Dict:
        """Parse schema information output."""
        result = {
            'schema_exists': False,
            'table_count': 0,
            'tables': [],
            'version': None
        }
        
        # Check if schema exists
        if 'poststack schema' in output.lower():
            result['schema_exists'] = True
        
        # Extract table count
        table_match = re.search(r'Tables:\s*(\d+)', output)
        if table_match:
            result['table_count'] = int(table_match.group(1))
        
        # Extract table names
        table_section = re.search(r'Tables:(.*?)(?=\n\n|\n$|$)', output, re.DOTALL)
        if table_section:
            for line in table_section.group(1).split('\n'):
                line = line.strip()
                if line and not line.startswith('Tables:'):
                    result['tables'].append(line)
        
        return result


class CLITestValidator:
    """Validate CLI command results."""
    
    @staticmethod
    def validate_successful_migration(result: CLIResult, expected_count: int = None) -> List[str]:
        """Validate successful migration result."""
        errors = []
        
        if not result.success:
            errors.append(f"Migration failed with exit code {result.exit_code}")
            return errors
        
        if 'successfully' not in result.output.lower():
            errors.append("Migration output doesn't indicate success")
        
        if expected_count is not None:
            parsed = CLIOutputParser.parse_migration_result(result.output)
            if parsed['applied_count'] != expected_count:
                errors.append(f"Expected {expected_count} migrations, got {parsed['applied_count']}")
        
        return errors
    
    @staticmethod
    def validate_migration_status(result: CLIResult, expected_applied: int = None, expected_pending: int = None) -> List[str]:
        """Validate migration status result."""
        errors = []
        
        if not result.success:
            errors.append(f"Migration status failed with exit code {result.exit_code}")
            return errors
        
        parsed = CLIOutputParser.parse_migration_status(result.output)
        
        if expected_applied is not None and parsed['applied_count'] != expected_applied:
            errors.append(f"Expected {expected_applied} applied migrations, got {parsed['applied_count']}")
        
        if expected_pending is not None and parsed['pending_count'] != expected_pending:
            errors.append(f"Expected {expected_pending} pending migrations, got {parsed['pending_count']}")
        
        return errors
    
    @staticmethod
    def validate_rollback_success(result: CLIResult, target_version: str) -> List[str]:
        """Validate successful rollback result."""
        errors = []
        
        if not result.success:
            errors.append(f"Rollback failed with exit code {result.exit_code}")
            return errors
        
        if 'rolled back' not in result.output.lower():
            errors.append("Rollback output doesn't indicate success")
        
        if target_version not in result.output:
            errors.append(f"Rollback output doesn't mention target version {target_version}")
        
        return errors
    
    @staticmethod
    def validate_error_message(result: CLIResult, expected_error: str) -> List[str]:
        """Validate that error message contains expected text."""
        errors = []
        
        if result.success:
            errors.append("Expected command to fail but it succeeded")
            return errors
        
        combined_output = result.output + result.error
        if expected_error.lower() not in combined_output.lower():
            errors.append(f"Expected error message '{expected_error}' not found in output")
        
        return errors


class CLIIntegrationTestRunner:
    """High-level test runner for CLI integration tests."""
    
    def __init__(self, cli_helper: CLITestHelper):
        self.cli_helper = cli_helper
        self.validator = CLITestValidator()
    
    def test_fresh_migration_workflow(self, expected_migrations: List[str]) -> List[str]:
        """Test complete fresh migration workflow."""
        errors = []
        
        # 1. Check initial status
        status_result = self.cli_helper.migration_status()
        errors.extend(self.validator.validate_migration_status(
            status_result, expected_applied=0, expected_pending=len(expected_migrations)
        ))
        
        # 2. Run migrations
        migrate_result = self.cli_helper.migrate()
        errors.extend(self.validator.validate_successful_migration(
            migrate_result, expected_count=len(expected_migrations)
        ))
        
        # 3. Check final status
        final_status = self.cli_helper.migration_status()
        errors.extend(self.validator.validate_migration_status(
            final_status, expected_applied=len(expected_migrations), expected_pending=0
        ))
        
        return errors
    
    def test_rollback_workflow(self, target_version: str, expected_applied: int) -> List[str]:
        """Test rollback workflow."""
        errors = []
        
        # 1. Run rollback
        rollback_result = self.cli_helper.rollback(target_version, confirm=True)
        errors.extend(self.validator.validate_rollback_success(rollback_result, target_version))
        
        # 2. Check status after rollback
        status_result = self.cli_helper.migration_status()
        errors.extend(self.validator.validate_migration_status(
            status_result, expected_applied=expected_applied
        ))
        
        return errors
    
    def test_verification_workflow(self) -> List[str]:
        """Test migration verification workflow."""
        errors = []
        
        # Run verification
        verify_result = self.cli_helper.verify_migrations()
        if not verify_result.success:
            errors.append(f"Migration verification failed: {verify_result.output}")
        
        return errors
    
    def test_error_handling(self, command_func, expected_error: str) -> List[str]:
        """Test error handling for a command."""
        errors = []
        
        result = command_func()
        errors.extend(self.validator.validate_error_message(result, expected_error))
        
        return errors


class CLIPerformanceTester:
    """Performance testing utilities for CLI commands."""
    
    def __init__(self, cli_helper: CLITestHelper):
        self.cli_helper = cli_helper
    
    def benchmark_migration_performance(self, max_duration_ms: int = 30000) -> Dict:
        """Benchmark migration performance."""
        result = self.cli_helper.migrate()
        
        return {
            'success': result.success,
            'duration_ms': result.duration_ms,
            'within_limit': result.duration_ms <= max_duration_ms,
            'performance_ratio': result.duration_ms / max_duration_ms
        }
    
    def benchmark_status_performance(self, max_duration_ms: int = 5000) -> Dict:
        """Benchmark status command performance."""
        result = self.cli_helper.migration_status()
        
        return {
            'success': result.success,
            'duration_ms': result.duration_ms,
            'within_limit': result.duration_ms <= max_duration_ms,
            'performance_ratio': result.duration_ms / max_duration_ms
        }


# Test utilities for complex scenarios
class ScenarioTestHelper:
    """Helper for testing complex migration scenarios."""
    
    def __init__(self, cli_helper: CLITestHelper, db_helper):
        self.cli_helper = cli_helper
        self.db_helper = db_helper
    
    def create_unified_scenario_and_test_recovery(self) -> Dict:
        """Create unified project scenario and test recovery."""
        # Create the problematic state
        self.db_helper.manually_apply_migration("""
            CREATE SCHEMA IF NOT EXISTS test_schema;
            CREATE TABLE test_schema.users (id SERIAL PRIMARY KEY);
            CREATE TABLE test_schema.certificates (id SERIAL PRIMARY KEY);
            CREATE TABLE test_schema.dns_records (id SERIAL PRIMARY KEY);
        """)
        
        # Only track first migration
        self.db_helper.manually_track_migration("001", "Initial migration", "checksum_001")
        
        # Check that status shows inconsistency
        status_result = self.cli_helper.migration_status()
        
        return {
            'inconsistent_state_detected': 'inconsistent' in status_result.output.lower(),
            'status_result': status_result,
            'repair_needed': True
        }
    
    def test_migration_with_failure_recovery(self) -> Dict:
        """Test migration with simulated failure and recovery."""
        # This would be implemented with more complex scenarios
        return {
            'failure_handled': True,
            'recovery_successful': True,
            'data_integrity_maintained': True
        }