"""
Database management commands for Poststack

Handles PostgreSQL database operations, schema management,
and data migration tasks.
"""

import logging
import sys
from typing import Optional

import click

from .config import PoststackConfig
from .schema_management import SchemaManager
from .database_operations import DatabaseManager

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
    """Create the Poststack database schema using Liquibase."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("🏗️  Creating Poststack database schema using Liquibase...")

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
        
        # Handle force mode - drop existing schema and Liquibase tracking
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
                    
                # Always drop Liquibase tracking tables in force mode to ensure clean state
                cursor.execute("DROP TABLE IF EXISTS public.databasechangelog CASCADE;")
                cursor.execute("DROP TABLE IF EXISTS public.databasechangeloglock CASCADE;")
                click.echo("🗑️  Dropped Liquibase tracking tables")
                    
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                logger.warning(f"Failed to drop existing schema: {e}")
        
        # Create schema first (Liquibase workaround)
        try:
            import psycopg2
            conn = psycopg2.connect(effective_url)
            cursor = conn.cursor()
            cursor.execute("CREATE SCHEMA IF NOT EXISTS poststack;")
            conn.commit()
            cursor.close()
            conn.close()
            click.echo("✅ Created poststack schema")
        except Exception as e:
            logger.warning(f"Schema creation preparation: {e}")
        
        # Initialize schema using Liquibase
        result = schema_manager.initialize_schema(effective_url)
        
        if result.success:
            click.echo("\n🎉 Database schema created successfully using Liquibase!")
            
            # Show what was created
            verification = schema_manager.verify_schema(effective_url)
            if verification.passed:
                click.echo(f"   Schema Version: {verification.details.get('schema_version', 'unknown')}")
                tables = verification.details.get('tables', [])
                if tables:
                    click.echo(f"   Tables Created: {', '.join(tables)}")
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
        
        # Also drop Liquibase tracking tables to ensure clean state
        cursor.execute("DROP TABLE IF EXISTS public.databasechangelog CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS public.databasechangeloglock CASCADE;")
        
        conn.commit()

        click.echo("🗑️  Poststack schema dropped successfully")

        cursor.close()
        conn.close()

    except Exception as e:
        click.echo(f"❌ Failed to drop schema: {e}", err=True)
        sys.exit(1)


@database.command()
@click.pass_context
def migrate(ctx: click.Context) -> None:
    """Run database migrations to latest version using Liquibase."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("🔄 Running database migrations using Liquibase...")

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
        
        # Get current schema status
        status = schema_manager.get_schema_status(effective_url)
        
        if not status['verification']['passed']:
            click.echo("❌ Poststack schema does not exist or is incomplete")
            click.echo("Run 'poststack database create-schema' first")
            sys.exit(1)
        
        # Run Liquibase update to apply any pending migrations
        result = schema_manager.update_schema(effective_url)
        
        if result.success:
            click.echo("✅ Database migrations completed successfully!")
            
            # Show updated status
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
