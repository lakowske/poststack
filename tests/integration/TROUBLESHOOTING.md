# Migration Troubleshooting Guide

This guide provides solutions for common migration issues and error scenarios.

## Quick Problem Resolution

### "My migrations aren't tracked in the database"

**Symptoms:**
- Database schema exists with tables/functions
- `poststack db migration-status` shows fewer migrations than expected
- Tables exist but migration table is empty or incomplete

**Diagnosis:**
```bash
poststack db diagnose --type missing_tracking
```

**Solution:**
```bash
# Preview recovery
poststack db recover --dry-run

# Perform recovery
poststack db recover

# Verify fix
poststack db migration-status
poststack db validate
```

### "Migration checksums don't match"

**Symptoms:**
- `poststack db verify-migrations` fails
- Error: "checksum mismatch"
- Modifications were made to migration files

**Diagnosis:**
```bash
poststack db diagnose --type checksum_mismatch
```

**Solution:**
```bash
# Repair checksum mismatches
poststack db repair --issue-type checksum_mismatch

# Or force update all checksums
poststack db repair --force

# Verify fix
poststack db verify-migrations
```

### "Migration system is locked"

**Symptoms:**
- `poststack db migrate` hangs or fails
- Error: "migration system is locked"
- Previous migration process was interrupted

**Diagnosis:**
```bash
poststack db diagnose --type stuck_lock
```

**Solution:**
```bash
# Clear stuck lock
poststack db clean --locks --confirm

# Or use legacy command
poststack db unlock-migrations --confirm

# Verify fix
poststack db migration-status
```

### "Duplicate migration versions"

**Symptoms:**
- Multiple entries for same migration version
- Inconsistent migration history
- Errors during migration status checks

**Diagnosis:**
```bash
poststack db diagnose --type duplicate_version
```

**Solution:**
```bash
# Repair duplicate versions
poststack db repair --issue-type duplicate_version

# Or clean up duplicates
poststack db clean --duplicates --confirm

# Verify fix
poststack db migration-status
```

## Detailed Error Scenarios

### Scenario 1: Unified Project Migration State

**Context:** This is the original scenario that led to the creation of this framework.

**Problem:** Migrations were applied manually to the database, but the migration tracking system wasn't updated.

**Symptoms:**
```bash
$ poststack db migration-status
Current version: 001
Applied migrations: 1
Pending migrations: 3

# But database actually has all objects from migrations 002, 003, 004
```

**Diagnosis:**
```bash
$ poststack db diagnose
Migration Diagnostics Report
==================================================
Overall Status: ❌ FAIL
Total Issues: 3

Issue Breakdown:
  🟠 HIGH: 3

Detailed Issues:

🟠 MISSING_TRACKING: Migration 002 appears to be applied but not tracked
   Version: 002
   Suggested Fix: Use recovery mode to track this migration
   Auto-fixable: Yes

🟠 MISSING_TRACKING: Migration 003 appears to be applied but not tracked
   Version: 003
   Suggested Fix: Use recovery mode to track this migration
   Auto-fixable: Yes

🟠 MISSING_TRACKING: Migration 004 appears to be applied but not tracked
   Version: 004
   Suggested Fix: Use recovery mode to track this migration
   Auto-fixable: Yes
```

**Solution:**
```bash
# Step 1: Preview recovery
$ poststack db recover --dry-run
🔍 Dry run - analyzing recovery options...
Would recover 3 issue(s):
  - Migration 002 appears to be applied but not tracked
    Fix: Use recovery mode to track this migration
  - Migration 003 appears to be applied but not tracked
    Fix: Use recovery mode to track this migration
  - Migration 004 appears to be applied but not tracked
    Fix: Use recovery mode to track this migration

# Step 2: Perform recovery
$ poststack db recover
🔄 Starting migration recovery...
✅ Recovery completed successfully!
   Added tracking for migrations 002, 003, 004

# Step 3: Verify fix
$ poststack db migration-status
Current version: 004
Applied migrations: 4
Pending migrations: 0
✅ Database is up to date!
```

### Scenario 2: File Modifications After Deployment

**Context:** Migration files were modified after being applied to the database.

**Problem:** Checksums no longer match, causing verification to fail.

**Symptoms:**
```bash
$ poststack db verify-migrations
❌ Migration verification failed!
   Error: Migration 002 checksum mismatch: expected abc123, got def456
```

**Diagnosis:**
```bash
$ poststack db diagnose --type checksum_mismatch
🟠 CHECKSUM_MISMATCH: Migration 002 has checksum mismatch
   Version: 002
   Details: {'tracked_checksum': 'abc123', 'file_checksum': 'def456'}
   Suggested Fix: Update checksum in database or restore original file
   Auto-fixable: Yes
```

**Solution Options:**

**Option 1: Update checksums (if file changes are intentional)**
```bash
# Update checksums to match current files
poststack db repair --issue-type checksum_mismatch

# Verify fix
poststack db verify-migrations
```

**Option 2: Restore original files (if changes were accidental)**
```bash
# First, restore original files from version control
git checkout HEAD -- migrations/002_migration_name.sql

# Then verify checksums now match
poststack db verify-migrations
```

### Scenario 3: Partial Migration Failure

**Context:** A migration failed partway through execution.

**Problem:** Migration is marked as failed but may have partially applied changes.

**Symptoms:**
```bash
$ poststack db migration-status
Current version: 001
Applied migrations: 1
Pending migrations: 2

# Migration 002 is in failed state
```

**Diagnosis:**
```bash
$ poststack db diagnose --type partial_migration
🟠 PARTIAL_MIGRATION: Migration 002 was not successfully applied
   Version: 002
   Details: {'version': '002', 'description': 'add_user_table'}
   Suggested Fix: Retry migration or clean up partial state
   Auto-fixable: Yes
```

**Solution:**
```bash
# Option 1: Clean up and retry
poststack db repair --issue-type partial_migration

# Option 2: Force cleanup and manual fix
poststack db repair --force
# Then manually fix any partial state
# Then re-run migration
poststack db migrate
```

### Scenario 4: Missing Rollback Files

**Context:** Some migrations don't have rollback files.

**Problem:** Cannot perform rollback operations.

**Symptoms:**
```bash
$ poststack db rollback 001
❌ Rollback failed: Migration 002 has no rollback file
```

**Diagnosis:**
```bash
$ poststack db validate --check-rollbacks
⚠️  Validation warnings:
  - Missing rollback files for migrations: 002, 003

$ poststack db diagnose --type rollback_missing
🟢 ROLLBACK_MISSING: Migration 002 has no rollback file
   Version: 002
   Suggested Fix: Create rollback file for this migration
   Auto-fixable: No
```

**Solution:**
```bash
# Create rollback files manually
# For migration 002_add_user_table.sql, create 002_add_user_table.rollback.sql

# Example rollback file content:
echo "DROP TABLE IF EXISTS users;" > migrations/002_add_user_table.rollback.sql

# Verify rollback files
poststack db validate --check-rollbacks
```

### Scenario 5: Orphaned Database Objects

**Context:** Database has schemas/tables that don't correspond to any migration.

**Problem:** Database state doesn't match migration history.

**Symptoms:**
```bash
$ poststack db diagnose --type orphaned_schema
🟡 ORPHANED_SCHEMA: Schema temp_schema exists but has no corresponding migration
   Details: {'schema': 'temp_schema'}
   Suggested Fix: Create migration for existing schema or remove it
   Auto-fixable: No
```

**Solution Options:**

**Option 1: Create migration for existing objects**
```bash
# Create new migration to formalize existing objects
echo "-- This migration formalizes existing temp_schema
CREATE SCHEMA IF NOT EXISTS temp_schema;
-- Add other existing objects..." > migrations/005_formalize_temp_schema.sql

# Run migration
poststack db migrate
```

**Option 2: Remove orphaned objects**
```bash
# Connect to database and remove orphaned objects
poststack db shell -c "DROP SCHEMA IF EXISTS temp_schema CASCADE;"

# Verify cleanup
poststack db diagnose --type orphaned_schema
```

## Performance Issues

### Slow Migration Execution

**Symptoms:**
- Migrations take extremely long to execute
- Database becomes unresponsive during migration
- Timeout errors during migration

**Diagnosis:**
```bash
# Check migration performance
poststack db diagnose --format json | jq '.database_state'

# Run performance tests
pytest tests/integration/test_migration_integrity.py::TestMigrationIntegrity::test_migration_performance -v
```

**Solutions:**

1. **Optimize Migration SQL:**
   ```sql
   -- Instead of:
   ALTER TABLE large_table ADD COLUMN new_col VARCHAR(255);
   
   -- Use:
   ALTER TABLE large_table ADD COLUMN new_col VARCHAR(255) DEFAULT '';
   -- Then update in batches
   ```

2. **Use Migration Batching:**
   ```sql
   -- Break large operations into smaller batches
   UPDATE large_table SET new_col = 'value' WHERE id BETWEEN 1 AND 10000;
   UPDATE large_table SET new_col = 'value' WHERE id BETWEEN 10001 AND 20000;
   ```

3. **Index Management:**
   ```sql
   -- Drop indexes before large operations
   DROP INDEX IF EXISTS idx_large_table_column;
   
   -- Perform operations
   UPDATE large_table SET column = 'new_value';
   
   -- Recreate indexes
   CREATE INDEX idx_large_table_column ON large_table(column);
   ```

### Memory Issues During Migration

**Symptoms:**
- Out of memory errors
- Database connection failures
- System becomes unresponsive

**Solutions:**

1. **Increase Database Memory:**
   ```bash
   # For PostgreSQL containers
   podman run --memory=4g poststack-postgres
   ```

2. **Use Streaming Operations:**
   ```sql
   -- Instead of loading all data at once
   UPDATE large_table SET column = function(column);
   
   -- Use cursor-based updates
   DECLARE cursor_name CURSOR FOR SELECT id FROM large_table;
   ```

## Testing Issues

### Test Database Connection Problems

**Symptoms:**
- Tests fail with connection errors
- "Database not available" errors
- Timeout during test setup

**Diagnosis:**
```bash
# Check Docker
docker ps

# Check testcontainers
pytest tests/integration/test_migration_integrity.py::TestMigrationIntegrity::test_basic_functionality -v -s
```

**Solutions:**

1. **Docker Issues:**
   ```bash
   # Restart Docker
   sudo systemctl restart docker
   
   # Clean up containers
   docker system prune -f
   ```

2. **Port Conflicts:**
   ```bash
   # Check port usage
   netstat -tulpn | grep 5432
   
   # Kill processes using the port
   sudo lsof -ti:5432 | xargs kill -9
   ```

3. **Permission Issues:**
   ```bash
   # Add user to docker group
   sudo usermod -aG docker $USER
   
   # Restart session
   newgrp docker
   ```

### Test Performance Issues

**Symptoms:**
- Tests run very slowly
- Tests timeout
- High CPU/memory usage during tests

**Solutions:**

1. **Run Tests in Parallel:**
   ```bash
   # Install pytest-xdist
   pip install pytest-xdist
   
   # Run tests in parallel
   pytest tests/integration/ -n auto
   ```

2. **Skip Slow Tests:**
   ```bash
   # Skip slow tests for development
   pytest tests/integration/ -m "not slow"
   ```

3. **Use Test Fixtures Efficiently:**
   ```python
   # Use session-scoped fixtures for expensive setup
   @pytest.fixture(scope="session")
   def expensive_setup():
       # Setup code
   ```

## Emergency Procedures

### Complete Migration System Reset

**Use only in extreme cases when all else fails:**

```bash
# 1. Backup database
poststack db backup --output emergency_backup.sql

# 2. Drop migration tracking
poststack db shell -c "DROP TABLE IF EXISTS schema_migrations CASCADE;"
poststack db shell -c "DROP TABLE IF EXISTS schema_migrations_lock CASCADE;"

# 3. Reinitialize migration system
poststack db create-schema --force

# 4. Recover state
poststack db recover --force

# 5. Validate recovery
poststack db validate
poststack db migration-status
```

### Database Corruption Recovery

**For severely corrupted migration state:**

```bash
# 1. Backup current state
poststack db backup --output corrupted_backup.sql

# 2. Export schema without migration tables
pg_dump --schema-only --exclude-table=schema_migrations* db_name > schema_backup.sql

# 3. Drop and recreate database
poststack db shell -c "DROP SCHEMA IF EXISTS poststack CASCADE;"

# 4. Restore schema
poststack db shell -c "$(cat schema_backup.sql)"

# 5. Rebuild migration tracking
poststack db create-schema --force
poststack db recover --force
```

## Prevention Best Practices

### Daily Practices

1. **Regular Diagnostics:**
   ```bash
   # Add to daily checks
   poststack db diagnose --severity high
   ```

2. **Validation Checks:**
   ```bash
   # Run after any migration changes
   poststack db validate
   ```

3. **Backup Before Changes:**
   ```bash
   # Always backup before migrations
   poststack db backup
   ```

### Development Practices

1. **Test Migrations Locally:**
   ```bash
   # Test on local copy before production
   poststack db migrate --dry-run
   ```

2. **Create Rollback Files:**
   ```bash
   # Always create rollback files
   poststack db validate --check-rollbacks
   ```

3. **Use Version Control:**
   ```bash
   # Track all migration files
   git add migrations/
   git commit -m "Add migration 005: user profiles"
   ```

## Getting Help

### Gathering Diagnostic Information

```bash
# Create comprehensive diagnostic report
poststack db diagnose --format json > diagnostic_report.json

# Get system information
poststack db migration-info --format json > migration_info.json

# Get migration status
poststack db migration-status > migration_status.txt

# Check validation
poststack db validate > validation_report.txt
```

### Support Information

Include this information when requesting help:

1. **Diagnostic Report:**
   ```bash
   poststack db diagnose --format json
   ```

2. **Migration Status:**
   ```bash
   poststack db migration-status
   ```

3. **Environment Information:**
   ```bash
   poststack version
   python --version
   psql --version
   ```

4. **Error Messages:**
   - Full error output
   - Stack traces
   - Log files from `/data/logs/`

5. **Migration Files:**
   - Content of problematic migration files
   - Migration directory structure
   - Rollback file availability