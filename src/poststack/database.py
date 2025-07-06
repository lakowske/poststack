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

        masked_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", config.database_url)
        click.echo(f"Connecting to: {masked_url}")

        # Test connection
        conn = psycopg2.connect(config.database_url, connect_timeout=timeout)
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
    """Create the Poststack database schema."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("🏗️  Creating Poststack database schema...")

    if force:
        click.echo("⚠️  Force mode enabled - existing schema will be destroyed!")
        if not click.confirm("Are you sure you want to continue?"):
            click.echo("Schema creation cancelled")
            return

    try:
        import psycopg2

        conn = psycopg2.connect(config.database_url)
        cursor = conn.cursor()

        # Check if schema exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = 'poststack'
            );
        """)
        schema_exists = cursor.fetchone()[0]

        if schema_exists and not force:
            click.echo(
                "❌ Poststack schema already exists. Use --force to recreate it.",
                err=True,
            )
            cursor.close()
            conn.close()
            sys.exit(1)

        if force and schema_exists:
            cursor.execute("DROP SCHEMA poststack CASCADE;")
            click.echo("🗑️  Dropped existing schema")

        # Create schema
        cursor.execute("CREATE SCHEMA IF NOT EXISTS poststack;")
        click.echo("✅ Created poststack schema")

        # Create core tables
        cursor.execute("""
            CREATE TABLE poststack.system_info (
                id SERIAL PRIMARY KEY,
                key VARCHAR(255) UNIQUE NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        click.echo("✅ Created system_info table")

        cursor.execute("""
            CREATE TABLE poststack.services (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                type VARCHAR(100) NOT NULL,
                status VARCHAR(50) DEFAULT 'stopped',
                config JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        click.echo("✅ Created services table")

        cursor.execute("""
            CREATE TABLE poststack.containers (
                id SERIAL PRIMARY KEY,
                service_id INTEGER REFERENCES poststack.services(id) ON DELETE CASCADE,
                container_id VARCHAR(255) UNIQUE,
                image VARCHAR(255) NOT NULL,
                status VARCHAR(50) DEFAULT 'created',
                config JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        click.echo("✅ Created containers table")

        cursor.execute("""
            CREATE TABLE poststack.certificates (
                id SERIAL PRIMARY KEY,
                domain VARCHAR(255) UNIQUE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                cert_path TEXT,
                key_path TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        click.echo("✅ Created certificates table")

        # Insert initial system info
        cursor.execute("""
            INSERT INTO poststack.system_info (key, value) 
            VALUES 
                ('schema_version', '1.0.0'),
                ('created_by', 'poststack-cli'),
                ('poststack_version', '0.1.0')
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP;
        """)
        click.echo("✅ Inserted system information")

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_services_type ON poststack.services(type);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_services_status ON poststack.services(status);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_containers_status ON poststack.containers(status);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_certificates_domain ON poststack.certificates(domain);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_certificates_expires_at ON poststack.certificates(expires_at);"
        )
        click.echo("✅ Created indexes")

        conn.commit()
        cursor.close()
        conn.close()

        click.echo("\n🎉 Database schema created successfully!")

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

        conn = psycopg2.connect(config.database_url)
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

        conn = psycopg2.connect(config.database_url)
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
    """Run database migrations to latest version."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo("❌ Database not configured.", err=True)
        sys.exit(1)

    click.echo("🔄 Running database migrations...")

    try:
        import psycopg2

        conn = psycopg2.connect(config.database_url)
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
            click.echo("❌ Poststack schema does not exist")
            click.echo("Run 'poststack database create-schema' first")
            cursor.close()
            conn.close()
            sys.exit(1)

        # Get current schema version
        current_version = "0.0.0"
        try:
            cursor.execute("""
                SELECT value FROM poststack.system_info 
                WHERE key = 'schema_version';
            """)
            result = cursor.fetchone()
            if result:
                current_version = result[0]
        except:
            pass  # Table might not exist

        click.echo(f"Current schema version: {current_version}")

        # For Phase 2, we'll just update the version to 1.0.0
        target_version = "1.0.0"

        if current_version == target_version:
            click.echo("✅ Database is already up to date")
        else:
            # Update version
            cursor.execute(
                """
                INSERT INTO poststack.system_info (key, value) 
                VALUES ('schema_version', %s)
                ON CONFLICT (key) DO UPDATE SET 
                    value = EXCLUDED.value,
                    updated_at = CURRENT_TIMESTAMP;
            """,
                (target_version,),
            )

            conn.commit()
            click.echo(f"✅ Migrated from {current_version} to {target_version}")

        cursor.close()
        conn.close()

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
        parsed = urllib.parse.urlparse(config.database_url)

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
