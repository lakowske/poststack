# Poststack Migration Testing Framework

A comprehensive testing framework for database migrations that provides integration testing, diagnostics, recovery tools, and CLI commands for managing complex migration scenarios.

## Overview

This framework was developed to address migration management challenges discovered in the unified project, where migration tracking inconsistencies led to complex recovery scenarios. It provides:

- **Integration Testing** - Comprehensive test suites for migration integrity, rollbacks, and recovery
- **Diagnostic Tools** - Advanced diagnostics to detect migration issues and inconsistencies
- **Recovery Tools** - Automated recovery from common migration problems
- **CLI Commands** - Enhanced CLI tools for migration management
- **Performance Testing** - Load testing and performance validation

## Architecture

The framework consists of several key components:

### Testing Infrastructure
- **Database Fixtures** (`conftest.py`) - PostgreSQL container management and test isolation
- **CLI Testing** (`cli_helpers.py`) - Framework for testing CLI commands end-to-end
- **Test Data** (`test_data/`) - Scenario-based test data including unified project scenarios

### Test Suites
- **Migration Integrity** (`test_migration_integrity.py`) - Core migration functionality tests
- **Rollback Testing** (`test_migration_rollback.py`) - Comprehensive rollback validation
- **Recovery Testing** (`test_migration_recovery.py`) - Recovery from inconsistent states
- **CLI Command Testing** (`test_cli_commands.py`) - End-to-end CLI command validation

### Diagnostic and Repair Tools
- **Migration Diagnostics** (`migration_diagnostics.py`) - Detection and analysis of migration issues
- **Enhanced CLI** (`cli_enhanced.py`) - Advanced CLI commands for diagnostics and repair

## Installation and Setup

### Prerequisites

- Python 3.8+
- PostgreSQL 12+
- Docker (for testcontainers)
- pytest
- psycopg2-binary

### Installation

1. Install the poststack package in development mode:
   ```bash
   pip install -e /home/seth/Software/dev/poststack/
   ```

2. Install test dependencies:
   ```bash
   pip install pytest pytest-asyncio testcontainers psycopg2-binary
   ```

3. Verify installation:
   ```bash
   pytest --version
   poststack --version
   ```

### Environment Setup

The tests use testcontainers to create isolated PostgreSQL instances. No additional configuration is required - the framework automatically manages test databases.

## Running Tests

### Test Categories

Tests are organized by markers:

- `@pytest.mark.integration` - Integration tests requiring database connections
- `@pytest.mark.database` - Database-specific tests
- `@pytest.mark.slow` - Long-running tests (performance, large datasets)

### Running Specific Test Suites

```bash
# Run all integration tests
pytest tests/integration/ -m integration

# Run migration integrity tests
pytest tests/integration/test_migration_integrity.py -v

# Run rollback tests
pytest tests/integration/test_migration_rollback.py -v

# Run recovery tests
pytest tests/integration/test_migration_recovery.py -v

# Run CLI command tests
pytest tests/integration/test_cli_commands.py -v

# Run performance tests (slow)
pytest tests/integration/ -m slow -v
```

### Running with Different Scenarios

```bash
# Run tests with unified project scenario
pytest tests/integration/test_migration_recovery.py::TestMigrationRecoveryAdvanced::test_recover_unified_project_scenario -v

# Run tests with specific test data
pytest tests/integration/test_migration_integrity.py -v --tb=short
```

### Performance Testing

```bash
# Run performance tests
pytest tests/integration/ -m "integration and slow" -v

# Run with performance output
pytest tests/integration/ -m integration -v --tb=short --showlocals
```

## CLI Commands

The framework provides enhanced CLI commands for migration management:

### Diagnostic Commands

```bash
# Run comprehensive diagnostics
poststack db diagnose

# Get diagnostics in JSON format
poststack db diagnose --format json

# Filter by severity
poststack db diagnose --severity high

# Filter by issue type
poststack db diagnose --type missing_tracking
```

### Recovery Commands

```bash
# Recover from inconsistent states (unified project scenario)
poststack db recover

# Dry run recovery (preview only)
poststack db recover --dry-run

# Force recovery (dangerous operations)
poststack db recover --force
```

### Repair Commands

```bash
# Repair migration issues automatically
poststack db repair

# Force repair (includes dangerous operations)
poststack db repair --force

# Repair specific issue types
poststack db repair --issue-type checksum_mismatch
```

### Validation Commands

```bash
# Enhanced validation
poststack db validate

# Validate specific aspects
poststack db validate --check-files --check-checksums --check-rollbacks
```

### Cleanup Commands

```bash
# Clean up migration artifacts
poststack db clean

# Clean specific types
poststack db clean --locks --failed --duplicates

# Skip confirmation prompts
poststack db clean --confirm
```

### Information Commands

```bash
# Get detailed migration information
poststack db migration-info

# Get specific migration details
poststack db migration-info 001

# Get information in JSON format
poststack db migration-info --format json
```

## Recovery Scenarios

### Unified Project Scenario

**Problem**: Migrations applied to database but not tracked in migration table.

**Symptoms**:
- Database schema exists with tables/functions
- Migration table shows fewer applied migrations than expected
- `poststack db migration-status` shows inconsistent state

**Solution**:
```bash
# Diagnose the issue
poststack db diagnose

# Recover from inconsistent state
poststack db recover

# Verify recovery
poststack db migration-status
poststack db validate
```

### Other Common Scenarios

#### Checksum Mismatches
```bash
# Detect checksum issues
poststack db diagnose --type checksum_mismatch

# Fix checksum issues
poststack db repair --issue-type checksum_mismatch
```

#### Stuck Migration Locks
```bash
# Detect stuck locks
poststack db diagnose --type stuck_lock

# Clear stuck locks
poststack db clean --locks
```

#### Missing Rollback Files
```bash
# Detect missing rollback files
poststack db validate --check-rollbacks

# Get warnings about missing rollbacks
poststack db diagnose --type rollback_missing
```

## Test Development

### Creating New Tests

1. **Choose the appropriate test file** based on functionality:
   - `test_migration_integrity.py` - Core migration functionality
   - `test_migration_rollback.py` - Rollback testing
   - `test_migration_recovery.py` - Recovery scenarios
   - `test_cli_commands.py` - CLI command testing

2. **Use provided fixtures**:
   ```python
   def test_new_scenario(self, migration_runner, sample_migrations, db_helper):
       # Test implementation
   ```

3. **Follow testing patterns**:
   ```python
   @pytest.mark.integration
   @pytest.mark.database
   class TestNewScenario:
       def test_specific_case(self, migration_runner, db_helper):
           # Setup
           # Execute
           # Verify
           # Cleanup (automatic)
   ```

### Test Data Creation

Create scenario-specific test data in `test_data/`:

```
test_data/
├── scenario_basic/
│   ├── 001_create_schema.sql
│   ├── 001_create_schema.rollback.sql
│   └── 002_add_tables.sql
└── scenario_complex/
    ├── 001_complex_migration.sql
    └── 001_complex_migration.rollback.sql
```

### Performance Testing

Add performance tests for scenarios involving large datasets:

```python
@pytest.mark.slow
def test_large_dataset_performance(self, migration_runner, db_helper):
    # Create large dataset
    # Measure performance
    # Assert performance criteria
```

## Best Practices

### Migration Development

1. **Always create rollback files** for every migration
2. **Test migrations in isolation** before applying to production
3. **Use descriptive migration names** that explain the purpose
4. **Keep migrations atomic** - one logical change per migration
5. **Test rollback procedures** before deploying

### Testing Practices

1. **Use integration tests** for end-to-end validation
2. **Test recovery scenarios** regularly
3. **Include performance testing** for large migrations
4. **Test CLI commands** to ensure user experience
5. **Use realistic test data** that matches production scenarios

### Recovery Practices

1. **Run diagnostics first** before attempting recovery
2. **Use dry-run mode** to preview recovery actions
3. **Take backups** before performing recovery operations
4. **Validate results** after recovery completion
5. **Document recovery procedures** for your team

## Troubleshooting

### Common Issues

#### Test Database Connection Issues
```bash
# Check if Docker is running
docker ps

# Check testcontainers logs
pytest tests/integration/test_migration_integrity.py::TestMigrationIntegrity::test_basic_test -v -s
```

#### Migration File Issues
```bash
# Check file permissions
ls -la migrations/

# Validate migration syntax
poststack db validate --check-files
```

#### Performance Issues
```bash
# Run performance tests
pytest tests/integration/ -m slow -v

# Check database performance
poststack db diagnose --format json | jq '.database_state'
```

### Debugging Tips

1. **Use verbose output** with `-v` flag
2. **Check logs** in `/data/logs/` directory
3. **Use dry-run mode** to preview operations
4. **Check database state** with diagnostic tools
5. **Use JSON output** for programmatic analysis

## API Reference

### MigrationDiagnostics

```python
from poststack.migration_diagnostics import MigrationDiagnostics

# Initialize diagnostics
diagnostics = MigrationDiagnostics(database_url, migrations_path)

# Run diagnostics
result = diagnostics.diagnose()

# Repair issues
repair_result = diagnostics.repair(result.issues, force=False)
```

### MigrationRunner

```python
from poststack.schema_migration import MigrationRunner

# Initialize runner
runner = MigrationRunner(database_url, migrations_path)

# Run migrations
migrate_result = runner.migrate()

# Rollback
rollback_result = runner.rollback(target_version="002")

# Recovery
recovery_result = runner.recover()
```

### CLI Testing

```python
from .cli_helpers import CLITestRunner

# Initialize CLI runner
cli_runner = CLITestRunner(database_url)

# Run CLI commands
result = cli_runner.run_command("migrate", ["--target", "002"])
```

## Contributing

### Development Setup

1. Clone the repository
2. Create a virtual environment
3. Install dependencies
4. Run tests to verify setup

### Adding New Features

1. Create tests first (TDD approach)
2. Implement the feature
3. Add CLI commands if needed
4. Update documentation
5. Run full test suite

### Submitting Changes

1. Ensure all tests pass
2. Add integration tests for new features
3. Update documentation
4. Include performance tests if applicable
5. Submit pull request with comprehensive description

## License

This framework is part of the poststack project and follows the same license terms.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Run diagnostics to understand the issue
3. Use the CLI tools for automated resolution
4. Consult the API reference for programmatic access
5. Review the test suites for examples