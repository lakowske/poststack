"""
Database management commands for Poststack

Handles PostgreSQL database operations, schema management,
and data migration tasks.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import click

from .config import PoststackConfig
from .schema_management import SchemaManager
from .database_operations import DatabaseManager
from .cli_enhanced import add_enhanced_commands

logger = logging.getLogger(__name__)


@click.group()
def database() -> None:
    """Manage PostgreSQL database operations."""
    pass


@database.command()
@click.option(
    "--timeout",
    default=30,
    help="Connection timeout in seconds",
)
@click.pass_context
def test_connection(ctx: click.Context, timeout: int) -> None:
    """Test database connection."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo(
            "❌ Database not configured. Set POSTSTACK_DATABASE_URL or use --database-url",
            err=True,
        )
        sys.exit(1)

    click.echo("🔌 Testing database connection...")

    try:
        # Parse database URL to show connection details (without password)
        import re

        import psycopg2

        effective_url = config.effective_database_url
        masked_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", effective_url)
        click.echo(f"Connecting to: {masked_url}")

        # Test connection
        conn = psycopg2.connect(effective_url, connect_timeout=timeout)
        cursor = conn.cursor()

        # Get database info
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]

        cursor.execute("SELECT current_database(), current_user;")
        db_name, db_user = cursor.fetchone()

        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';"
        )
        table_count = cursor.fetchone()[0]

        click.echo("✅ Connection successful!")
        click.echo(f"   Database: {db_name}")
        click.echo(f"   User: {db_user}")
        click.echo(f"   Version: {version}")
        click.echo(f"   Tables in public schema: {table_count}")

        cursor.close()
        conn.close()

    except ImportError:
        click.echo(
            "❌ psycopg2 not available. Install with: pip install psycopg2-binary",
            err=True,
        )
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Connection failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--force",
    is_flag=True,
    help="Force schema creation (drops existing schema)",
)
@click.pass_context
def create_schema(ctx: click.Context, force: bool) -> None:
    """Create the Poststack database schema using SQL migrations."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("🏗️  Creating Poststack database schema using SQL migrations...")

    if force:
        click.echo("⚠️  Force mode enabled - existing schema will be destroyed!")
        if not click.confirm("Are you sure you want to continue?"):
            click.echo("Schema creation cancelled")
            return

    try:
        # Initialize managers
        schema_manager = SchemaManager(config)
        db_manager = DatabaseManager(config)
        
        # Test database connection first
        effective_url = config.effective_database_url
        connection_result = db_manager.test_connection(effective_url)
        if not connection_result.passed:
            click.echo(f"❌ Database connection failed: {connection_result.message}", err=True)
            sys.exit(1)
        
        # Handle force mode - drop existing schema and migration tracking
        if force:
            try:
                import psycopg2
                conn = psycopg2.connect(effective_url)
                cursor = conn.cursor()
                
                # Check if schema exists
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'poststack');"
                )
                schema_exists = cursor.fetchone()[0]
                
                if schema_exists:
                    cursor.execute("DROP SCHEMA poststack CASCADE;")
                    click.echo("🗑️  Dropped existing schema")
                    
                # Drop migration tracking tables to ensure clean state
                cursor.execute("DROP TABLE IF EXISTS public.schema_migrations CASCADE;")
                cursor.execute("DROP TABLE IF EXISTS public.schema_migration_lock CASCADE;")
                click.echo("🗑️  Dropped migration tracking tables")
                    
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                logger.warning(f"Failed to drop existing schema: {e}")
        
        # Initialize schema using migrations (same as migrate command)
        result = schema_manager.update_schema(effective_url)
        
        if result.success:
            click.echo("\n🎉 Database schema created successfully using SQL migrations!")
            
            # Show what was created
            verification = schema_manager.verify_schema(effective_url)
            if verification.passed:
                click.echo(f"   Schema Version: {verification.details.get('schema_version', 'unknown')}")
                tables = verification.details.get('tables', [])
                if tables:
                    click.echo(f"   Tables Created: {', '.join(tables)}")
                    
            # Show migration status
            migration_status = schema_manager.get_migration_status(effective_url)
            applied_count = len(migration_status.get('applied_migrations', []))
            click.echo(f"   Applied Migrations: {applied_count}")
        else:
            click.echo(f"❌ Schema creation failed: {result.logs}", err=True)
            sys.exit(1)

    except ImportError as e:
        if "psycopg2" in str(e):
            click.echo(
                "❌ psycopg2 not available. Install with: pip install psycopg2-binary",
                err=True,
            )
        else:
            click.echo(f"❌ Import error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Schema creation failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.pass_context
def show_schema(ctx: click.Context) -> None:
    """Show current database schema information."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    try:
        import psycopg2

        effective_url = config.effective_database_url
        conn = psycopg2.connect(effective_url)
        cursor = conn.cursor()

        click.echo("📊 Poststack Database Schema")
        click.echo("=" * 40)

        # Check if schema exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = 'poststack'
            );
        """)
        schema_exists = cursor.fetchone()[0]

        if not schema_exists:
            click.echo("❌ Poststack schema does not exist")
            click.echo("Run 'poststack database create-schema' to create it")
            cursor.close()
            conn.close()
            return

        click.echo("✅ Poststack schema exists")

        # Get tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'poststack'
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()

        click.echo(f"\nTables ({len(tables)}):")
        for table in tables:
            table_name = table[0]

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM poststack.{table_name};")
            row_count = cursor.fetchone()[0]

            click.echo(f"  📋 {table_name}: {row_count} rows")

        # Get system info
        try:
            cursor.execute("SELECT key, value FROM poststack.system_info ORDER BY key;")
            system_info = cursor.fetchall()

            if system_info:
                click.echo("\nSystem Information:")
                for key, value in system_info:
                    click.echo(f"  🔧 {key}: {value}")
        except:
            pass  # Table might not exist

        cursor.close()
        conn.close()

    except Exception as e:
        click.echo(f"❌ Failed to show schema: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--confirm",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_context
def drop_schema(ctx: click.Context, confirm: bool) -> None:
    """Drop the Poststack database schema (DESTRUCTIVE)."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("⚠️  WARNING: This will destroy ALL Poststack data!")

    if not confirm:
        if not click.confirm("Are you absolutely sure you want to drop the schema?"):
            click.echo("Schema drop cancelled")
            return

    try:
        import psycopg2

        effective_url = config.effective_database_url
        conn = psycopg2.connect(effective_url)
        cursor = conn.cursor()

        # Check if schema exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = 'poststack'
            );
        """)
        schema_exists = cursor.fetchone()[0]

        if not schema_exists:
            click.echo("ℹ️  Poststack schema does not exist")
            cursor.close()
            conn.close()
            return

        cursor.execute("DROP SCHEMA poststack CASCADE;")
        
        # Clear migration tracking tables for clean state
        cursor.execute("DELETE FROM public.schema_migrations;")
        click.echo("🗑️  Cleared migration tracking records")
        
        conn.commit()

        click.echo("🗑️  Poststack schema dropped successfully")

        cursor.close()
        conn.close()

    except Exception as e:
        click.echo(f"❌ Failed to drop schema: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--target",
    help="Target migration version to migrate to"
)
@click.pass_context
def migrate(ctx: click.Context, target: Optional[str]) -> None:
    """Run database migrations to latest version using SQL migrations."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    if target:
        click.echo(f"🔄 Running database migrations to version {target}...")
    else:
        click.echo("🔄 Running database migrations to latest version...")

    try:
        # Initialize managers
        schema_manager = SchemaManager(config)
        db_manager = DatabaseManager(config)
        
        # Test database connection first
        effective_url = config.effective_database_url
        connection_result = db_manager.test_connection(effective_url)
        if not connection_result.passed:
            click.echo(f"❌ Database connection failed: {connection_result.message}", err=True)
            sys.exit(1)
        
        # Check if migration tracking tables exist
        migration_status = schema_manager.get_migration_status(effective_url)
        if 'error' in migration_status:
            click.echo("❌ Migration system not initialized")
            click.echo("Run 'poststack database create-schema' first")
            sys.exit(1)
        
        # Show current status
        current_version = migration_status.get('current_version')
        pending_count = len(migration_status.get('pending_migrations', []))
        
        if current_version:
            click.echo(f"   Current version: {current_version}")
        else:
            click.echo("   No migrations applied yet")
            
        if pending_count == 0:
            click.echo("✅ No pending migrations - database is up to date!")
            return
            
        click.echo(f"   Found {pending_count} pending migration(s)")
        
        # Run migrations
        result = schema_manager.update_schema(effective_url, target_version=target)
        
        if result.success:
            click.echo("✅ Database migrations completed successfully!")
            
            # Show updated status
            updated_status = schema_manager.get_migration_status(effective_url)
            new_version = updated_status.get('current_version')
            if new_version:
                click.echo(f"   New version: {new_version}")
                
            # Show schema version from system_info
            verification = schema_manager.verify_schema(effective_url)
            if verification.passed:
                click.echo(f"   Schema Version: {verification.details.get('schema_version', 'unknown')}")
        else:
            click.echo(f"❌ Migration failed: {result.logs}", err=True)
            sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Migration failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--table",
    help="Backup specific table only",
)
@click.option(
    "--output",
    type=click.Path(),
    help="Output file path (default: poststack_backup_YYYYMMDD_HHMMSS.sql)",
)
@click.pass_context
def backup(ctx: click.Context, table: Optional[str], output: Optional[str]) -> None:
    """Create a backup of the Poststack database."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    # Generate default filename if not provided
    if not output:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"poststack_backup_{timestamp}.sql"

    click.echo("💾 Creating database backup...")
    click.echo(f"Output file: {output}")

    try:
        import subprocess
        import urllib.parse

        # Parse database URL
        effective_url = config.effective_database_url
        parsed = urllib.parse.urlparse(effective_url)

        # Build pg_dump command
        cmd = [
            "pg_dump",
            f"--host={parsed.hostname}",
            f"--port={parsed.port or 5432}",
            f"--username={parsed.username}",
            f"--dbname={parsed.path[1:]}",  # Remove leading slash
            "--verbose",
            "--no-password",
            f"--file={output}",
        ]

        if table:
            cmd.extend(["--table", f"poststack.{table}"])
        else:
            cmd.extend(["--schema", "poststack"])

        # Set password environment variable
        env = {"PGPASSWORD": parsed.password} if parsed.password else {}

        click.echo("Running pg_dump...")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode == 0:
            click.echo("✅ Backup created successfully!")
        else:
            click.echo(f"❌ Backup failed: {result.stderr}", err=True)
            sys.exit(1)

    except FileNotFoundError:
        click.echo("❌ pg_dump not found. Install PostgreSQL client tools.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Backup failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.pass_context
def migration_status(ctx: click.Context) -> None:
    """Show current migration status."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    try:
        schema_manager = SchemaManager(config)
        effective_url = config.effective_database_url
        
        click.echo("📊 Migration Status")
        click.echo("=" * 40)
        
        migration_status = schema_manager.get_migration_status(effective_url)
        
        if 'error' in migration_status:
            click.echo("❌ Migration system not initialized")
            click.echo("Run 'poststack database create-schema' first")
            return
        
        current_version = migration_status.get('current_version')
        applied_migrations = migration_status.get('applied_migrations', [])
        pending_migrations = migration_status.get('pending_migrations', [])
        is_locked = migration_status.get('is_locked', False)
        
        if current_version:
            click.echo(f"Current version: {current_version}")
        else:
            click.echo("Current version: None (no migrations applied)")
            
        click.echo(f"Applied migrations: {len(applied_migrations)}")
        click.echo(f"Pending migrations: {len(pending_migrations)}")
        
        if is_locked:
            lock_info = migration_status.get('lock_info', {})
            click.echo("⚠️  Migration system is LOCKED")
            if lock_info:
                click.echo(f"   Locked by: {lock_info.get('locked_by', 'unknown')}")
                click.echo(f"   Locked at: {lock_info.get('locked_at', 'unknown')}")
        
        if applied_migrations:
            click.echo("\nApplied migrations:")
            for migration in applied_migrations:
                click.echo(f"  ✅ {migration['version']}: {migration.get('description', 'No description')}")
        
        if pending_migrations:
            click.echo("\nPending migrations:")
            for migration in pending_migrations:
                click.echo(f"  ⏳ {migration['version']}: {migration.get('description', 'No description')}")
        
        if not pending_migrations and applied_migrations:
            click.echo("\n✅ Database is up to date!")
            
    except Exception as e:
        click.echo(f"❌ Failed to get migration status: {e}", err=True)
        sys.exit(1)


@database.command()
@click.argument("target_version")
@click.option(
    "--confirm",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_context
def rollback(ctx: click.Context, target_version: str, confirm: bool) -> None:
    """Rollback database to a specific migration version."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo(f"⚠️  Rolling back database to version {target_version}")
    click.echo("⚠️  This will DESTROY data from newer migrations!")

    if not confirm:
        if not click.confirm("Are you sure you want to rollback?"):
            click.echo("Rollback cancelled")
            return

    try:
        schema_manager = SchemaManager(config)
        effective_url = config.effective_database_url
        
        # Show current status
        migration_status = schema_manager.get_migration_status(effective_url)
        current_version = migration_status.get('current_version')
        
        if current_version:
            click.echo(f"Current version: {current_version}")
        else:
            click.echo("❌ No migrations to rollback")
            return
            
        if current_version <= target_version:
            click.echo(f"❌ Target version {target_version} is not older than current version {current_version}")
            return
        
        # Perform rollback
        result = schema_manager.rollback_schema(effective_url, target_version)
        
        if result.success:
            click.echo(f"✅ Database rolled back to version {target_version}")
        else:
            click.echo(f"❌ Rollback failed: {result.logs}", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Rollback failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.pass_context
def verify_migrations(ctx: click.Context) -> None:
    """Verify that applied migrations match their checksums."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    try:
        schema_manager = SchemaManager(config)
        effective_url = config.effective_database_url
        
        click.echo("🔍 Verifying migration checksums...")
        
        verification = schema_manager.verify_migrations(effective_url)
        
        if verification['valid']:
            click.echo("✅ All migrations verified successfully!")
        else:
            click.echo("❌ Migration verification failed!")
            
            for error in verification['errors']:
                click.echo(f"   Error: {error}")
                
        for warning in verification['warnings']:
            click.echo(f"   Warning: {warning}")
            
        if not verification['valid']:
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Verification failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--command",
    "-c",
    help="Execute a single command and exit",
)
@click.pass_context
def shell(ctx: click.Context, command: Optional[str]) -> None:
    """Open a PostgreSQL shell (psql) to the auto-detected database."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured or auto-detection failed.", err=True)
        click.echo("Make sure PostgreSQL is running in your current environment.", err=True)
        sys.exit(1)

    try:
        import subprocess
        import urllib.parse

        # Get database URL (auto-detected or configured)
        effective_url = config.effective_database_url
        parsed = urllib.parse.urlparse(effective_url)

        # Build psql command
        cmd = [
            "psql",
            f"--host={parsed.hostname}",
            f"--port={parsed.port or 5432}",
            f"--username={parsed.username}",
            f"--dbname={parsed.path[1:]}",  # Remove leading slash
        ]

        if command:
            cmd.extend(["-c", command])

        # Set password environment variable
        env = {"PGPASSWORD": parsed.password} if parsed.password else {}

        # Show connection info (masked)
        import re
        masked_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", effective_url)
        click.echo(f"Connecting to: {masked_url}")

        if command:
            # Execute single command
            result = subprocess.run(cmd, env=env)
            sys.exit(result.returncode)
        else:
            # Interactive shell
            click.echo("Opening PostgreSQL shell (type \\q to exit)")
            subprocess.run(cmd, env=env)

    except FileNotFoundError:
        click.echo("❌ psql not found. Install PostgreSQL client tools.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Failed to open database shell: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--migrations-path",
    type=click.Path(exists=True, path_type=Path),
    default="./migrations",
    help="Path to migrations directory (default: ./migrations)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what migrations would be applied without running them",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Auto-confirm migration application without prompting",
)
@click.pass_context
def migrate_project(ctx: click.Context, migrations_path: Path, dry_run: bool, yes: bool) -> None:
    """Run project-specific database migrations from local migrations directory."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured or auto-detection failed.", err=True)
        click.echo("Make sure PostgreSQL is running in your current environment.", err=True)
        sys.exit(1)

    try:
        import subprocess
        import urllib.parse
        from pathlib import Path

        # Get database connection details
        effective_url = config.effective_database_url
        parsed = urllib.parse.urlparse(effective_url)
        
        # Show connection info (masked)
        import re
        masked_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", effective_url)
        click.echo(f"🔗 Database: {masked_url}")
        click.echo(f"📁 Migrations path: {migrations_path}")

        # Find migration files
        migration_files = sorted([
            f for f in migrations_path.glob("*.sql") 
            if not f.name.endswith(".rollback.sql")
        ])

        if not migration_files:
            click.echo(f"❌ No migration files found in {migrations_path}")
            sys.exit(1)

        click.echo(f"📋 Found {len(migration_files)} migration(s):")
        for migration_file in migration_files:
            click.echo(f"  - {migration_file.name}")

        if dry_run:
            click.echo("\n🔍 Dry run - no migrations were executed")
            return

        if not yes and not click.confirm(f"\nApply {len(migration_files)} migration(s)?"):
            click.echo("Migration cancelled")
            return

        # Set up environment for psql
        env = {}
        if parsed.password:
            env["PGPASSWORD"] = parsed.password

        # Apply each migration
        success_count = 0
        for migration_file in migration_files:
            click.echo(f"🔄 Applying: {migration_file.name}")
            
            cmd = [
                "psql",
                f"--host={parsed.hostname}",
                f"--port={parsed.port or 5432}",
                f"--username={parsed.username}",
                f"--dbname={parsed.path[1:]}",  # Remove leading slash
                "-f", str(migration_file),
                "-v", "ON_ERROR_STOP=1"
            ]

            result = subprocess.run(cmd, env=env, capture_output=True, text=True)

            if result.returncode == 0:
                click.echo(f"  ✅ Success: {migration_file.name}")
                success_count += 1
            else:
                click.echo(f"  ❌ Failed: {migration_file.name}")
                click.echo(f"     Error: {result.stderr.strip()}")
                break

        if success_count == len(migration_files):
            click.echo(f"\n🎉 All migrations applied successfully! ({success_count}/{len(migration_files)})")
        else:
            click.echo(f"\n⚠️  Migration stopped at failure. Applied: {success_count}/{len(migration_files)}")
            sys.exit(1)

    except FileNotFoundError:
        click.echo("❌ psql not found. Install PostgreSQL client tools.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Migration failed: {e}", err=True)
        sys.exit(1)


@database.command()
@click.option(
    "--confirm",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_context
def unlock_migrations(ctx: click.Context, confirm: bool) -> None:
    """Force unlock the migration system (use with caution)."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("⚠️  This will force unlock the migration system")
    click.echo("⚠️  Only use this if migrations are stuck due to a crashed process")

    if not confirm:
        if not click.confirm("Are you sure you want to force unlock?"):
            click.echo("Unlock cancelled")
            return

    try:
        schema_manager = SchemaManager(config)
        effective_url = config.effective_database_url
        
        success = schema_manager.force_unlock_migrations(effective_url)
        
        if success:
            click.echo("✅ Migration system unlocked")
        else:
            click.echo("❌ Failed to unlock migration system")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Unlock failed: {e}", err=True)
        sys.exit(1)


# Add enhanced migration commands
add_enhanced_commands(database)
