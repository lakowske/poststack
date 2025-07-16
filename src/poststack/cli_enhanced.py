"""
Enhanced CLI commands for poststack migration system.

Extends the existing database CLI with advanced diagnostic, recovery, and repair
capabilities for handling complex migration scenarios.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any

import click

from .config import PoststackConfig
from .migration_diagnostics import MigrationDiagnostics, IssueType, IssueSeverity
from .schema_migration import MigrationRunner

logger = logging.getLogger(__name__)


def add_enhanced_commands(database_group: click.Group) -> None:
    """Add enhanced migration commands to the database group."""
    
    @database_group.command("diagnose")
    @click.option(
        "--format",
        type=click.Choice(["text", "json"], case_sensitive=False),
        default="text",
        help="Output format (default: text)",
    )
    @click.option(
        "--severity",
        type=click.Choice(["low", "medium", "high", "critical"], case_sensitive=False),
        help="Filter issues by minimum severity level",
    )
    @click.option(
        "--type",
        "issue_type",
        type=click.Choice([t.value for t in IssueType], case_sensitive=False),
        help="Filter issues by specific type",
    )
    @click.option(
        "--migrations-path",
        type=click.Path(exists=True, path_type=Path),
        default="./migrations",
        help="Path to migrations directory (default: ./migrations)",
    )
    @click.pass_context
    def diagnose(ctx: click.Context, format: str, severity: Optional[str], 
                issue_type: Optional[str], migrations_path: Path) -> None:
        """Run comprehensive migration diagnostics."""
        config: PoststackConfig = ctx.obj["config"]

        if not config.is_database_configured:
            click.echo("❌ Database not configured.", err=True)
            sys.exit(1)

        try:
            effective_url = config.effective_database_url
            diagnostics = MigrationDiagnostics(effective_url, str(migrations_path))
            
            click.echo("🔍 Running migration diagnostics...")
            
            result = diagnostics.diagnose()
            
            if format == "json":
                _output_json_diagnostics(result)
            else:
                _output_text_diagnostics(result, severity, issue_type)
                
            # Exit with error code if critical issues found
            critical_issues = [i for i in result.issues if i.severity == IssueSeverity.CRITICAL]
            if critical_issues:
                sys.exit(1)
                
        except Exception as e:
            click.echo(f"❌ Diagnostics failed: {e}", err=True)
            sys.exit(1)

    @database_group.command("recover")
    @click.option(
        "--force",
        is_flag=True,
        help="Force recovery operations (potentially dangerous)",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Show what would be recovered without making changes",
    )
    @click.option(
        "--migrations-path",
        type=click.Path(exists=True, path_type=Path),
        default="./migrations",
        help="Path to migrations directory (default: ./migrations)",
    )
    @click.pass_context
    def recover(ctx: click.Context, force: bool, dry_run: bool, migrations_path: Path) -> None:
        """Recover from migration inconsistencies (like unified project scenario)."""
        config: PoststackConfig = ctx.obj["config"]

        if not config.is_database_configured:
            click.echo("❌ Database not configured.", err=True)
            sys.exit(1)

        try:
            effective_url = config.effective_database_url
            
            if dry_run:
                click.echo("🔍 Dry run - analyzing recovery options...")
                diagnostics = MigrationDiagnostics(effective_url, str(migrations_path))
                result = diagnostics.diagnose()
                
                recoverable_issues = [i for i in result.issues if i.auto_fixable or force]
                
                if recoverable_issues:
                    click.echo(f"Would recover {len(recoverable_issues)} issue(s):")
                    for issue in recoverable_issues:
                        click.echo(f"  - {issue.description}")
                        if issue.suggested_fix:
                            click.echo(f"    Fix: {issue.suggested_fix}")
                else:
                    click.echo("No recoverable issues found")
                return
            
            click.echo("🔄 Starting migration recovery...")
            
            # Use MigrationRunner for actual recovery
            runner = MigrationRunner(effective_url, str(migrations_path))
            result = runner.recover(force=force)
            
            if result.success:
                click.echo("✅ Recovery completed successfully!")
                click.echo(f"   {result.message}")
            else:
                click.echo(f"❌ Recovery failed: {result.message}")
                sys.exit(1)
                
        except Exception as e:
            click.echo(f"❌ Recovery failed: {e}", err=True)
            sys.exit(1)

    @database_group.command("repair")
    @click.option(
        "--force",
        is_flag=True,
        help="Force repair operations (potentially dangerous)",
    )
    @click.option(
        "--issue-type",
        type=click.Choice([t.value for t in IssueType], case_sensitive=False),
        help="Repair only specific issue types",
    )
    @click.option(
        "--migrations-path",
        type=click.Path(exists=True, path_type=Path),
        default="./migrations",
        help="Path to migrations directory (default: ./migrations)",
    )
    @click.pass_context
    def repair(ctx: click.Context, force: bool, issue_type: Optional[str], 
              migrations_path: Path) -> None:
        """Repair migration issues automatically where possible."""
        config: PoststackConfig = ctx.obj["config"]

        if not config.is_database_configured:
            click.echo("❌ Database not configured.", err=True)
            sys.exit(1)

        try:
            effective_url = config.effective_database_url
            diagnostics = MigrationDiagnostics(effective_url, str(migrations_path))
            
            click.echo("🔧 Starting migration repair...")
            
            # Run diagnostics first
            diagnostic_result = diagnostics.diagnose()
            
            # Filter issues by type if specified
            issues_to_repair = diagnostic_result.issues
            if issue_type:
                issues_to_repair = [i for i in issues_to_repair if i.type.value == issue_type]
            
            if not issues_to_repair:
                click.echo("✅ No issues found to repair")
                return
            
            # Show what will be repaired
            click.echo(f"Found {len(issues_to_repair)} issue(s) to repair:")
            for issue in issues_to_repair:
                fixable = "✅" if issue.auto_fixable or force else "❌"
                click.echo(f"  {fixable} {issue.description}")
                
            if not force:
                dangerous_issues = [i for i in issues_to_repair if not i.auto_fixable]
                if dangerous_issues:
                    click.echo(f"\n⚠️  {len(dangerous_issues)} issue(s) require --force flag")
                    for issue in dangerous_issues:
                        click.echo(f"    - {issue.description}")
                    
                    if not click.confirm("Continue with safe repairs only?"):
                        click.echo("Repair cancelled")
                        return
            
            # Perform repairs
            repair_result = diagnostics.repair(issues_to_repair, force=force)
            
            if repair_result.success:
                click.echo("✅ Repair completed!")
                click.echo(f"   Fixed: {len(repair_result.issues_fixed)} issue(s)")
                click.echo(f"   Remaining: {len(repair_result.issues_remaining)} issue(s)")
                
                if repair_result.actions_taken:
                    click.echo("\nActions taken:")
                    for action in repair_result.actions_taken:
                        click.echo(f"  - {action}")
            else:
                click.echo(f"❌ Repair failed: {repair_result.message}")
                sys.exit(1)
                
        except Exception as e:
            click.echo(f"❌ Repair failed: {e}", err=True)
            sys.exit(1)

    @database_group.command("validate")
    @click.option(
        "--check-files",
        is_flag=True,
        help="Validate migration files exist and are readable",
    )
    @click.option(
        "--check-checksums",
        is_flag=True,
        help="Validate migration checksums match files",
    )
    @click.option(
        "--check-rollbacks",
        is_flag=True,
        help="Validate rollback files exist for all migrations",
    )
    @click.option(
        "--migrations-path",
        type=click.Path(exists=True, path_type=Path),
        default="./migrations",
        help="Path to migrations directory (default: ./migrations)",
    )
    @click.pass_context
    def validate(ctx: click.Context, check_files: bool, check_checksums: bool, 
                check_rollbacks: bool, migrations_path: Path) -> None:
        """Enhanced validation of migration system integrity."""
        config: PoststackConfig = ctx.obj["config"]

        if not config.is_database_configured:
            click.echo("❌ Database not configured.", err=True)
            sys.exit(1)

        # Default to all checks if none specified
        if not any([check_files, check_checksums, check_rollbacks]):
            check_files = check_checksums = check_rollbacks = True

        try:
            effective_url = config.effective_database_url
            runner = MigrationRunner(effective_url, str(migrations_path))
            
            click.echo("🔍 Running enhanced migration validation...")
            
            errors = []
            warnings = []
            
            # File existence check
            if check_files:
                click.echo("  Checking migration files...")
                try:
                    migrations = runner.discover_migrations()
                    click.echo(f"    Found {len(migrations)} migration(s)")
                    
                    for migration in migrations:
                        if not migration.migration_file.exists():
                            errors.append(f"Migration file missing: {migration.migration_file}")
                        elif not migration.migration_file.is_file():
                            errors.append(f"Migration path is not a file: {migration.migration_file}")
                        else:
                            try:
                                migration.migration_file.read_text()
                            except Exception as e:
                                errors.append(f"Migration file not readable: {migration.migration_file} - {e}")
                                
                except Exception as e:
                    errors.append(f"Failed to discover migrations: {e}")
            
            # Checksum validation
            if check_checksums:
                click.echo("  Checking migration checksums...")
                try:
                    verification = runner.verify()
                    if not verification.valid:
                        errors.extend(verification.errors)
                    if verification.warnings:
                        warnings.extend(verification.warnings)
                except Exception as e:
                    errors.append(f"Checksum validation failed: {e}")
            
            # Rollback file validation
            if check_rollbacks:
                click.echo("  Checking rollback files...")
                try:
                    migrations = runner.discover_migrations()
                    missing_rollbacks = []
                    
                    for migration in migrations:
                        if not migration.rollback_file or not migration.rollback_file.exists():
                            missing_rollbacks.append(migration.version)
                    
                    if missing_rollbacks:
                        warnings.append(f"Missing rollback files for migrations: {', '.join(missing_rollbacks)}")
                        
                except Exception as e:
                    errors.append(f"Rollback validation failed: {e}")
            
            # Report results
            if errors:
                click.echo("\n❌ Validation errors found:")
                for error in errors:
                    click.echo(f"  - {error}")
            
            if warnings:
                click.echo("\n⚠️  Validation warnings:")
                for warning in warnings:
                    click.echo(f"  - {warning}")
            
            if not errors and not warnings:
                click.echo("✅ All validation checks passed!")
            elif not errors:
                click.echo("✅ Validation completed with warnings")
            else:
                click.echo("❌ Validation failed")
                sys.exit(1)
                
        except Exception as e:
            click.echo(f"❌ Validation failed: {e}", err=True)
            sys.exit(1)

    @database_group.command("clean")
    @click.option(
        "--locks",
        is_flag=True,
        help="Clear stuck migration locks",
    )
    @click.option(
        "--failed",
        is_flag=True,
        help="Remove failed migration records",
    )
    @click.option(
        "--duplicates",
        is_flag=True,
        help="Remove duplicate migration records",
    )
    @click.option(
        "--confirm",
        is_flag=True,
        help="Skip confirmation prompts",
    )
    @click.pass_context
    def clean(ctx: click.Context, locks: bool, failed: bool, duplicates: bool, confirm: bool) -> None:
        """Clean up migration artifacts and fix common issues."""
        config: PoststackConfig = ctx.obj["config"]

        if not config.is_database_configured:
            click.echo("❌ Database not configured.", err=True)
            sys.exit(1)

        # Default to all cleanup if none specified
        if not any([locks, failed, duplicates]):
            locks = failed = duplicates = True

        try:
            effective_url = config.effective_database_url
            diagnostics = MigrationDiagnostics(effective_url, "./migrations")
            
            click.echo("🧹 Cleaning migration artifacts...")
            
            # Run diagnostics to find issues
            diagnostic_result = diagnostics.diagnose()
            
            issues_to_fix = []
            
            if locks:
                issues_to_fix.extend([i for i in diagnostic_result.issues if i.type == IssueType.STUCK_LOCK])
            
            if failed:
                issues_to_fix.extend([i for i in diagnostic_result.issues if i.type == IssueType.PARTIAL_MIGRATION])
            
            if duplicates:
                issues_to_fix.extend([i for i in diagnostic_result.issues if i.type == IssueType.DUPLICATE_VERSION])
            
            if not issues_to_fix:
                click.echo("✅ No cleanup needed - migration system is clean")
                return
            
            # Show what will be cleaned
            click.echo(f"Found {len(issues_to_fix)} issue(s) to clean:")
            for issue in issues_to_fix:
                click.echo(f"  - {issue.description}")
            
            if not confirm:
                if not click.confirm("Proceed with cleanup?"):
                    click.echo("Cleanup cancelled")
                    return
            
            # Perform cleanup
            repair_result = diagnostics.repair(issues_to_fix, force=True)
            
            if repair_result.success:
                click.echo("✅ Cleanup completed successfully!")
                click.echo(f"   Fixed: {len(repair_result.issues_fixed)} issue(s)")
                
                if repair_result.actions_taken:
                    click.echo("\nActions taken:")
                    for action in repair_result.actions_taken:
                        click.echo(f"  - {action}")
            else:
                click.echo(f"❌ Cleanup failed: {repair_result.message}")
                sys.exit(1)
                
        except Exception as e:
            click.echo(f"❌ Cleanup failed: {e}", err=True)
            sys.exit(1)

    @database_group.command("migration-info")
    @click.argument("version", required=False)
    @click.option(
        "--format",
        type=click.Choice(["text", "json"], case_sensitive=False),
        default="text",
        help="Output format (default: text)",
    )
    @click.option(
        "--migrations-path",
        type=click.Path(exists=True, path_type=Path),
        default="./migrations",
        help="Path to migrations directory (default: ./migrations)",
    )
    @click.pass_context
    def migration_info(ctx: click.Context, version: Optional[str], format: str, 
                      migrations_path: Path) -> None:
        """Show detailed information about migrations."""
        config: PoststackConfig = ctx.obj["config"]

        if not config.is_database_configured:
            click.echo("❌ Database not configured.", err=True)
            sys.exit(1)

        try:
            effective_url = config.effective_database_url
            runner = MigrationRunner(effective_url, str(migrations_path))
            
            # Get status and migrations
            status = runner.status()
            migrations = runner.discover_migrations()
            
            if version:
                # Show specific migration info
                migration = next((m for m in migrations if m.version == version), None)
                if not migration:
                    click.echo(f"❌ Migration {version} not found")
                    sys.exit(1)
                
                if format == "json":
                    _output_json_migration_info(migration, status)
                else:
                    _output_text_migration_info(migration, status)
            else:
                # Show all migrations info
                if format == "json":
                    _output_json_all_migrations_info(migrations, status)
                else:
                    _output_text_all_migrations_info(migrations, status)
                    
        except Exception as e:
            click.echo(f"❌ Failed to get migration info: {e}", err=True)
            sys.exit(1)


def _output_json_diagnostics(result) -> None:
    """Output diagnostics in JSON format."""
    output = {
        "success": result.success,
        "message": result.message,
        "issues": [
            {
                "type": issue.type.value,
                "severity": issue.severity.value,
                "version": issue.version,
                "description": issue.description,
                "details": issue.details,
                "suggested_fix": issue.suggested_fix,
                "auto_fixable": issue.auto_fixable
            }
            for issue in result.issues
        ],
        "inconsistencies": result.inconsistencies,
        "database_state": {
            "migration_count": result.database_state.get("migration_count", 0),
            "is_locked": result.database_state.get("is_locked", False),
            "schema_count": len(result.database_state.get("schemas", [])),
            "table_count": len(result.database_state.get("tables", []))
        },
        "file_state": {
            "migration_count": result.file_state.get("migration_count", 0),
            "migrations_with_rollbacks": len([m for m in result.file_state.get("migrations", []) if m.get("has_rollback")])
        }
    }
    
    click.echo(json.dumps(output, indent=2))


def _output_text_diagnostics(result, severity_filter: Optional[str], type_filter: Optional[str]) -> None:
    """Output diagnostics in human-readable text format."""
    click.echo("Migration Diagnostics Report")
    click.echo("=" * 50)
    
    # Filter issues
    issues = result.issues
    if severity_filter:
        severity_levels = ["low", "medium", "high", "critical"]
        min_level = severity_levels.index(severity_filter.lower())
        issues = [i for i in issues if severity_levels.index(i.severity.value) >= min_level]
    
    if type_filter:
        issues = [i for i in issues if i.type.value == type_filter.lower()]
    
    # Summary
    click.echo(f"Overall Status: {'✅ PASS' if result.success else '❌ FAIL'}")
    click.echo(f"Total Issues: {len(issues)}")
    
    # Issue breakdown by severity
    severity_counts = {}
    for issue in issues:
        severity_counts[issue.severity.value] = severity_counts.get(issue.severity.value, 0) + 1
    
    if severity_counts:
        click.echo("\nIssue Breakdown:")
        for severity in ["critical", "high", "medium", "low"]:
            count = severity_counts.get(severity, 0)
            if count > 0:
                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}[severity]
                click.echo(f"  {icon} {severity.upper()}: {count}")
    
    # Database state
    click.echo(f"\nDatabase State:")
    click.echo(f"  Migrations Applied: {result.database_state.get('migration_count', 0)}")
    click.echo(f"  Schemas: {len(result.database_state.get('schemas', []))}")
    click.echo(f"  Tables: {len(result.database_state.get('tables', []))}")
    click.echo(f"  Locked: {'Yes' if result.database_state.get('is_locked') else 'No'}")
    
    # File state
    click.echo(f"\nFile State:")
    click.echo(f"  Migration Files: {result.file_state.get('migration_count', 0)}")
    migrations_with_rollbacks = len([m for m in result.file_state.get("migrations", []) if m.get("has_rollback")])
    click.echo(f"  With Rollbacks: {migrations_with_rollbacks}")
    
    # Inconsistencies
    if result.inconsistencies:
        click.echo(f"\nInconsistencies:")
        for inconsistency in result.inconsistencies:
            click.echo(f"  ⚠️  {inconsistency}")
    
    # Detailed issues
    if issues:
        click.echo(f"\nDetailed Issues:")
        for issue in issues:
            severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}[issue.severity.value]
            click.echo(f"\n{severity_icon} {issue.type.value.upper()}: {issue.description}")
            
            if issue.version:
                click.echo(f"   Version: {issue.version}")
            
            if issue.details:
                click.echo(f"   Details: {issue.details}")
            
            if issue.suggested_fix:
                click.echo(f"   Suggested Fix: {issue.suggested_fix}")
            
            if issue.auto_fixable:
                click.echo(f"   Auto-fixable: Yes")
    
    if not issues:
        click.echo("\n✅ No issues found matching the specified criteria")


def _output_json_migration_info(migration, status) -> None:
    """Output single migration info in JSON format."""
    is_applied = migration.version in [m.version for m in status.applied_migrations]
    
    output = {
        "version": migration.version,
        "name": migration.name,
        "description": migration.get_description(),
        "file_path": str(migration.migration_file),
        "rollback_file": str(migration.rollback_file) if migration.rollback_file else None,
        "checksum": migration.checksum,
        "is_applied": is_applied,
        "file_size": migration.migration_file.stat().st_size if migration.migration_file.exists() else 0,
        "has_rollback": migration.rollback_file is not None
    }
    
    click.echo(json.dumps(output, indent=2))


def _output_text_migration_info(migration, status) -> None:
    """Output single migration info in text format."""
    is_applied = migration.version in [m.version for m in status.applied_migrations]
    
    click.echo(f"Migration Information: {migration.version}")
    click.echo("=" * 50)
    click.echo(f"Name: {migration.name}")
    click.echo(f"Description: {migration.get_description()}")
    click.echo(f"File: {migration.migration_file}")
    click.echo(f"Rollback File: {migration.rollback_file or 'None'}")
    click.echo(f"Checksum: {migration.checksum}")
    click.echo(f"Status: {'✅ Applied' if is_applied else '⏳ Pending'}")
    click.echo(f"File Size: {migration.migration_file.stat().st_size if migration.migration_file.exists() else 0} bytes")
    click.echo(f"Has Rollback: {'Yes' if migration.rollback_file else 'No'}")


def _output_json_all_migrations_info(migrations, status) -> None:
    """Output all migrations info in JSON format."""
    applied_versions = [m.version for m in status.applied_migrations]
    
    output = {
        "current_version": status.current_version,
        "total_migrations": len(migrations),
        "applied_count": len(status.applied_migrations),
        "pending_count": len(status.pending_migrations),
        "migrations": [
            {
                "version": m.version,
                "name": m.name,
                "description": m.description,
                "file_path": str(m.file_path),
                "rollback_file": str(m.rollback_file) if m.rollback_file else None,
                "checksum": m.checksum,
                "is_applied": m.version in applied_versions,
                "file_size": m.file_path.stat().st_size if m.file_path.exists() else 0,
                "has_rollback": m.rollback_file is not None
            }
            for m in migrations
        ]
    }
    
    click.echo(json.dumps(output, indent=2))


def _output_text_all_migrations_info(migrations, status) -> None:
    """Output all migrations info in text format."""
    applied_versions = [m.version for m in status.applied_migrations]
    
    click.echo("All Migrations Information")
    click.echo("=" * 50)
    click.echo(f"Current Version: {status.current_version or 'None'}")
    click.echo(f"Total Migrations: {len(migrations)}")
    click.echo(f"Applied: {len(status.applied_migrations)}")
    click.echo(f"Pending: {len(status.pending_migrations)}")
    
    if migrations:
        click.echo("\nMigrations:")
        for migration in migrations:
            is_applied = migration.version in applied_versions
            status_icon = "✅" if is_applied else "⏳"
            rollback_icon = "🔄" if migration.rollback_file else "❌"
            
            click.echo(f"  {status_icon} {migration.version}: {migration.name}")
            click.echo(f"      Description: {migration.get_description()}")
            click.echo(f"      File: {migration.migration_file}")
            click.echo(f"      Rollback: {rollback_icon} {migration.rollback_file or 'None'}")
            click.echo(f"      Size: {migration.migration_file.stat().st_size if migration.migration_file.exists() else 0} bytes")
            click.echo()