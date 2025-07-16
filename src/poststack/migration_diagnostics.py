"""
Migration diagnostic and repair tools for poststack.

Provides comprehensive diagnostic capabilities to detect and repair various
migration-related issues, including inconsistent states, missing files,
corrupted data, and other edge cases.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from enum import Enum

import psycopg2
from psycopg2 import sql

logger = logging.getLogger(__name__)


class IssueType(Enum):
    """Types of migration issues that can be detected."""
    MISSING_TRACKING = "missing_tracking"
    MISSING_FILE = "missing_file"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    INVALID_MIGRATION = "invalid_migration"
    STUCK_LOCK = "stuck_lock"
    ORPHANED_SCHEMA = "orphaned_schema"
    PARTIAL_MIGRATION = "partial_migration"
    DUPLICATE_VERSION = "duplicate_version"
    CORRUPTED_DATA = "corrupted_data"
    ROLLBACK_MISSING = "rollback_missing"


class IssueSeverity(Enum):
    """Severity levels for migration issues."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MigrationIssue:
    """Represents a migration issue detected during diagnostics."""
    type: IssueType
    severity: IssueSeverity
    version: Optional[str]
    description: str
    details: Dict[str, Any]
    suggested_fix: Optional[str] = None
    auto_fixable: bool = False


@dataclass
class DiagnosticResult:
    """Results of migration diagnostics."""
    success: bool
    message: str
    issues: List[MigrationIssue]
    database_state: Dict[str, Any]
    file_state: Dict[str, Any]
    inconsistencies: List[str]


@dataclass
class RepairResult:
    """Results of migration repair operations."""
    success: bool
    message: str
    issues_fixed: List[MigrationIssue]
    issues_remaining: List[MigrationIssue]
    actions_taken: List[str]


class MigrationDiagnostics:
    """Diagnostic and repair tools for migration issues."""
    
    def __init__(self, database_url: str, migrations_path: str):
        """Initialize diagnostics with database connection and migration path."""
        self.database_url = database_url
        self.migrations_path = Path(migrations_path)
        self.logger = logging.getLogger(__name__)
        
    def diagnose(self) -> DiagnosticResult:
        """Perform comprehensive migration diagnostics."""
        self.logger.info("Starting migration diagnostics")
        
        issues = []
        database_state = {}
        file_state = {}
        inconsistencies = []
        
        try:
            # Analyze database state
            database_state = self._analyze_database_state()
            
            # Analyze file state
            file_state = self._analyze_file_state()
            
            # Detect various types of issues
            issues.extend(self._detect_missing_tracking(database_state, file_state))
            issues.extend(self._detect_missing_files(database_state, file_state))
            issues.extend(self._detect_checksum_mismatches(database_state, file_state))
            issues.extend(self._detect_invalid_migrations(database_state))
            issues.extend(self._detect_stuck_locks(database_state))
            issues.extend(self._detect_orphaned_schemas(database_state, file_state))
            issues.extend(self._detect_partial_migrations(database_state))
            issues.extend(self._detect_duplicate_versions(database_state))
            issues.extend(self._detect_corrupted_data(database_state))
            issues.extend(self._detect_missing_rollback_files(file_state))
            
            # Analyze inconsistencies
            inconsistencies = self._analyze_inconsistencies(database_state, file_state)
            
            success = len([i for i in issues if i.severity in [IssueSeverity.HIGH, IssueSeverity.CRITICAL]]) == 0
            message = f"Diagnostics completed. Found {len(issues)} issues."
            
        except Exception as e:
            self.logger.error(f"Diagnostics failed: {e}")
            success = False
            message = f"Diagnostics failed: {str(e)}"
            
        return DiagnosticResult(
            success=success,
            message=message,
            issues=issues,
            database_state=database_state,
            file_state=file_state,
            inconsistencies=inconsistencies
        )
    
    def repair(self, issues: List[MigrationIssue] = None, force: bool = False) -> RepairResult:
        """Repair migration issues automatically where possible."""
        self.logger.info("Starting migration repair")
        
        if issues is None:
            # Run diagnostics first
            diagnostic_result = self.diagnose()
            issues = diagnostic_result.issues
        
        issues_fixed = []
        issues_remaining = []
        actions_taken = []
        
        try:
            # Sort issues by severity (critical first)
            issues.sort(key=lambda x: [IssueSeverity.CRITICAL, IssueSeverity.HIGH, 
                                     IssueSeverity.MEDIUM, IssueSeverity.LOW].index(x.severity))
            
            for issue in issues:
                if issue.auto_fixable or force:
                    try:
                        action = self._repair_issue(issue, force)
                        if action:
                            issues_fixed.append(issue)
                            actions_taken.append(action)
                            self.logger.info(f"Fixed issue: {issue.description}")
                        else:
                            issues_remaining.append(issue)
                    except Exception as e:
                        self.logger.error(f"Failed to fix issue {issue.type}: {e}")
                        issues_remaining.append(issue)
                else:
                    issues_remaining.append(issue)
            
            success = len(issues_fixed) > 0 or len(issues) == 0
            message = f"Repair completed. Fixed {len(issues_fixed)} issues, {len(issues_remaining)} remaining."
            
        except Exception as e:
            self.logger.error(f"Repair failed: {e}")
            success = False
            message = f"Repair failed: {str(e)}"
            issues_remaining = issues
            
        return RepairResult(
            success=success,
            message=message,
            issues_fixed=issues_fixed,
            issues_remaining=issues_remaining,
            actions_taken=actions_taken
        )
    
    def _analyze_database_state(self) -> Dict[str, Any]:
        """Analyze current database state."""
        self.logger.debug("Analyzing database state")
        
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            # Get applied migrations
            cursor.execute("""
                SELECT version, description, applied_at, checksum, success, execution_time_ms
                FROM schema_migrations
                ORDER BY version
            """)
            applied_migrations = cursor.fetchall()
            
            # Get migration lock status
            cursor.execute("""
                SELECT locked_at, process_id, hostname
                FROM schema_migrations_lock
                ORDER BY locked_at DESC
                LIMIT 1
            """)
            lock_info = cursor.fetchone()
            
            # Get schema information
            cursor.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            """)
            schemas = [row[0] for row in cursor.fetchall()]
            
            # Get table information
            cursor.execute("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            """)
            tables = cursor.fetchall()
            
            # Get function information
            cursor.execute("""
                SELECT routine_schema, routine_name, routine_type
                FROM information_schema.routines
                WHERE routine_schema NOT IN ('information_schema', 'pg_catalog')
            """)
            functions = cursor.fetchall()
            
            # Get index information
            cursor.execute("""
                SELECT schemaname, tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            """)
            indexes = cursor.fetchall()
            
            return {
                'applied_migrations': applied_migrations,
                'lock_info': lock_info,
                'schemas': schemas,
                'tables': tables,
                'functions': functions,
                'indexes': indexes,
                'migration_count': len(applied_migrations),
                'is_locked': lock_info is not None
            }
            
        finally:
            conn.close()
    
    def _analyze_file_state(self) -> Dict[str, Any]:
        """Analyze migration file state."""
        self.logger.debug("Analyzing file state")
        
        migration_files = []
        rollback_files = []
        
        # Find migration files
        for file_path in self.migrations_path.glob("*.sql"):
            if file_path.name.endswith('.rollback.sql'):
                rollback_files.append(file_path)
            else:
                migration_files.append(file_path)
        
        # Parse migration information
        migrations = []
        for file_path in sorted(migration_files):
            version = self._extract_version(file_path.name)
            if version:
                checksum = self._calculate_checksum(file_path)
                rollback_file = self._find_rollback_file(file_path)
                
                migrations.append({
                    'version': version,
                    'file_path': file_path,
                    'checksum': checksum,
                    'rollback_file': rollback_file,
                    'has_rollback': rollback_file is not None
                })
        
        return {
            'migrations': migrations,
            'migration_files': migration_files,
            'rollback_files': rollback_files,
            'migration_count': len(migrations)
        }
    
    def _detect_missing_tracking(self, database_state: Dict, file_state: Dict) -> List[MigrationIssue]:
        """Detect migrations that are applied but not tracked."""
        issues = []
        
        tracked_versions = {m[0] for m in database_state['applied_migrations']}
        
        # Check for schema objects that might indicate applied migrations
        for migration in file_state['migrations']:
            version = migration['version']
            
            if version not in tracked_versions:
                # Check if this migration's objects exist in database
                if self._migration_appears_applied(migration, database_state):
                    issues.append(MigrationIssue(
                        type=IssueType.MISSING_TRACKING,
                        severity=IssueSeverity.HIGH,
                        version=version,
                        description=f"Migration {version} appears to be applied but not tracked",
                        details={
                            'migration_file': str(migration['file_path']),
                            'expected_checksum': migration['checksum']
                        },
                        suggested_fix="Use recovery mode to track this migration",
                        auto_fixable=True
                    ))
        
        return issues
    
    def _detect_missing_files(self, database_state: Dict, file_state: Dict) -> List[MigrationIssue]:
        """Detect migrations that are tracked but files are missing."""
        issues = []
        
        file_versions = {m['version'] for m in file_state['migrations']}
        
        for migration in database_state['applied_migrations']:
            version = migration[0]
            
            if version not in file_versions:
                issues.append(MigrationIssue(
                    type=IssueType.MISSING_FILE,
                    severity=IssueSeverity.MEDIUM,
                    version=version,
                    description=f"Migration {version} is tracked but file is missing",
                    details={
                        'expected_file': f"{version}_*.sql",
                        'tracked_checksum': migration[3]
                    },
                    suggested_fix="Restore migration file or remove from tracking",
                    auto_fixable=False
                ))
        
        return issues
    
    def _detect_checksum_mismatches(self, database_state: Dict, file_state: Dict) -> List[MigrationIssue]:
        """Detect migrations with checksum mismatches."""
        issues = []
        
        tracked_migrations = {m[0]: m for m in database_state['applied_migrations']}
        
        for migration in file_state['migrations']:
            version = migration['version']
            
            if version in tracked_migrations:
                tracked_checksum = tracked_migrations[version][3]
                file_checksum = migration['checksum']
                
                if tracked_checksum != file_checksum:
                    issues.append(MigrationIssue(
                        type=IssueType.CHECKSUM_MISMATCH,
                        severity=IssueSeverity.HIGH,
                        version=version,
                        description=f"Migration {version} has checksum mismatch",
                        details={
                            'tracked_checksum': tracked_checksum,
                            'file_checksum': file_checksum,
                            'migration_file': str(migration['file_path'])
                        },
                        suggested_fix="Update checksum in database or restore original file",
                        auto_fixable=True
                    ))
        
        return issues
    
    def _detect_invalid_migrations(self, database_state: Dict) -> List[MigrationIssue]:
        """Detect invalid migration records."""
        issues = []
        
        for migration in database_state['applied_migrations']:
            version, description, applied_at, checksum, success, execution_time = migration
            
            # Check for invalid versions
            if not self._is_valid_version(version):
                issues.append(MigrationIssue(
                    type=IssueType.INVALID_MIGRATION,
                    severity=IssueSeverity.HIGH,
                    version=version,
                    description=f"Invalid version format: {version}",
                    details={'version': version, 'description': description},
                    suggested_fix="Remove invalid migration record",
                    auto_fixable=True
                ))
            
            # Check for failed migrations
            if not success:
                issues.append(MigrationIssue(
                    type=IssueType.PARTIAL_MIGRATION,
                    severity=IssueSeverity.HIGH,
                    version=version,
                    description=f"Migration {version} failed during application",
                    details={'version': version, 'description': description},
                    suggested_fix="Retry migration or remove failed record",
                    auto_fixable=True
                ))
        
        return issues
    
    def _detect_stuck_locks(self, database_state: Dict) -> List[MigrationIssue]:
        """Detect stuck migration locks."""
        issues = []
        
        lock_info = database_state['lock_info']
        
        if lock_info:
            locked_at, process_id, hostname = lock_info
            
            # Check if lock is older than 1 hour
            if locked_at and (time.time() - locked_at.timestamp()) > 3600:
                issues.append(MigrationIssue(
                    type=IssueType.STUCK_LOCK,
                    severity=IssueSeverity.CRITICAL,
                    version=None,
                    description=f"Migration locked since {locked_at} by process {process_id} on {hostname}",
                    details={
                        'locked_at': locked_at.isoformat(),
                        'process_id': process_id,
                        'hostname': hostname
                    },
                    suggested_fix="Clear stuck lock",
                    auto_fixable=True
                ))
        
        return issues
    
    def _detect_orphaned_schemas(self, database_state: Dict, file_state: Dict) -> List[MigrationIssue]:
        """Detect schemas that exist but have no corresponding migrations."""
        issues = []
        
        # Get schemas created by migrations
        migration_schemas = set()
        for migration in file_state['migrations']:
            schemas = self._extract_schemas_from_migration(migration['file_path'])
            migration_schemas.update(schemas)
        
        # Check for orphaned schemas
        for schema in database_state['schemas']:
            if schema not in migration_schemas and not schema.startswith('pg_'):
                issues.append(MigrationIssue(
                    type=IssueType.ORPHANED_SCHEMA,
                    severity=IssueSeverity.MEDIUM,
                    version=None,
                    description=f"Schema {schema} exists but has no corresponding migration",
                    details={'schema': schema},
                    suggested_fix="Create migration for existing schema or remove it",
                    auto_fixable=False
                ))
        
        return issues
    
    def _detect_partial_migrations(self, database_state: Dict) -> List[MigrationIssue]:
        """Detect migrations that were partially applied."""
        issues = []
        
        for migration in database_state['applied_migrations']:
            version, description, applied_at, checksum, success, execution_time = migration
            
            if not success:
                issues.append(MigrationIssue(
                    type=IssueType.PARTIAL_MIGRATION,
                    severity=IssueSeverity.HIGH,
                    version=version,
                    description=f"Migration {version} was not successfully applied",
                    details={
                        'version': version,
                        'description': description,
                        'applied_at': applied_at.isoformat() if applied_at else None
                    },
                    suggested_fix="Retry migration or clean up partial state",
                    auto_fixable=True
                ))
        
        return issues
    
    def _detect_duplicate_versions(self, database_state: Dict) -> List[MigrationIssue]:
        """Detect duplicate migration versions."""
        issues = []
        
        versions = [m[0] for m in database_state['applied_migrations']]
        seen_versions = set()
        
        for version in versions:
            if version in seen_versions:
                issues.append(MigrationIssue(
                    type=IssueType.DUPLICATE_VERSION,
                    severity=IssueSeverity.HIGH,
                    version=version,
                    description=f"Duplicate migration version: {version}",
                    details={'version': version},
                    suggested_fix="Remove duplicate migration records",
                    auto_fixable=True
                ))
            seen_versions.add(version)
        
        return issues
    
    def _detect_corrupted_data(self, database_state: Dict) -> List[MigrationIssue]:
        """Detect corrupted migration data."""
        issues = []
        
        for migration in database_state['applied_migrations']:
            version, description, applied_at, checksum, success, execution_time = migration
            
            # Check for missing required fields
            if not version or not description:
                issues.append(MigrationIssue(
                    type=IssueType.CORRUPTED_DATA,
                    severity=IssueSeverity.HIGH,
                    version=version,
                    description=f"Migration record has missing required fields",
                    details={
                        'version': version,
                        'description': description,
                        'has_version': bool(version),
                        'has_description': bool(description)
                    },
                    suggested_fix="Clean up corrupted migration record",
                    auto_fixable=True
                ))
            
            # Check for invalid checksums
            if checksum and len(checksum) != 64:
                issues.append(MigrationIssue(
                    type=IssueType.CORRUPTED_DATA,
                    severity=IssueSeverity.MEDIUM,
                    version=version,
                    description=f"Migration {version} has invalid checksum",
                    details={
                        'version': version,
                        'checksum': checksum,
                        'checksum_length': len(checksum) if checksum else 0
                    },
                    suggested_fix="Recalculate checksum",
                    auto_fixable=True
                ))
        
        return issues
    
    def _detect_missing_rollback_files(self, file_state: Dict) -> List[MigrationIssue]:
        """Detect migrations missing rollback files."""
        issues = []
        
        for migration in file_state['migrations']:
            if not migration['has_rollback']:
                issues.append(MigrationIssue(
                    type=IssueType.ROLLBACK_MISSING,
                    severity=IssueSeverity.LOW,
                    version=migration['version'],
                    description=f"Migration {migration['version']} has no rollback file",
                    details={
                        'version': migration['version'],
                        'migration_file': str(migration['file_path'])
                    },
                    suggested_fix="Create rollback file for this migration",
                    auto_fixable=False
                ))
        
        return issues
    
    def _analyze_inconsistencies(self, database_state: Dict, file_state: Dict) -> List[str]:
        """Analyze various inconsistencies between database and file state."""
        inconsistencies = []
        
        db_count = database_state['migration_count']
        file_count = file_state['migration_count']
        
        if db_count != file_count:
            inconsistencies.append(f"Migration count mismatch: database has {db_count}, files have {file_count}")
        
        # Check for version gaps
        file_versions = sorted([m['version'] for m in file_state['migrations']])
        db_versions = sorted([m[0] for m in database_state['applied_migrations']])
        
        if file_versions != db_versions:
            inconsistencies.append(f"Version mismatch: file versions {file_versions} != db versions {db_versions}")
        
        return inconsistencies
    
    def _repair_issue(self, issue: MigrationIssue, force: bool = False) -> Optional[str]:
        """Repair a specific issue."""
        if issue.type == IssueType.MISSING_TRACKING:
            return self._repair_missing_tracking(issue, force)
        elif issue.type == IssueType.CHECKSUM_MISMATCH:
            return self._repair_checksum_mismatch(issue, force)
        elif issue.type == IssueType.STUCK_LOCK:
            return self._repair_stuck_lock(issue, force)
        elif issue.type == IssueType.INVALID_MIGRATION:
            return self._repair_invalid_migration(issue, force)
        elif issue.type == IssueType.DUPLICATE_VERSION:
            return self._repair_duplicate_version(issue, force)
        elif issue.type == IssueType.CORRUPTED_DATA:
            return self._repair_corrupted_data(issue, force)
        elif issue.type == IssueType.PARTIAL_MIGRATION:
            return self._repair_partial_migration(issue, force)
        
        return None
    
    def _repair_missing_tracking(self, issue: MigrationIssue, force: bool) -> str:
        """Repair missing migration tracking."""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            version = issue.version
            checksum = issue.details['expected_checksum']
            
            cursor.execute("""
                INSERT INTO schema_migrations (version, description, applied_at, checksum, success)
                VALUES (%s, %s, CURRENT_TIMESTAMP, %s, TRUE)
                ON CONFLICT (version) DO NOTHING
            """, (version, f"recovered_{version}", checksum))
            
            conn.commit()
            return f"Added tracking for migration {version}"
            
        finally:
            conn.close()
    
    def _repair_checksum_mismatch(self, issue: MigrationIssue, force: bool) -> str:
        """Repair checksum mismatch by updating database."""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            version = issue.version
            new_checksum = issue.details['file_checksum']
            
            cursor.execute("""
                UPDATE schema_migrations 
                SET checksum = %s, updated_at = CURRENT_TIMESTAMP
                WHERE version = %s
            """, (new_checksum, version))
            
            conn.commit()
            return f"Updated checksum for migration {version}"
            
        finally:
            conn.close()
    
    def _repair_stuck_lock(self, issue: MigrationIssue, force: bool) -> str:
        """Repair stuck migration lock."""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM schema_migrations_lock")
            conn.commit()
            return "Cleared stuck migration lock"
            
        finally:
            conn.close()
    
    def _repair_invalid_migration(self, issue: MigrationIssue, force: bool) -> str:
        """Repair invalid migration record."""
        if not force:
            return None
        
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            version = issue.version
            cursor.execute("DELETE FROM schema_migrations WHERE version = %s", (version,))
            conn.commit()
            return f"Removed invalid migration record {version}"
            
        finally:
            conn.close()
    
    def _repair_duplicate_version(self, issue: MigrationIssue, force: bool) -> str:
        """Repair duplicate version by keeping the latest."""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            version = issue.version
            cursor.execute("""
                DELETE FROM schema_migrations 
                WHERE version = %s AND applied_at < (
                    SELECT MAX(applied_at) FROM schema_migrations WHERE version = %s
                )
            """, (version, version))
            
            conn.commit()
            return f"Removed duplicate migration records for {version}"
            
        finally:
            conn.close()
    
    def _repair_corrupted_data(self, issue: MigrationIssue, force: bool) -> str:
        """Repair corrupted migration data."""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            version = issue.version
            
            # If checksum is invalid, recalculate it
            if 'checksum' in issue.details:
                migration_file = self._find_migration_file(version)
                if migration_file:
                    new_checksum = self._calculate_checksum(migration_file)
                    cursor.execute("""
                        UPDATE schema_migrations 
                        SET checksum = %s 
                        WHERE version = %s
                    """, (new_checksum, version))
                    conn.commit()
                    return f"Fixed corrupted checksum for migration {version}"
            
            return f"Attempted to repair corrupted data for migration {version}"
            
        finally:
            conn.close()
    
    def _repair_partial_migration(self, issue: MigrationIssue, force: bool) -> str:
        """Repair partial migration by retrying or cleaning up."""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()
        
        try:
            version = issue.version
            
            if force:
                # Remove failed migration record
                cursor.execute("DELETE FROM schema_migrations WHERE version = %s", (version,))
                conn.commit()
                return f"Removed failed migration record {version}"
            else:
                # Mark for retry
                cursor.execute("""
                    UPDATE schema_migrations 
                    SET success = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE version = %s
                """, (version,))
                conn.commit()
                return f"Marked migration {version} for retry"
            
        finally:
            conn.close()
    
    # Helper methods
    
    def _migration_appears_applied(self, migration: Dict, database_state: Dict) -> bool:
        """Check if migration appears to be applied based on database objects."""
        # This is a simplified check - in practice, would need more sophisticated analysis
        return True  # Placeholder implementation
    
    def _extract_version(self, filename: str) -> Optional[str]:
        """Extract version from migration filename."""
        parts = filename.split('_')
        if parts and parts[0].isdigit():
            return parts[0].zfill(3)
        return None
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of migration file."""
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    
    def _find_rollback_file(self, migration_file: Path) -> Optional[Path]:
        """Find rollback file for migration."""
        rollback_file = migration_file.parent / f"{migration_file.stem}.rollback.sql"
        return rollback_file if rollback_file.exists() else None
    
    def _find_migration_file(self, version: str) -> Optional[Path]:
        """Find migration file for version."""
        for file_path in self.migrations_path.glob(f"{version}_*.sql"):
            if not file_path.name.endswith('.rollback.sql'):
                return file_path
        return None
    
    def _is_valid_version(self, version: str) -> bool:
        """Check if version format is valid."""
        return version and version.isdigit() and len(version) == 3
    
    def _extract_schemas_from_migration(self, file_path: Path) -> Set[str]:
        """Extract schema names from migration file."""
        schemas = set()
        try:
            with open(file_path, 'r') as f:
                content = f.read().upper()
                # Simple regex to find CREATE SCHEMA statements
                import re
                matches = re.findall(r'CREATE\s+SCHEMA\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
                schemas.update(matches)
        except Exception as e:
            self.logger.warning(f"Could not parse migration file {file_path}: {e}")
        return schemas