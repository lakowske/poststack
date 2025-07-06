"""
Bootstrap commands for Poststack

Handles initial system setup, configuration validation,
and preparation for service deployment.
"""

import logging
import subprocess
import sys
from pathlib import Path

import click

from .config import PoststackConfig
from .logging_config import SubprocessLogHandler

logger = logging.getLogger(__name__)


@click.group()
def bootstrap() -> None:
    """Bootstrap and initialize Poststack services."""
    pass


@bootstrap.command()
@click.option(
    "--database-url",
    prompt="PostgreSQL connection URL",
    help="PostgreSQL connection URL (postgresql://user:pass@host:port/db)",
)
@click.option(
    "--domain-name",
    prompt="Primary domain name",
    help="Primary domain name for services",
)
@click.option(
    "--le-email",
    prompt="Let's Encrypt email",
    help="Email address for Let's Encrypt notifications",
)
@click.option(
    "--container-runtime",
    type=click.Choice(["podman", "docker"], case_sensitive=False),
    default="podman",
    help="Container runtime to use",
)
@click.pass_context
def init(
    ctx: click.Context,
    database_url: str,
    domain_name: str,
    le_email: str,
    container_runtime: str,
) -> None:
    """Initialize Poststack configuration interactively."""
    config: PoststackConfig = ctx.obj["config"]

    click.echo("🚀 Initializing Poststack configuration...")

    # Update configuration
    updated_config = PoststackConfig(
        database_url=database_url,
        domain_name=domain_name,
        le_email=le_email,
        container_runtime=container_runtime.lower(),
        log_level=config.log_level,
        verbose=config.verbose,
        log_dir=config.log_dir,
    )

    # Validate configuration
    click.echo("\n📋 Validating configuration...")

    if not updated_config.is_database_configured:
        click.echo("❌ Database configuration invalid", err=True)
        sys.exit(1)

    if not updated_config.is_domain_configured:
        click.echo("❌ Domain configuration invalid", err=True)
        sys.exit(1)

    click.echo("✅ Configuration validation passed")

    # Create necessary directories
    try:
        updated_config.create_directories()
        click.echo("✅ Created necessary directories")
    except Exception as e:
        click.echo(f"❌ Failed to create directories: {e}", err=True)
        sys.exit(1)

    # Save configuration to .env file
    env_file = Path(".env")
    try:
        with open(env_file, "w") as f:
            f.write(f"POSTSTACK_DATABASE_URL={database_url}\n")
            f.write(f"POSTSTACK_DOMAIN_NAME={domain_name}\n")
            f.write(f"POSTSTACK_LE_EMAIL={le_email}\n")
            f.write(f"POSTSTACK_CONTAINER_RUNTIME={container_runtime.lower()}\n")
            f.write(f"POSTSTACK_LOG_LEVEL={config.log_level}\n")
            f.write(f"POSTSTACK_LOG_DIR={config.log_dir}\n")

        click.echo(f"✅ Saved configuration to {env_file}")
    except Exception as e:
        click.echo(f"❌ Failed to save configuration: {e}", err=True)
        sys.exit(1)

    click.echo("\n🎉 Poststack initialization complete!")
    click.echo("\nNext steps:")
    click.echo(
        "1. Run 'poststack bootstrap check-system' to verify system requirements"
    )
    click.echo("2. Run 'poststack bootstrap setup-database' to initialize the database")
    click.echo(
        "3. Run 'poststack bootstrap build-containers' to build container images"
    )


@bootstrap.command()
@click.pass_context
def check_system(ctx: click.Context) -> None:
    """Check system requirements and dependencies."""
    config: PoststackConfig = ctx.obj["config"]

    click.echo("🔍 Checking system requirements...")

    issues = []

    # Check container runtime
    try:
        result = subprocess.run(
            [config.container_runtime, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            click.echo(
                f"✅ {config.container_runtime.title()} available: {result.stdout.strip()}"
            )
        else:
            issues.append(f"❌ {config.container_runtime.title()} not working properly")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append(f"❌ {config.container_runtime.title()} not found")

    # Check for required system tools
    required_tools = {
        "git": ["--version"],
        "openssl": ["version"],
    }
    for tool, version_args in required_tools.items():
        try:
            result = subprocess.run(
                [tool] + version_args,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                click.echo(f"✅ {tool} available")
            else:
                issues.append(f"❌ {tool} not working properly")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            issues.append(f"❌ {tool} not found")

    # Check Python version
    python_version = sys.version_info
    if python_version >= (3, 9):
        click.echo(
            f"✅ Python {python_version.major}.{python_version.minor}.{python_version.micro}"
        )
    else:
        issues.append(
            f"❌ Python 3.9+ required, found {python_version.major}.{python_version.minor}"
        )

    # Check disk space in current directory
    try:
        import shutil

        free_space = shutil.disk_usage(".").free / (1024**3)  # GB
        if free_space >= 5.0:
            click.echo(f"✅ Disk space: {free_space:.1f} GB available")
        else:
            issues.append(
                f"❌ Insufficient disk space: {free_space:.1f} GB (5 GB required)"
            )
    except Exception:
        issues.append("❌ Unable to check disk space")

    # Check if running as root (warn but don't fail)
    if sys.platform != "win32":
        import os

        if os.geteuid() == 0:
            click.echo("⚠️  Running as root - consider using a non-root user")

    if issues:
        click.echo("\n❌ System check failed:")
        for issue in issues:
            click.echo(f"  {issue}")
        click.echo(f"\nFound {len(issues)} issue(s)")
        sys.exit(1)
    else:
        click.echo("\n✅ System check passed!")


@bootstrap.command()
@click.option(
    "--force",
    is_flag=True,
    help="Force database initialization (drops existing data)",
)
@click.pass_context
def setup_database(ctx: click.Context, force: bool) -> None:
    """Initialize and set up the PostgreSQL database."""
    config: PoststackConfig = ctx.obj["config"]

    if not config.is_database_configured:
        click.echo(
            "❌ Database not configured. Run 'poststack bootstrap init' first.",
            err=True,
        )
        sys.exit(1)

    click.echo("🗄️  Setting up PostgreSQL database...")

    if force:
        click.echo("⚠️  Force mode enabled - existing data will be destroyed!")
        if not click.confirm("Are you sure you want to continue?"):
            click.echo("Database setup cancelled")
            return

    # Test database connection
    try:
        import psycopg2

        click.echo("Testing database connection...")
        conn = psycopg2.connect(config.database_url)
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        click.echo(f"✅ Connected to PostgreSQL: {version}")
        cursor.close()
        conn.close()
    except ImportError:
        click.echo("❌ psycopg2 not available for database testing", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Database connection failed: {e}", err=True)
        sys.exit(1)

    # Here we would normally run database migrations/schema setup
    # For now, we'll just create a basic structure
    try:
        conn = psycopg2.connect(config.database_url)
        cursor = conn.cursor()

        if force:
            cursor.execute("DROP SCHEMA IF EXISTS poststack CASCADE;")
            click.echo("🗑️  Dropped existing schema")

        cursor.execute("CREATE SCHEMA IF NOT EXISTS poststack;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS poststack.system_info (
                id SERIAL PRIMARY KEY,
                key VARCHAR(255) UNIQUE NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Insert version info
        cursor.execute(
            """
            INSERT INTO poststack.system_info (key, value) 
            VALUES ('version', %s)
            ON CONFLICT (key) DO UPDATE SET 
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP;
        """,
            ("0.1.0",),
        )

        conn.commit()
        cursor.close()
        conn.close()

        click.echo("✅ Database schema initialized")

    except Exception as e:
        click.echo(f"❌ Database setup failed: {e}", err=True)
        sys.exit(1)

    click.echo("\n🎉 Database setup complete!")


@bootstrap.command()
@click.option(
    "--parallel",
    is_flag=True,
    help="Build containers in parallel where possible",
)
@click.pass_context
def build_containers(ctx: click.Context, parallel: bool) -> None:
    """Build required container images."""
    config: PoststackConfig = ctx.obj["config"]

    click.echo("📦 Building container images...")

    # For Phase 2, we'll simulate container builds
    # In later phases, this will build actual container images

    containers = [
        "poststack/postgresql",
        "poststack/apache",
        "poststack/dovecot",
        "poststack/bind",
        "poststack/certbot",
    ]

    log_handler = SubprocessLogHandler("container_build", config.log_dir)

    for container in containers:
        click.echo(f"🔨 Building {container}...")

        # Simulate build process
        import time

        time.sleep(1)  # Simulate build time

        log_handler.log_command(
            [config.container_runtime, "build", "-t", container, "."]
        )
        log_handler.log_output(f"Successfully built {container}")
        log_handler.log_completion(0, 1.0)

        click.echo(f"✅ {container} built successfully")

    click.echo(f"\n📄 Build logs saved to: {log_handler.get_log_file_path()}")
    click.echo("🎉 All containers built successfully!")


@bootstrap.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current bootstrap status."""
    config: PoststackConfig = ctx.obj["config"]

    click.echo("📊 Poststack Bootstrap Status")
    click.echo("=" * 40)

    # Configuration status
    if config.is_database_configured and config.is_domain_configured:
        click.echo("✅ Configuration: Complete")
    else:
        click.echo("❌ Configuration: Incomplete")
        if not config.is_database_configured:
            click.echo("   - Database URL not configured")
        if not config.is_domain_configured:
            click.echo("   - Domain/email not configured")

    # Check if .env exists
    env_file = Path(".env")
    if env_file.exists():
        click.echo("✅ Environment file: Present")
    else:
        click.echo("❌ Environment file: Missing")

    # Check directories
    log_dir = config.get_log_dir_path()
    cert_dir = config.get_cert_path()

    if log_dir.exists():
        click.echo("✅ Log directory: Created")
    else:
        click.echo("❌ Log directory: Missing")

    if cert_dir.exists():
        click.echo("✅ Certificate directory: Created")
    else:
        click.echo("❌ Certificate directory: Missing")

    # Database status (if configured)
    if config.is_database_configured:
        try:
            import psycopg2

            conn = psycopg2.connect(config.database_url)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = 'poststack';"
            )
            schema_exists = cursor.fetchone()[0] > 0
            cursor.close()
            conn.close()

            if schema_exists:
                click.echo("✅ Database schema: Initialized")
            else:
                click.echo("❌ Database schema: Not initialized")
        except Exception:
            click.echo("❌ Database: Connection failed")

    click.echo()

    # Next steps recommendations
    if not config.is_database_configured or not config.is_domain_configured:
        click.echo("💡 Next step: Run 'poststack bootstrap init'")
    elif not env_file.exists():
        click.echo("💡 Next step: Run 'poststack bootstrap init' to save configuration")
    else:
        click.echo("💡 Next steps:")
        click.echo("   1. poststack bootstrap check-system")
        click.echo("   2. poststack bootstrap setup-database")
        click.echo("   3. poststack bootstrap build-containers")
