"""
Schema migration module for Poststack

Provides SQL-based database schema migration without external dependencies.
Designed specifically for PostgreSQL with support for change tracking and rollbacks.
"""

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extensions import connection as PostgresConnection

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Base exception for migration errors."""
    pass


class MigrationLockError(MigrationError):
    """Error acquiring migration lock."""
    pass


class MigrationChecksumError(MigrationError):
    """Error with migration checksum validation."""
    pass


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    success: bool
    version: Optional[str] = None
    message: str = ""
    execution_time_ms: Optional[int] = None
    error: Optional[Exception] = None


@dataclass
class MigrationStatus:
    """Current migration status."""
    current_version: Optional[str]
    applied_migrations: List['AppliedMigration']
    pending_migrations: List['Migration']
    is_locked: bool
    lock_info: Optional[Dict] = None


@dataclass
class AppliedMigration:
    """Record of an applied migration."""
    version: str
    description: Optional[str]
    applied_at: datetime
    execution_time_ms: Optional[int]
    checksum: str
    applied_by: Optional[str]


@dataclass
class VerificationResult:
    """Result of migration verification."""
    valid: bool
    errors: List[str]
    warnings: List[str]


class Migration:
    """Represents a single migration with its rollback."""
    
    def __init__(self, migration_file: Path, rollback_file: Optional[Path] = None):
        """Initialize migration from SQL files."""
        self.migration_file = migration_file
        self.rollback_file = rollback_file
        self._validate_files()
        
    def _validate_files(self):
        """Validate migration files exist and are readable."""
        if not self.migration_file.exists():
            raise MigrationError(f"Migration file not found: {self.migration_file}")
        
        if not self.migration_file.is_file():
            raise MigrationError(f"Not a file: {self.migration_file}")
            
        if self.rollback_file and not self.rollback_file.exists():
            logger.warning(f"Rollback file not found: {self.rollback_file}")
            self.rollback_file = None
    
    @property
    def version(self) -> str:
        """Get migration version from filename (e.g., '001')."""
        match = re.match(r'^(\d+)_', self.migration_file.name)
        if not match:
            raise MigrationError(f"Invalid migration filename: {self.migration_file.name}")
        return match.group(1)
    
    @property
    def name(self) -> str:
        """Get migration name from filename (e.g., 'initial_schema')."""
        match = re.match(r'^\d+_(.+)\.sql$', self.migration_file.name)
        if not match:
            raise MigrationError(f"Invalid migration filename: {self.migration_file.name}")
        return match.group(1)
    
    @property
    def checksum(self) -> str:
        """Calculate SHA-256 checksum of migration content."""
        content = self.get_sql()
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    @property
    def rollback_checksum(self) -> Optional[str]:
        """Calculate SHA-256 checksum of rollback content."""
        if not self.rollback_file:
            return None
        content = self.get_rollback_sql()
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def get_sql(self) -> str:
        """Read and return the forward migration SQL."""
        return self.migration_file.read_text(encoding='utf-8')
    
    def get_rollback_sql(self) -> Optional[str]:
        """Read and return the rollback SQL."""
        if not self.rollback_file:
            return None
        return self.rollback_file.read_text(encoding='utf-8')
    
    def get_description(self) -> str:
        """Extract description from SQL comment."""
        sql = self.get_sql()
        lines = sql.split('\n')
        for line in lines[:10]:  # Check first 10 lines
            if line.strip().startswith('-- Description:'):
                return line.replace('-- Description:', '').strip()
        return self.name.replace('_', ' ').title()
    
    def apply(self, conn: PostgresConnection) -> None:
        """Execute the migration SQL."""
        sql = self.get_sql()
        with conn.cursor() as cursor:
            # Execute the entire SQL block - psycopg2 can handle multiple statements
            cursor.execute(sql)
    
    def rollback(self, conn: PostgresConnection) -> None:
        """Execute the rollback SQL."""
        if not self.rollback_file:
            raise MigrationError(f"No rollback file for migration {self.version}")
        
        sql = self.get_rollback_sql()
        with conn.cursor() as cursor:
            # Execute the entire SQL block - psycopg2 can handle multiple statements
            cursor.execute(sql)


class MigrationRunner:
    """Executes and manages database migrations."""
    
    def __init__(self, database_url: str, migrations_path: str = "./migrations"):
        """Initialize migration runner with database connection."""
        self.database_url = database_url
        self.migrations_path = Path(migrations_path)
        self._ensure_migration_tables()
    
    def _get_connection(self) -> PostgresConnection:
        """Create a database connection."""
        conn = psycopg2.connect(self.database_url)
        # Use default transaction mode (autocommit=False)
        return conn
    
    def _ensure_migration_tables(self):
        """Ensure migration tracking tables exist."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # Create schema_migrations table in public schema
                cursor.execute("""
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
                """)
                
                # Create lock table in public schema
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS public.schema_migration_lock (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        locked BOOLEAN NOT NULL DEFAULT FALSE,
                        locked_at TIMESTAMP,
                        locked_by VARCHAR(255)
                    );
                """)
                
                # Ensure single row in lock table
                cursor.execute("""
                    INSERT INTO public.schema_migration_lock (id, locked)
                    VALUES (1, FALSE)
                    ON CONFLICT (id) DO NOTHING;
                """)
                
            conn.commit()
        finally:
            conn.close()
    
    def _acquire_lock(self, conn: PostgresConnection, timeout: int = 300) -> bool:
        """Acquire migration lock with timeout."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with conn.cursor() as cursor:
                # Try to acquire lock
                cursor.execute("""
                    UPDATE public.schema_migration_lock
                    SET locked = TRUE,
                        locked_at = CURRENT_TIMESTAMP,
                        locked_by = %s
                    WHERE id = 1 AND locked = FALSE;
                """, (os.environ.get('USER', 'unknown'),))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    return True
                
                # Check if lock is stale (older than 5 minutes)
                cursor.execute("""
                    UPDATE public.schema_migration_lock
                    SET locked = TRUE,
                        locked_at = CURRENT_TIMESTAMP,
                        locked_by = %s
                    WHERE id = 1 
                    AND locked = TRUE 
                    AND locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes';
                """, (os.environ.get('USER', 'unknown'),))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    logger.warning("Acquired stale migration lock")
                    return True
            
            # Wait before retry
            time.sleep(1)
        
        return False
    
    def _release_lock(self, conn: PostgresConnection):
        """Release migration lock."""
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE public.schema_migration_lock
                    SET locked = FALSE,
                        locked_at = NULL,
                        locked_by = NULL
                    WHERE id = 1;
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to release migration lock: {e}")
            # Don't raise - this is cleanup code
    
    def discover_migrations(self) -> List[Migration]:
        """Discover all migration SQL files in migrations directory."""
        if not self.migrations_path.exists():
            logger.warning(f"Migrations directory not found: {self.migrations_path}")
            return []
        
        migrations = []
        sql_files = sorted(self.migrations_path.glob("*.sql"))
        
        # Group migrations with their rollbacks
        migration_map = {}
        for sql_file in sql_files:
            if sql_file.name.endswith('.rollback.sql'):
                continue
                
            version_match = re.match(r'^(\d+)_', sql_file.name)
            if not version_match:
                logger.warning(f"Skipping invalid migration filename: {sql_file.name}")
                continue
            
            version = version_match.group(1)
            base_name = sql_file.stem
            rollback_file = self.migrations_path / f"{base_name}.rollback.sql"
            
            migration = Migration(
                migration_file=sql_file,
                rollback_file=rollback_file if rollback_file.exists() else None
            )
            migration_map[version] = migration
        
        # Sort by version
        for version in sorted(migration_map.keys()):
            migrations.append(migration_map[version])
        
        return migrations
    
    def _is_migration_applied(self, version: str) -> bool:
        """Check if a migration version has been applied."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM public.schema_migrations WHERE version = %s",
                        (version,)
                    )
                    return cursor.fetchone() is not None
        except Exception:
            return False
    
    def _validate_migration_state(self) -> List[str]:
        """Validate that the database state matches migration records.
        
        Returns a list of inconsistencies found.
        """
        inconsistencies = []
        
        try:
            applied_migrations = self.get_applied_migrations()
            
            # Check if migration tracking tables exist
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if poststack schema exists when migrations are applied
                    if applied_migrations:
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.schemata 
                                WHERE schema_name = 'poststack'
                            )
                        """)
                        schema_exists = cursor.fetchone()[0]
                        
                        if not schema_exists:
                            inconsistencies.append("Migration records indicate schema should exist, but poststack schema not found")
                    
                    # Check for duplicate migration records
                    cursor.execute("""
                        SELECT version, COUNT(*) 
                        FROM schema_migrations 
                        GROUP BY version 
                        HAVING COUNT(*) > 1
                    """)
                    duplicates = cursor.fetchall()
                    if duplicates:
                        for version, count in duplicates:
                            inconsistencies.append(f"Duplicate migration records found for version {version} ({count} records)")
                    
                    # Check for migration records with invalid checksums
                    all_migrations = {m.version: m for m in self.discover_migrations()}
                    for applied in applied_migrations:
                        if applied.version in all_migrations:
                            current_checksum = all_migrations[applied.version].checksum
                            if applied.checksum != current_checksum:
                                inconsistencies.append(f"Migration {applied.version} checksum mismatch: recorded={applied.checksum[:8]}..., current={current_checksum[:8]}...")
                        else:
                            inconsistencies.append(f"Migration {applied.version} is recorded as applied but migration file not found")
        
        except Exception as e:
            inconsistencies.append(f"Failed to validate migration state: {str(e)}")
        
        return inconsistencies
    
    def get_applied_migrations(self) -> List[AppliedMigration]:
        """Get list of migrations that have been applied."""
        applied = []
        
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT version, description, applied_at, 
                           execution_time_ms, checksum, applied_by
                    FROM public.schema_migrations
                    ORDER BY version;
                """)
                
                for row in cursor.fetchall():
                    applied.append(AppliedMigration(
                        version=row[0],
                        description=row[1],
                        applied_at=row[2],
                        execution_time_ms=row[3],
                        checksum=row[4],
                        applied_by=row[5]
                    ))
        
        return applied
    
    def get_pending_migrations(self) -> List[Migration]:
        """Get list of migrations that haven't been applied."""
        all_migrations = self.discover_migrations()
        applied_versions = {m.version for m in self.get_applied_migrations()}
        
        return [m for m in all_migrations if m.version not in applied_versions]
    
    def migrate(self, target_version: str = None) -> MigrationResult:
        """Apply all pending migrations up to target version."""
        pending = self.get_pending_migrations()
        
        if not pending:
            return MigrationResult(
                success=True,
                message="No pending migrations"
            )
        
        # Filter to target version if specified
        if target_version:
            pending = [m for m in pending if m.version <= target_version]
            if not pending:
                return MigrationResult(
                    success=True,
                    message=f"No migrations to apply up to version {target_version}"
                )
        
        conn = self._get_connection()
        try:
            # Acquire lock
            if not self._acquire_lock(conn):
                raise MigrationLockError("Could not acquire migration lock")
            
            applied_count = 0
            last_version = None
            
            for migration in pending:
                # Simple transaction: schema migration + ledger record
                start_time = time.time()
                logger.info(f"Applying migration {migration.version}: {migration.name}")
                
                try:
                    # 1. Run the schema migration
                    migration.apply(conn)
                    
                    # 2. Record success in migration ledger
                    execution_time_ms = int((time.time() - start_time) * 1000)
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO public.schema_migrations 
                            (version, description, checksum, execution_time_ms, 
                             applied_by, sql_up, sql_down)
                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """, (
                            migration.version,
                            migration.get_description(),
                            migration.checksum,
                            execution_time_ms,
                            os.environ.get('USER', 'unknown'),
                            migration.get_sql(),
                            migration.get_rollback_sql()
                        ))
                    
                    # 3. Commit everything together
                    conn.commit()
                    
                    applied_count += 1
                    last_version = migration.version
                    logger.info(f"Successfully applied migration {migration.version}: {migration.name}")
                    
                except Exception as e:
                    # 4. If error, rollback and report it
                    conn.rollback()
                    logger.error(f"Migration {migration.version} failed: {e}")
                    return MigrationResult(
                        success=False,
                        version=migration.version,
                        message=f"Migration {migration.version} failed: {str(e)}",
                        error=e
                    )
            
            return MigrationResult(
                success=True,
                version=last_version,
                message=f"Applied {applied_count} migration(s)"
            )
            
        finally:
            self._release_lock(conn)
            conn.close()
    
    def rollback(self, target_version: str) -> MigrationResult:
        """Rollback to a specific version."""
        applied = self.get_applied_migrations()
        
        if not applied:
            return MigrationResult(
                success=True,
                message="No migrations to rollback"
            )
        
        # Find migrations to rollback
        to_rollback = [m for m in reversed(applied) if m.version > target_version]
        
        if not to_rollback:
            return MigrationResult(
                success=True,
                message=f"Already at version {target_version} or earlier"
            )
        
        # Get migration objects
        all_migrations = {m.version: m for m in self.discover_migrations()}
        
        conn = self._get_connection()
        try:
            # Acquire lock
            if not self._acquire_lock(conn):
                raise MigrationLockError("Could not acquire migration lock")
            
            rolled_back = 0
            
            for applied_migration in to_rollback:
                migration = all_migrations.get(applied_migration.version)
                if not migration:
                    raise MigrationError(
                        f"Migration file not found for version {applied_migration.version}"
                    )
                
                if not migration.rollback_file:
                    raise MigrationError(
                        f"No rollback file for migration {applied_migration.version}"
                    )
                
                try:
                    logger.info(f"Rolling back migration {migration.version}: {migration.name}")
                    
                    # Execute rollback SQL
                    migration.rollback(conn)
                    
                    # Remove migration record in same transaction
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            DELETE FROM public.schema_migrations
                            WHERE version = %s;
                        """, (migration.version,))
                    
                    # Commit the entire rollback (schema changes + tracking removal)
                    conn.commit()
                    rolled_back += 1
                    logger.info(f"Successfully rolled back migration {migration.version}: {migration.name}")
                    
                except Exception as e:
                    # Rollback the entire rollback transaction
                    conn.rollback()
                    logger.error(f"Failed to rollback migration {migration.version}: {e}")
                    
                    # Verify the migration is still properly recorded
                    if not self._is_migration_applied(migration.version):
                        logger.error(f"Migration {migration.version} record was lost during failed rollback - database may be in inconsistent state")
                        return MigrationResult(
                            success=False,
                            version=migration.version,
                            message=f"Rollback of {migration.version} failed and database may be in inconsistent state: {str(e)}",
                            error=e
                        )
                    
                    return MigrationResult(
                        success=False,
                        version=migration.version,
                        message=f"Rollback of {migration.version} failed: {str(e)}",
                        error=e
                    )
            
            return MigrationResult(
                success=True,
                version=target_version,
                message=f"Rolled back {rolled_back} migration(s)"
            )
            
        finally:
            self._release_lock(conn)
            conn.close()
    
    def status(self) -> MigrationStatus:
        """Get current migration status."""
        applied = self.get_applied_migrations()
        pending = self.get_pending_migrations()
        
        # Check lock status
        is_locked = False
        lock_info = None
        
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT locked, locked_at, locked_by
                    FROM public.schema_migration_lock
                    WHERE id = 1;
                """)
                row = cursor.fetchone()
                if row and row[0]:
                    is_locked = True
                    lock_info = {
                        'locked_at': row[1],
                        'locked_by': row[2]
                    }
        
        current_version = applied[-1].version if applied else None
        
        return MigrationStatus(
            current_version=current_version,
            applied_migrations=applied,
            pending_migrations=pending,
            is_locked=is_locked,
            lock_info=lock_info
        )
    
    def verify(self) -> VerificationResult:
        """Verify all applied migrations match their checksums and database state is consistent."""
        errors = []
        warnings = []
        
        # Validate migration state consistency
        state_inconsistencies = self._validate_migration_state()
        errors.extend(state_inconsistencies)
        
        applied = self.get_applied_migrations()
        all_migrations = {m.version: m for m in self.discover_migrations()}
        
        for applied_migration in applied:
            migration = all_migrations.get(applied_migration.version)
            
            if not migration:
                warnings.append(
                    f"Migration file not found for applied version {applied_migration.version}"
                )
                continue
            
            # Verify checksum
            current_checksum = migration.checksum
            if current_checksum != applied_migration.checksum:
                errors.append(
                    f"Checksum mismatch for migration {applied_migration.version}: "
                    f"expected {applied_migration.checksum}, got {current_checksum}"
                )
        
        return VerificationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def force_unlock(self) -> bool:
        """Force release the migration lock."""
        with self._get_connection() as conn:
            self._release_lock(conn)
            logger.warning("Forcefully released migration lock")
            return True