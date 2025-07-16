# CLI Command Reference

Quick reference guide for poststack enhanced migration CLI commands.

## Database Migration Commands

### Basic Migration Commands

```bash
# Check migration status
poststack db migration-status

# Run migrations to latest version
poststack db migrate

# Run migrations to specific version
poststack db migrate --target 003

# Rollback to specific version
poststack db rollback 002 --confirm

# Verify migration checksums
poststack db verify-migrations
```

### Project Migration Commands

```bash
# Run project-specific migrations
poststack db migrate-project

# Run project migrations from custom path
poststack db migrate-project --migrations-path ./custom/migrations

# Dry run project migrations
poststack db migrate-project --dry-run

# Force unlock stuck migrations
poststack db unlock-migrations --confirm
```

## Enhanced Diagnostic Commands

### Comprehensive Diagnostics

```bash
# Run full diagnostics
poststack db diagnose

# Get diagnostics in JSON format
poststack db diagnose --format json

# Filter by severity level
poststack db diagnose --severity high
poststack db diagnose --severity critical

# Filter by issue type
poststack db diagnose --type missing_tracking
poststack db diagnose --type checksum_mismatch
poststack db diagnose --type stuck_lock
```

### Available Issue Types

- `missing_tracking` - Migrations applied but not tracked
- `missing_file` - Migrations tracked but files missing
- `checksum_mismatch` - Migration files don't match recorded checksums
- `invalid_migration` - Invalid migration records
- `stuck_lock` - Migration system is locked
- `orphaned_schema` - Schemas exist without corresponding migrations
- `partial_migration` - Migrations that failed during application
- `duplicate_version` - Duplicate migration version numbers
- `corrupted_data` - Corrupted migration table data
- `rollback_missing` - Missing rollback files

### Severity Levels

- `low` - Minor issues, warnings
- `medium` - Issues that should be addressed
- `high` - Important issues that may cause problems
- `critical` - Severe issues that prevent migration system operation

## Recovery Commands

### Automated Recovery

```bash
# Recover from inconsistent states
poststack db recover

# Preview recovery actions (dry run)
poststack db recover --dry-run

# Force recovery (dangerous operations)
poststack db recover --force

# Recover with custom migrations path
poststack db recover --migrations-path ./custom/migrations
```

### Common Recovery Scenarios

```bash
# Unified project scenario (migrations applied but not tracked)
poststack db recover

# After manual database changes
poststack db recover --force

# Preview what would be recovered
poststack db recover --dry-run
```

## Repair Commands

### Automated Repairs

```bash
# Repair all auto-fixable issues
poststack db repair

# Force repair including dangerous operations
poststack db repair --force

# Repair specific issue types
poststack db repair --issue-type checksum_mismatch
poststack db repair --issue-type stuck_lock
poststack db repair --issue-type duplicate_version
```

### Safe vs. Dangerous Repairs

**Safe repairs** (no --force needed):
- Update checksums
- Clear stuck locks
- Remove invalid migration records
- Fix corrupted data

**Dangerous repairs** (require --force):
- Remove migration tracking
- Delete database objects
- Modify migration history

## Validation Commands

### Enhanced Validation

```bash
# Validate all aspects
poststack db validate

# Validate specific aspects
poststack db validate --check-files
poststack db validate --check-checksums
poststack db validate --check-rollbacks

# Validate with custom migrations path
poststack db validate --migrations-path ./custom/migrations
```

### Validation Checks

- `--check-files` - Verify migration files exist and are readable
- `--check-checksums` - Verify migration checksums match files
- `--check-rollbacks` - Verify rollback files exist for all migrations

## Cleanup Commands

### Migration Cleanup

```bash
# Clean all migration artifacts
poststack db clean

# Clean specific types
poststack db clean --locks
poststack db clean --failed
poststack db clean --duplicates

# Skip confirmation prompts
poststack db clean --confirm
```

### Cleanup Types

- `--locks` - Clear stuck migration locks
- `--failed` - Remove failed migration records
- `--duplicates` - Remove duplicate migration records

## Information Commands

### Migration Information

```bash
# List all migrations with details
poststack db migration-info

# Get specific migration details
poststack db migration-info 001

# Get information in JSON format
poststack db migration-info --format json
poststack db migration-info 001 --format json

# Use custom migrations path
poststack db migration-info --migrations-path ./custom/migrations
```

### Migration Details Shown

- Version number
- Migration name and description
- File path and rollback file
- Checksum information
- Application status
- File size
- Rollback availability

## Output Formats

### Text Format (Default)

Human-readable output with colors and formatting:
```
Migration Diagnostics Report
==================================================
Overall Status: ✅ PASS
Total Issues: 0

Database State:
  Migrations Applied: 3
  Schemas: 2
  Tables: 8
  Locked: No
```

### JSON Format

Structured output for programmatic use:
```json
{
  "success": true,
  "message": "Diagnostics completed. Found 0 issues.",
  "issues": [],
  "database_state": {
    "migration_count": 3,
    "is_locked": false,
    "schema_count": 2,
    "table_count": 8
  }
}
```

## Common Command Patterns

### Daily Operations

```bash
# Check migration status
poststack db migration-status

# Run any pending migrations
poststack db migrate

# Validate integrity
poststack db validate
```

### Troubleshooting Workflow

```bash
# 1. Diagnose issues
poststack db diagnose

# 2. Try automated recovery
poststack db recover --dry-run
poststack db recover

# 3. Repair remaining issues
poststack db repair

# 4. Validate final state
poststack db validate
```

### Emergency Recovery

```bash
# 1. Assess the situation
poststack db diagnose --severity high

# 2. Force recovery if needed
poststack db recover --force

# 3. Clean up artifacts
poststack db clean --confirm

# 4. Verify recovery
poststack db migration-status
poststack db validate
```

## Environment Variables

### Database Configuration

```bash
# Set database URL
export POSTSTACK_DATABASE_URL="postgresql://user:pass@localhost:5432/dbname"

# Or use auto-detection (recommended)
# poststack automatically detects database from running environments
```

### Logging Configuration

```bash
# Enable debug logging
export POSTSTACK_LOG_LEVEL=DEBUG

# Set custom log directory
export POSTSTACK_LOG_DIR=/path/to/logs
```

## Exit Codes

- `0` - Success
- `1` - General error
- `2` - Invalid arguments
- `3` - Database connection error
- `4` - Migration error
- `5` - Validation error

## Tips and Best Practices

### Performance Tips

1. Use `--dry-run` to preview operations
2. Run diagnostics before making changes
3. Use JSON output for scripting
4. Filter diagnostics by severity for focus

### Safety Tips

1. Always backup before recovery operations
2. Use `--dry-run` before `--force` operations
3. Run validation after repairs
4. Check migration status regularly

### Automation Tips

1. Use JSON output for parsing in scripts
2. Check exit codes for automation
3. Use severity filtering in monitoring
4. Set up regular diagnostic checks

## Examples

### Unified Project Recovery

```bash
# Typical unified project scenario
poststack db diagnose --type missing_tracking
poststack db recover --dry-run
poststack db recover
poststack db validate
```

### Checksum Mismatch Recovery

```bash
# When migration files have been modified
poststack db diagnose --type checksum_mismatch
poststack db repair --issue-type checksum_mismatch
poststack db verify-migrations
```

### Stuck Lock Recovery

```bash
# When migration system is locked
poststack db diagnose --type stuck_lock
poststack db clean --locks --confirm
poststack db migration-status
```

### JSON Output Processing

```bash
# Get critical issues in JSON for processing
poststack db diagnose --severity critical --format json | jq '.issues[] | .description'

# Check if system is locked
poststack db diagnose --format json | jq '.database_state.is_locked'

# Get pending migrations count
poststack db migration-info --format json | jq '.pending_count'
```