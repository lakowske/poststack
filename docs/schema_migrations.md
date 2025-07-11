# Poststack Schema Migration System

## Overview

This document specifies the design and implementation of a SQL-based schema migration system for Poststack. The system is designed specifically for PostgreSQL, providing simple change tracking and rollback capabilities with direct SQL execution.

## Goals

1. **Simplicity** - Plain SQL files that can be understood and applied by any PostgreSQL tool
2. **PostgreSQL-native** - Direct SQL execution without cross-platform abstractions
3. **Lightweight** - No container or JVM overhead
4. **Traceable** - Full history of applied migrations with checksums
5. **Reversible** - Support for rolling back changes via separate rollback files
6. **Transactional** - Each migration runs in a database transaction
7. **Transparent** - No surprises, just SQL files that clearly show what will be executed

## Architecture

### Core Components

1. **Migration Engine** (`src/poststack/schema_migration.py`)
   - `Migration` class - Represents a single migration and its rollback
   - `MigrationRunner` class - Executes migrations and manages tracking
   - Migration discovery and validation logic

2. **Migration Files** (`./migrations/`)
   - Plain SQL files containing migration statements
   - Coordinated numbering for migrations and rollbacks
   - Example: `001_initial_schema.sql` and `001_initial_schema.rollback.sql`

3. **Tracking Database** (public schema)
   - `public.schema_migrations` table - Records applied migrations
   - `public.schema_migration_lock` table - Prevents concurrent migrations

### Database Schema

```sql
-- Migration tracking table (in public schema)
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    execution_time_ms INTEGER,
    checksum VARCHAR(64) NOT NULL,
    applied_by VARCHAR(255),
    sql_up TEXT,
    sql_down TEXT
);

-- Lock table to prevent concurrent migrations (in public schema)
CREATE TABLE IF NOT EXISTS public.schema_migration_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    locked_at TIMESTAMP,
    locked_by VARCHAR(255)
);

-- Single row in lock table
INSERT INTO public.schema_migration_lock (id, locked) 
VALUES (1, FALSE) 
ON CONFLICT (id) DO NOTHING;
```

## Migration File Format

### Naming Convention

Migrations use a numbered naming convention with descriptive names:

```text
NNN_description.sql           # Forward migration
NNN_description.rollback.sql  # Rollback migration
```

Examples:

- `001_initial_schema.sql` and `001_initial_schema.rollback.sql`
- `002_add_indexes.sql` and `002_add_indexes.rollback.sql`
- `003_add_audit_tables.sql` and `003_add_audit_tables.rollback.sql`

### File Structure

Each migration consists of two plain SQL files:

#### Forward Migration (`001_initial_schema.sql`)

```sql
-- Migration: Initial schema creation
-- Author: poststack
-- Date: 2025-01-07
-- Description: Create initial poststack schema and core tables

-- Create schema
CREATE SCHEMA IF NOT EXISTS poststack;

-- Create system_info table
CREATE TABLE poststack.system_info (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create services table
CREATE TABLE poststack.services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'stopped',
    config JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add initial data
INSERT INTO poststack.system_info (key, value) 
VALUES ('schema_version', '1.0.0');
```

#### Rollback Migration (`001_initial_schema.rollback.sql`)

```sql
-- Rollback: Initial schema creation
-- Author: poststack
-- Date: 2025-01-07
-- Description: Remove poststack schema and all related objects

DROP SCHEMA IF EXISTS poststack CASCADE;
```

### Migration Metadata

Since SQL files cannot contain structured metadata, a companion metadata file can be created:

```json
// 001_initial_schema.json (optional)
{
    "description": "Create initial poststack schema",
    "author": "poststack",
    "date": "2025-01-07",
    "breaking_change": false,
    "requires_maintenance": false,
    "estimated_duration": "< 1 second"
}
```

## API Design

### MigrationRunner Class

```python
class MigrationRunner:
    def __init__(self, database_url: str, migrations_path: str = "./migrations"):
        """Initialize migration runner with database connection."""
        
    def discover_migrations(self) -> List[Migration]:
        """Discover all migration SQL files in migrations directory."""
        
    def get_pending_migrations(self) -> List[Migration]:
        """Get list of migrations that haven't been applied."""
        
    def get_applied_migrations(self) -> List[AppliedMigration]:
        """Get list of migrations that have been applied."""
        
    def migrate(self, target_version: str = None) -> MigrationResult:
        """Apply all pending migrations up to target version."""
        
    def rollback(self, target_version: str) -> MigrationResult:
        """Rollback to a specific version."""
        
    def status(self) -> MigrationStatus:
        """Get current migration status."""
        
    def verify(self) -> VerificationResult:
        """Verify all applied migrations match their checksums."""
```

### Migration Class

```python
class Migration:
    def __init__(self, migration_file: Path, rollback_file: Path):
        """Load migration from SQL files."""
        
    @property
    def version(self) -> str:
        """Get migration version from filename (e.g., '001')."""
        
    @property
    def name(self) -> str:
        """Get migration name from filename (e.g., 'initial_schema')."""
        
    @property
    def checksum(self) -> str:
        """Calculate SHA-256 checksum of migration content."""
        
    @property
    def rollback_checksum(self) -> str:
        """Calculate SHA-256 checksum of rollback content."""
        
    def get_sql(self) -> str:
        """Read and return the forward migration SQL."""
        
    def get_rollback_sql(self) -> str:
        """Read and return the rollback SQL."""
        
    def apply(self, connection) -> None:
        """Execute the migration SQL."""
        
    def rollback(self, connection) -> None:
        """Execute the rollback SQL."""
```

## Migration Workflow

### Creating a Migration

1. Create migration files manually in `./migrations/` directory:
   - `NNN_description.sql` (forward migration)
   - `NNN_description.rollback.sql` (rollback migration)

2. Edit the SQL files to add your schema changes

3. Verify migration syntax and run tests

### Applying Migrations

1. Check current status:

   ```bash
   poststack database migration-status
   ```

2. Initialize schema (applies all migrations):

   ```bash
   poststack database create-schema
   ```

3. Apply pending migrations to existing schema:

   ```bash
   poststack database migrate
   ```

4. Apply migrations up to specific version:

   ```bash
   poststack database migrate --target 002
   ```

### Rolling Back

1. Rollback to specific version:

   ```bash
   poststack database rollback 001 --confirm
   ```

### Development Workflow

1. Drop and recreate schema for clean state:

   ```bash
   poststack database drop-schema --confirm
   poststack database create-schema
   ```

2. Verify schema structure:

   ```bash
   poststack database show-schema
   ```

## Error Handling

### Transaction Management

- Each migration runs in its own transaction
- On error, the transaction is rolled back
- Migration is not recorded in `schema_migrations` table
- Lock is released

### Checksum Validation

- Before applying a migration, verify no applied migration has changed
- If checksum mismatch detected, abort with error
- Provide option to force update with `--force` flag

### Lock Management

- Acquire lock before any migration operation
- Release lock on completion or error
- Timeout after 5 minutes to prevent stuck locks
- CLI command to manually release lock if needed

## CLI Integration

### Commands

```bash
# Database management commands (actual implementation)
poststack database create-schema        # Initialize schema with all migrations
poststack database drop-schema          # Drop schema and clear migration tracking  
poststack database migrate              # Apply pending migrations
poststack database migration-status     # Show migration status
poststack database show-schema          # Show current schema information
poststack database rollback <version>   # Rollback to specific version
poststack database verify-migrations    # Verify migration checksums
poststack database unlock-migrations    # Force unlock migration system

# Options
--target VERSION    # Migrate to specific version
--confirm          # Skip confirmation prompts
--force            # Force schema creation (drops existing)
```

### Output Examples

```bash
$ poststack database migration-status
📊 Migration Status
========================================
Current version: 003
Applied migrations: 3
Pending migrations: 0

Applied migrations:
  ✅ 001: Create poststack schema and core tables
  ✅ 002: Add indexes for commonly queried columns
  ✅ 003: Insert initial system information and default service configurations

✅ Database is up to date!
```

## Integration with SchemaManager

The existing `SchemaManager` class will be updated to use the new migration system while maintaining the same public API:

```python
class SchemaManager:
    def __init__(self, config: PoststackConfig):
        self.config = config
        self.migration_runner = MigrationRunner(
            database_url=config.database_url,
            migrations_path=config.migrations_path
        )
    
    def initialize_schema(self, database_url: str) -> RuntimeResult:
        """Initialize schema by running all migrations."""
        result = self.migration_runner.migrate()
        return self._convert_to_runtime_result(result)
    
    def update_schema(self, database_url: str) -> RuntimeResult:
        """Update schema to latest version."""
        result = self.migration_runner.migrate()
        return self._convert_to_runtime_result(result)
    
    def verify_schema(self, database_url: str) -> HealthCheckResult:
        """Verify schema integrity."""
        result = self.migration_runner.verify()
        return self._convert_to_health_check_result(result)
```

## Migration Examples

### Example 1: Creating Tables

#### `001_initial_schema.sql`

```sql
-- Migration: Initial schema creation
-- Author: poststack
-- Date: 2025-01-07
-- Description: Create poststack schema and core tables

-- Create schema
CREATE SCHEMA IF NOT EXISTS poststack;

-- Create system_info table
CREATE TABLE poststack.system_info (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create services table
CREATE TABLE poststack.services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'stopped',
    config JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert initial data
INSERT INTO poststack.system_info (key, value) 
VALUES ('schema_version', '1.0.0');
```

#### `001_initial_schema.rollback.sql`

```sql
-- Rollback: Initial schema creation
-- Author: poststack
-- Date: 2025-01-07

DROP SCHEMA IF EXISTS poststack CASCADE;
```

### Example 2: Adding Indexes

#### `002_add_indexes.sql`

```sql
-- Migration: Add performance indexes
-- Author: poststack
-- Date: 2025-01-07
-- Description: Add indexes for commonly queried columns

CREATE INDEX idx_services_type ON poststack.services(type);
CREATE INDEX idx_services_status ON poststack.services(status);
CREATE INDEX idx_system_info_key ON poststack.system_info(key);
```

#### `002_add_indexes.rollback.sql`

```sql
-- Rollback: Remove performance indexes
-- Author: poststack
-- Date: 2025-01-07

DROP INDEX IF EXISTS poststack.idx_services_type;
DROP INDEX IF EXISTS poststack.idx_services_status;
DROP INDEX IF EXISTS poststack.idx_system_info_key;
```

### Example 3: Data Migration

#### `003_add_user_status.sql`

```sql
-- Migration: Add user status tracking
-- Author: poststack
-- Date: 2025-01-08
-- Description: Add status column and migrate existing data

-- Add new column
ALTER TABLE poststack.users 
ADD COLUMN status VARCHAR(50) DEFAULT 'active';

-- Migrate existing data (assume early users are active)
UPDATE poststack.users 
SET status = 'active' 
WHERE created_at < '2025-01-01';

-- Add index for queries
CREATE INDEX idx_users_status ON poststack.users(status);
```

#### `003_add_user_status.rollback.sql`

```sql
-- Rollback: Remove user status
-- Author: poststack
-- Date: 2025-01-08

-- Drop index first
DROP INDEX IF EXISTS poststack.idx_users_status;

-- Remove column
ALTER TABLE poststack.users 
DROP COLUMN status;
```

## Features

### Core Capabilities

- Pure SQL migration files
- Separate rollback files with clear naming
- Checksum validation for migration integrity
- Direct execution without interpretation layer
- Fast execution with minimal overhead
- Can be applied manually with psql if needed
- Atomic transaction handling
- Migration locking to prevent conflicts

## Security Considerations

1. **SQL Injection** - Migration files are trusted code, not user input
2. **Access Control** - Migrations require database admin privileges
3. **Audit Trail** - All migrations logged with timestamp and user
4. **Checksum Validation** - Prevents tampering with applied migrations
5. **Lock Mechanism** - Prevents concurrent schema modifications

## Future Enhancements

1. **Migration Squashing** - Combine old migrations into single file
2. **Schema Diff Tool** - Generate migrations from database changes
3. **Test Migrations** - Dry-run migrations against test database
4. **Migration Hooks** - Pre/post migration callbacks
5. **Schema Versioning** - Tag schema versions for releases

## Implementation Experience

### What Was Actually Built

The implementation followed the core design but with some important differences from the original plan:

1. **Migration Files Created**:
   - `001_initial_schema.sql` - Creates poststack schema and core tables
   - `002_add_indexes.sql` - Adds performance indexes
   - `003_initial_data.sql` - Inserts initial system configuration

2. **Integration Points**:
   - Integrated with existing `SchemaManager` class in `schema_management.py`
   - CLI commands added to `database.py` module
   - Auto-detection of PostgreSQL containers for database URL

3. **Key Design Decisions**:
   - Migration tracking tables placed in `public` schema (not poststack schema)
   - Simple transaction pattern: run migration → record tracking → commit
   - Drop-schema command clears migration tracking for clean state

### Lessons Learned

#### 1. Schema Placement for Tracking Tables

**Issue**: Originally planned to use the application schema for tracking, but this caused circular dependencies.
**Solution**: Placed `schema_migrations` and `schema_migration_lock` tables in `public` schema.
**Lesson**: Infrastructure tables should be separate from application schema to avoid bootstrap dependencies.

#### 2. Transaction Handling Complexity

**Issue**: Initial implementation tried complex rollback scenarios that caused inconsistent state.
**Solution**: Simplified to basic pattern: attempt migration → record result → commit or rollback everything.
**Lesson**: Start with simple transaction patterns and add complexity only when needed.

#### 3. Drop/Recreate Workflow

**Issue**: `drop-schema` only dropped application schema but left migration tracking, causing confusion.
**Solution**: Added migration tracking cleanup to `drop-schema` command.
**Lesson**: Full cleanup operations should clear all related state, not just obvious artifacts.

#### 4. Error Handling and State Validation

**Issue**: Migration failures could leave database in inconsistent state with partial tracking records.
**Solution**: Added validation methods and enhanced error detection.
**Lesson**: Migration systems need robust state validation to detect and report inconsistencies.

#### 5. CLI Command Structure

**Issue**: Originally designed separate `schema` command group, but integrated with existing `database` commands.
**Solution**: Used `poststack database` commands for consistency with existing codebase.
**Lesson**: Follow existing CLI patterns rather than creating new command hierarchies.

### Actual Implementation Timeline

- **Day 1**: Core migration engine and file structure
- **Day 2**: CLI integration and basic testing  
- **Day 3**: Transaction handling fixes and error scenarios
- **Day 4**: Schema tracking issues and cleanup workflow
- **Day 5**: Documentation cleanup and Liquibase removal

**Total time**: 5 days (vs. estimated 6-9 days)

### Future Improvements Based on Experience

1. **Migration Generation**: Add `poststack database generate-migration <name>` command
2. **Dry Run Support**: Add `--dry-run` flag to show what migrations would do
3. **Migration Validation**: Add pre-commit hooks to validate migration syntax
4. **Better Error Messages**: Enhance error reporting with suggestions for common issues
5. **Backup Integration**: Automatically backup before major migrations
