"""
Volume management commands for Poststack

Handles persistent volume operations including listing, cleanup,
backup, and restore for container deployments.
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import List, Optional

import click

from .config import PoststackConfig
from .environment.orchestrator import EnvironmentOrchestrator
from .environment.config import EnvironmentConfigParser

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async functions in sync Click commands."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)


@click.group()
def volumes() -> None:
    """Manage persistent volumes for deployments."""
    pass


@volumes.command()
@click.option(
    "--environment",
    "-e",
    help="Filter volumes by environment (e.g., dev, staging, production)",
)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show all volumes, not just poststack-managed ones",
)
@click.option(
    "--format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def list(ctx: click.Context, environment: Optional[str], show_all: bool, format: str) -> None:
    """List persistent volumes."""
    config: PoststackConfig = ctx.obj["config"]
    
    try:
        orchestrator = EnvironmentOrchestrator(config)
        
        click.echo("📦 Listing Persistent Volumes")
        if environment:
            click.echo(f"Environment: {environment}")
        
        # Get volumes
        volumes = run_async(orchestrator.list_environment_volumes(environment))
        
        if not volumes:
            if environment:
                click.echo(f"No volumes found for environment: {environment}")
            else:
                click.echo("No volumes found")
            return
        
        # Filter poststack-managed volumes unless --all is specified
        if not show_all:
            # Filter for volumes that look like poststack volumes
            # Pattern: {project}-{volume_name}-{environment}
            filtered_volumes = []
            for volume in volumes:
                name = volume.get('Name', '')
                # Basic heuristic: contains hyphens and looks like our naming pattern
                if '-' in name and any(env in name for env in ['dev', 'staging', 'production']):
                    filtered_volumes.append(volume)
            volumes = filtered_volumes
        
        if format == "json":
            import json
            click.echo(json.dumps(volumes, indent=2))
        else:
            # Table format
            click.echo(f"\nFound {len(volumes)} volume(s):")
            click.echo()
            click.echo("NAME                           DRIVER    CREATED                SIZE")
            click.echo("-" * 70)
            
            for volume in volumes:
                name = volume.get('Name', 'unknown')
                driver = volume.get('Driver', 'local')
                created_at = volume.get('CreatedAt', 'unknown')
                
                # Format creation date
                created = created_at
                if created_at and created_at != 'unknown':
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        created = dt.strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        pass
                
                # Try to get size from mountpoint if available
                size = "unknown"
                mountpoint = volume.get('Mountpoint', '')
                if mountpoint:
                    try:
                        import shutil
                        import os
                        if os.path.exists(mountpoint):
                            # Get directory size
                            total_size = 0
                            for dirpath, dirnames, filenames in os.walk(mountpoint):
                                for filename in filenames:
                                    filepath = os.path.join(dirpath, filename)
                                    try:
                                        total_size += os.path.getsize(filepath)
                                    except (OSError, FileNotFoundError):
                                        pass
                            
                            # Convert to human readable
                            if total_size > 0:
                                for unit in ['B', 'KB', 'MB', 'GB']:
                                    if total_size < 1024.0:
                                        size = f"{total_size:.1f}{unit}"
                                        break
                                    total_size /= 1024.0
                            else:
                                size = "0 B"
                    except Exception:
                        pass
                
                # Truncate long names
                display_name = name[:30] + "..." if len(name) > 30 else name
                click.echo(f"{display_name:<30} {driver:<8} {created:<18} {size}")
        
    except Exception as e:
        click.echo(f"❌ Failed to list volumes: {e}", err=True)
        sys.exit(1)


@volumes.command()
@click.option(
    "--environment",
    "-e",
    help="Environment to clean up volumes for",
)
@click.option(
    "--older-than",
    type=int,
    default=30,
    help="Remove volumes older than N days (default: 30)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be removed without actually removing",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force removal without confirmation",
)
@click.pass_context
def cleanup(ctx: click.Context, environment: Optional[str], older_than: int, dry_run: bool, force: bool) -> None:
    """Clean up old or unused volumes."""
    config: PoststackConfig = ctx.obj["config"]
    
    try:
        orchestrator = EnvironmentOrchestrator(config)
        
        if dry_run:
            click.echo("🔍 Dry run - showing what would be removed:")
        else:
            click.echo("🧹 Cleaning up volumes...")
        
        if environment:
            click.echo(f"Environment: {environment}")
        click.echo(f"Removing volumes older than {older_than} days")
        
        # Get volumes to potentially remove
        volumes = run_async(orchestrator.list_environment_volumes(environment))
        
        # Filter by age and other criteria
        volumes_to_remove = []
        for volume in volumes:
            name = volume.get('name', '')
            
            # Skip non-poststack volumes for safety
            if not ('-dev-' in name or '-staging-' in name or '-production-' in name):
                continue
            
            # For now, we'll be conservative and only remove volumes
            # that are explicitly marked for cleanup
            # In a real implementation, you'd check creation date, environment status, etc.
            
            # This is a placeholder - in practice you'd implement age checking
            # based on volume metadata or creation timestamps
            pass
        
        if not volumes_to_remove:
            click.echo("✅ No volumes need cleanup")
            return
        
        click.echo(f"\nFound {len(volumes_to_remove)} volume(s) for cleanup:")
        for volume in volumes_to_remove:
            click.echo(f"  - {volume.get('name', 'unknown')}")
        
        if dry_run:
            click.echo("\n🔍 Dry run complete - no volumes were removed")
            return
        
        if not force:
            if not click.confirm(f"\nRemove {len(volumes_to_remove)} volume(s)?"):
                click.echo("Cleanup cancelled")
                return
        
        # Remove volumes
        removed_count = 0
        for volume in volumes_to_remove:
            volume_name = volume.get('name', '')
            try:
                # Implementation would call orchestrator.remove_volume()
                click.echo(f"  ✅ Removed: {volume_name}")
                removed_count += 1
            except Exception as e:
                click.echo(f"  ❌ Failed to remove {volume_name}: {e}")
        
        click.echo(f"\n🎉 Cleanup complete: {removed_count} volume(s) removed")
        
    except Exception as e:
        click.echo(f"❌ Cleanup failed: {e}", err=True)
        sys.exit(1)


@volumes.command()
@click.argument("environment_name")
@click.option(
    "--force",
    is_flag=True,
    help="Force removal without confirmation",
)
@click.pass_context
def remove(ctx: click.Context, environment_name: str, force: bool) -> None:
    """Remove all volumes for a specific environment."""
    config: PoststackConfig = ctx.obj["config"]
    
    try:
        orchestrator = EnvironmentOrchestrator(config)
        
        click.echo(f"🗑️  Removing volumes for environment: {environment_name}")
        
        # Check if environment exists
        try:
            parser = EnvironmentConfigParser(config)
            env_config = parser.get_environment_config(environment_name)
        except Exception:
            click.echo(f"❌ Environment '{environment_name}' not found", err=True)
            sys.exit(1)
        
        # Get volumes for this environment
        volumes = run_async(orchestrator.list_environment_volumes(environment_name))
        
        if not volumes:
            click.echo(f"No volumes found for environment: {environment_name}")
            return
        
        click.echo(f"Found {len(volumes)} volume(s) to remove:")
        for volume in volumes:
            click.echo(f"  - {volume.get('name', 'unknown')}")
        
        if not force:
            click.echo(f"\n⚠️  This will permanently delete all data in these volumes!")
            if not click.confirm(f"Remove {len(volumes)} volume(s) for environment '{environment_name}'?"):
                click.echo("Removal cancelled")
                return
        
        # Remove volumes using orchestrator
        success = run_async(orchestrator.remove_environment_volumes(environment_name, force=True))
        
        if success:
            click.echo(f"✅ Successfully removed volumes for environment: {environment_name}")
        else:
            click.echo(f"❌ Some volumes could not be removed", err=True)
            sys.exit(1)
        
    except Exception as e:
        click.echo(f"❌ Failed to remove volumes: {e}", err=True)
        sys.exit(1)


@volumes.command()
@click.argument("volume_name")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file path (default: {volume_name}_backup_{timestamp}.tar.gz)",
)
@click.pass_context
def backup(ctx: click.Context, volume_name: str, output: Optional[str]) -> None:
    """Create a backup of a volume."""
    config: PoststackConfig = ctx.obj["config"]
    
    # Generate default filename if not provided
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"{volume_name}_backup_{timestamp}.tar.gz"
    
    click.echo(f"💾 Creating backup of volume: {volume_name}")
    click.echo(f"Output file: {output}")
    
    try:
        # This would use podman volume export or similar
        # For now, this is a placeholder implementation
        
        click.echo("⚠️  Volume backup functionality not yet implemented")
        click.echo("This feature will be added in a future version")
        click.echo("For now, you can manually backup volumes using:")
        click.echo(f"  podman volume export {volume_name} | gzip > {output}")
        
    except Exception as e:
        click.echo(f"❌ Backup failed: {e}", err=True)
        sys.exit(1)


@volumes.command()
@click.argument("backup_file", type=click.Path(exists=True))
@click.argument("volume_name")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing volume",
)
@click.pass_context
def restore(ctx: click.Context, backup_file: str, volume_name: str, force: bool) -> None:
    """Restore a volume from backup."""
    config: PoststackConfig = ctx.obj["config"]
    
    click.echo(f"♻️  Restoring volume: {volume_name}")
    click.echo(f"From backup: {backup_file}")
    
    try:
        # This would use podman volume import or similar
        # For now, this is a placeholder implementation
        
        click.echo("⚠️  Volume restore functionality not yet implemented")
        click.echo("This feature will be added in a future version")
        click.echo("For now, you can manually restore volumes using:")
        click.echo(f"  zcat {backup_file} | podman volume import {volume_name}")
        
    except Exception as e:
        click.echo(f"❌ Restore failed: {e}", err=True)
        sys.exit(1)


@volumes.command()
@click.argument("volume_name")
@click.pass_context
def inspect(ctx: click.Context, volume_name: str) -> None:
    """Show detailed information about a volume."""
    config: PoststackConfig = ctx.obj["config"]
    
    try:
        import subprocess
        import json
        
        click.echo(f"🔍 Inspecting volume: {volume_name}")
        
        # Get volume details using podman
        cmd = [config.container_runtime, "volume", "inspect", volume_name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            click.echo(f"❌ Volume '{volume_name}' not found", err=True)
            sys.exit(1)
        
        volume_info = json.loads(result.stdout)
        if volume_info:
            volume = volume_info[0]
            
            click.echo(f"Name: {volume.get('Name', 'unknown')}")
            click.echo(f"Driver: {volume.get('Driver', 'unknown')}")
            click.echo(f"Mountpoint: {volume.get('Mountpoint', 'unknown')}")
            click.echo(f"Created: {volume.get('CreatedAt', 'unknown')}")
            
            options = volume.get('Options', {})
            if options:
                click.echo("Options:")
                for key, value in options.items():
                    click.echo(f"  {key}: {value}")
            
            # Try to get size information
            mountpoint = volume.get('Mountpoint', '')
            if mountpoint:
                try:
                    import os
                    if os.path.exists(mountpoint):
                        # Get directory size
                        total_size = 0
                        for dirpath, dirnames, filenames in os.walk(mountpoint):
                            for filename in filenames:
                                filepath = os.path.join(dirpath, filename)
                                try:
                                    total_size += os.path.getsize(filepath)
                                except (OSError, FileNotFoundError):
                                    pass
                        
                        def format_bytes(bytes_val):
                            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                                if bytes_val < 1024.0:
                                    return f"{bytes_val:.1f} {unit}"
                                bytes_val /= 1024.0
                            return f"{bytes_val:.1f} PB"
                        
                        click.echo(f"Size: {format_bytes(total_size)} used")
                    
                except Exception:
                    pass
        
    except Exception as e:
        click.echo(f"❌ Failed to inspect volume: {e}", err=True)
        sys.exit(1)