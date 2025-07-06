"""
Command-line interface for Poststack

Provides a comprehensive CLI for managing container-based service orchestration
including PostgreSQL, Apache, Dovecot, BIND, and certificate management.
"""

import sys
from pathlib import Path
from typing import Optional

import click

from .bootstrap import bootstrap
from .config import PoststackConfig, load_config
from .database import database
from .logging_config import setup_logging

# Global configuration object
config: Optional[PoststackConfig] = None


@click.group()
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--database-url",
    envvar="POSTSTACK_DATABASE_URL",
    help="PostgreSQL connection URL",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    help="Set logging level",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.option(
    "--log-dir",
    type=click.Path(path_type=Path),
    default="logs",
    help="Directory for log files",
)
@click.version_option(package_name="poststack", message="%(prog)s %(version)s")
@click.pass_context
def cli(
    ctx: click.Context,
    config_file: Optional[Path],
    database_url: Optional[str],
    log_level: str,
    verbose: bool,
    log_dir: Path,
) -> None:
    """
    Poststack: Container-based service orchestration

    Manage containerized services including PostgreSQL, Apache, Dovecot,
    BIND DNS, and Let's Encrypt certificates through a unified CLI.
    """
    global config

    # Build CLI overrides
    cli_overrides = {
        "log_level": log_level.upper(),
        "verbose": verbose,
        "log_dir": str(log_dir),
    }

    if database_url:
        cli_overrides["database_url"] = database_url

    # Load configuration
    try:
        config = load_config(
            config_file=str(config_file) if config_file else None,
            cli_overrides=cli_overrides,
        )
    except Exception as e:
        click.echo(f"Error loading configuration: {e}", err=True)
        sys.exit(1)

    # Set up logging
    try:
        logger = setup_logging(
            log_dir=config.log_dir,
            verbose=config.verbose,
            log_level=config.log_level,
        )
        logger.info(f"Poststack CLI started - Version: {ctx.find_root().info_name}")
        logger.debug(f"Configuration: {config.mask_sensitive_values()}")
    except Exception as e:
        click.echo(f"Error setting up logging: {e}", err=True)
        sys.exit(1)

    # Store config in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


# Add command groups
cli.add_command(bootstrap)
cli.add_command(database)


@cli.command()
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration."""
    config = ctx.obj["config"]

    click.echo("Current Poststack Configuration:")
    click.echo("=" * 40)

    masked_config = config.mask_sensitive_values()
    for key, value in masked_config.items():
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        click.echo(f"{key.replace('_', ' ').title():<20}: {value}")


@cli.command()
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate current configuration."""
    config = ctx.obj["config"]

    click.echo("Validating Poststack configuration...")

    issues = []

    # Check database configuration
    if not config.is_database_configured:
        issues.append("❌ Database URL not configured")
    else:
        click.echo("✅ Database configuration valid")

    # Check domain configuration for certificates
    if not config.is_domain_configured:
        issues.append("❌ Domain/Let's Encrypt email not configured")
    else:
        click.echo("✅ Domain configuration valid")

    # Check log directory
    try:
        config.create_directories()
        click.echo("✅ Log directories created/verified")
    except Exception as e:
        issues.append(f"❌ Log directory issue: {e}")

    # Check certificate directory
    cert_path = config.get_cert_path()
    if cert_path.exists() or cert_path.parent.exists():
        click.echo("✅ Certificate directory accessible")
    else:
        issues.append(f"❌ Certificate directory not accessible: {cert_path}")

    if issues:
        click.echo("\nConfiguration Issues:")
        for issue in issues:
            click.echo(f"  {issue}")
        click.echo(f"\nFound {len(issues)} configuration issue(s)")
        sys.exit(1)
    else:
        click.echo("\n✅ Configuration is valid!")


@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Display version information."""
    from . import __author__, __version__

    config = ctx.obj["config"]

    click.echo(f"Poststack version {__version__}")
    click.echo(f"Author: {__author__}")
    click.echo(f"Container runtime: {config.container_runtime}")
    click.echo(f"Python: {sys.version}")


def main() -> None:
    """Entry point for the poststack command."""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\nOperation cancelled by user", err=True)
        sys.exit(130)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
