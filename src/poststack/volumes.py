"""
Volume management commands for Poststack (Database-Focused)

Handles basic volume operations for database-related containers.
For complex orchestration, use Docker Compose.
"""

import logging
import subprocess
import sys
from typing import List

import click

from .config import PoststackConfig

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def volumes(ctx: click.Context) -> None:
    """Basic volume management (database-focused)."""
    pass


@volumes.command("list")
@click.option("--all", "-a", is_flag=True, help="Show all volumes including non-poststack")
@click.pass_context
def list_volumes(ctx: click.Context, all: bool) -> None:
    """List volumes, optionally filtered to poststack-related ones."""
    try:
        # Get all volumes
        result = subprocess.run(
            ["podman", "volume", "ls", "--format", "{{.Name}}\t{{.Driver}}\t{{.MountPoint}}"],
            capture_output=True,
            text=True,
            check=True
        )
        
        volumes = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        if not volumes:
            click.echo("No volumes found")
            return
        
        # Filter for poststack volumes unless --all is specified
        if not all:
            volumes = [v for v in volumes if 'poststack' in v.lower() or 'postgres' in v.lower()]
        
        if not volumes:
            click.echo("No poststack-related volumes found")
            return
        
        click.echo("Volume Name\t\tDriver\t\tMount Point")
        click.echo("-" * 60)
        for volume in volumes:
            click.echo(volume)
            
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to list volumes: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo("❌ podman not found. Please install podman.", err=True)
        sys.exit(1)


@volumes.command("prune")
@click.option("--force", "-f", is_flag=True, help="Force removal without confirmation")
@click.pass_context
def prune_volumes(ctx: click.Context, force: bool) -> None:
    """Remove unused volumes."""
    if not force:
        click.confirm("This will remove unused volumes. Continue?", abort=True)
    
    try:
        result = subprocess.run(
            ["podman", "volume", "prune", "--force"],
            capture_output=True,
            text=True,
            check=True
        )
        
        if result.stdout.strip():
            click.echo("Pruned volumes:")
            click.echo(result.stdout)
        else:
            click.echo("No unused volumes to prune")
            
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to prune volumes: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo("❌ podman not found. Please install podman.", err=True)
        sys.exit(1)


@volumes.command("info")
@click.argument("volume_name")
@click.pass_context
def volume_info(ctx: click.Context, volume_name: str) -> None:
    """Show detailed information about a volume."""
    try:
        result = subprocess.run(
            ["podman", "volume", "inspect", volume_name],
            capture_output=True,
            text=True,
            check=True
        )
        
        click.echo(result.stdout)
        
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to inspect volume '{volume_name}': {e}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo("❌ podman not found. Please install podman.", err=True)
        sys.exit(1)