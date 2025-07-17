"""
Command-line interface for Poststack (Database-Focused)

Provides database operations, schema management, and migrations.
Orchestration is now handled by Docker Compose.
"""

import sys
from pathlib import Path
from typing import Optional

import click

from .config import PoststackConfig, load_config
from .database import database
from .volumes import volumes
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
    default=None,
    help="Directory for log files",
)
@click.version_option()
@click.pass_context
def cli(
    ctx: click.Context,
    config_file: Optional[Path],
    log_level: str,
    verbose: bool,
    log_dir: Optional[Path],
) -> None:
    """
    Poststack: PostgreSQL database and schema migration management

    Focused on database operations and schema migrations.
    For container orchestration, use Docker Compose.
    """
    global config

    # Load configuration with defaults
    config = load_config(
        config_file=str(config_file) if config_file else None,
        cli_overrides={
            k: v for k, v in {
                "log_level": log_level.upper(),
                "verbose": verbose,
                "log_dir": str(log_dir) if log_dir else None,
            }.items() if v is not None
        },
    )

    # Setup logging based on loaded configuration
    setup_logging(
        log_dir=config.log_dir,
        verbose=config.verbose,
        log_level=config.log_level,
    )

    # Store config in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


# Database operations (core functionality)
cli.add_command(database, name="db")
cli.add_command(volumes, name="volumes")


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()