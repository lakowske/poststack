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
from .real_container_builder import RealContainerBuilder

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
        logger.debug(f"Poststack CLI started - Version: {ctx.find_root().info_name}")
        logger.debug(f"Configuration: {config.mask_sensitive_values()}")
    except Exception as e:
        click.echo(f"Error setting up logging: {e}", err=True)
        sys.exit(1)

    # Store config in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


# Container management command group
@cli.group()
@click.pass_context
def container(ctx: click.Context) -> None:
    """Manage container builds and operations."""
    pass


@container.command("build")
@click.option(
    "--parallel",
    is_flag=True,
    help="Build service images in parallel after base image",
)
@click.option(
    "--image",
    type=click.Choice(["all", "base-debian", "postgres", "liquibase"]),
    default="all",
    help="Specific image to build (default: all)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable build cache",
)
@click.pass_context
def container_build(
    ctx: click.Context,
    parallel: bool,
    image: str,
    no_cache: bool,
) -> None:
    """Build Phase 4 container images."""
    config = ctx.obj["config"]
    
    click.echo("🚀 Building Poststack containers...")
    
    try:
        builder = RealContainerBuilder(config)
        
        if image == "all":
            click.echo("Building all Phase 4 images...")
            results = builder.build_all_phase4_images(parallel=parallel)
        elif image == "base-debian":
            click.echo("Building base-debian image...")
            result = builder.build_base_image()
            results = {"base-debian": result}
        elif image == "postgres":
            click.echo("Building postgres image...")
            result = builder.build_postgres_image()
            results = {"postgres": result}
        elif image == "liquibase":
            click.echo("Building liquibase image...")
            result = builder.build_liquibase_image()
            results = {"liquibase": result}
        
        # Display results
        click.echo("\n📊 Build Results:")
        click.echo("-" * 40)
        
        successful = 0
        total_time = 0
        
        for name, result in results.items():
            status_icon = "✅" if result.success else "❌"
            click.echo(f"{status_icon} {name:15} | {result.status.value:8} | {result.build_time:6.1f}s")
            
            if result.success:
                successful += 1
            total_time += result.build_time
        
        click.echo("-" * 40)
        click.echo(f"Total: {successful}/{len(results)} successful in {total_time:.1f}s")
        
        if successful == len(results):
            click.echo("\n🎉 All images built successfully!")
        else:
            click.echo(f"\n⚠️  {len(results) - successful} build(s) failed")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Container build failed: {e}", err=True)
        sys.exit(1)


@container.command("list")
@click.pass_context
def container_list(ctx: click.Context) -> None:
    """List built Poststack container images."""
    config = ctx.obj["config"]
    
    try:
        builder = RealContainerBuilder(config)
        
        images = ["poststack/base-debian:latest", "poststack/postgres:latest", "poststack/liquibase:latest"]
        
        click.echo("📦 Poststack Container Images:")
        click.echo("-" * 50)
        
        found_images = 0
        for image_name in images:
            info = builder.get_image_info(image_name)
            if info:
                found_images += 1
                click.echo(f"✅ {image_name}")
                click.echo(f"   Size: {info['size_mb']} MB, Layers: {info['layers']}, ID: {info['id']}")
            else:
                click.echo(f"❌ {image_name} (not built)")
        
        click.echo("-" * 50)
        click.echo(f"Found {found_images}/{len(images)} images")
        
    except Exception as e:
        click.echo(f"❌ Failed to list images: {e}", err=True)
        sys.exit(1)


@container.command("clean")
@click.option(
    "--test-only",
    is_flag=True,
    help="Only remove test images (cache-test-*)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force removal without confirmation",
)
@click.pass_context
def container_clean(ctx: click.Context, test_only: bool, force: bool) -> None:
    """Clean up container images."""
    config = ctx.obj["config"]
    
    try:
        builder = RealContainerBuilder(config)
        
        if test_only:
            click.echo("🧹 Cleaning test images...")
            builder.cleanup_test_images()
            click.echo("✅ Test images cleaned")
        else:
            # Remove all Poststack images
            images_to_remove = [
                "poststack/base-debian:latest",
                "poststack/base-debian:1.0.0", 
                "poststack/postgres:latest",
                "poststack/postgres:15",
                "poststack/liquibase:latest",
                "poststack/liquibase:4.24.0"
            ]
            
            # Check which images exist
            existing_images = []
            for image_name in images_to_remove:
                info = builder.get_image_info(image_name)
                if info:
                    existing_images.append(image_name)
            
            if not existing_images:
                click.echo("No Poststack images found to clean")
                return
                
            click.echo(f"Found {len(existing_images)} Poststack images to remove:")
            for image in existing_images:
                click.echo(f"  - {image}")
            
            if not force:
                if not click.confirm("\nAre you sure you want to remove these images?"):
                    click.echo("Cleanup cancelled")
                    return
            
            click.echo("🧹 Removing Poststack images...")
            removed_count = 0
            
            for image_name in existing_images:
                try:
                    result = builder.remove_image(image_name, force=True)
                    if result:
                        click.echo(f"✅ Removed {image_name}")
                        removed_count += 1
                    else:
                        click.echo(f"⚠️  Could not remove {image_name}")
                except Exception as e:
                    click.echo(f"❌ Failed to remove {image_name}: {e}")
            
            click.echo(f"\n🎉 Removed {removed_count}/{len(existing_images)} images")
        
    except Exception as e:
        click.echo(f"❌ Cleanup failed: {e}", err=True)
        sys.exit(1)


# Log management command group
@cli.group()
@click.pass_context
def logs(ctx: click.Context) -> None:
    """Manage Poststack log files."""
    pass


@logs.command("list")
@click.option(
    "--category",
    type=click.Choice(["all", "container", "database", "main"]),
    default="all",
    help="Filter logs by category",
)
@click.option(
    "--days",
    type=int,
    help="Show logs from last N days only",
)
@click.pass_context
def logs_list(ctx: click.Context, category: str, days: int) -> None:
    """List Poststack log files."""
    config = ctx.obj["config"]
    log_dir = Path(config.log_dir)
    
    if not log_dir.exists():
        click.echo("No log directory found")
        return
    
    import datetime
    import os
    
    cutoff_time = None
    if days:
        cutoff_time = datetime.datetime.now() - datetime.timedelta(days=days)
    
    # Collect log files by category
    log_files = {"main": [], "container": [], "database": []}
    
    # Main logs
    for log_file in log_dir.glob("poststack_*.log"):
        if cutoff_time and datetime.datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_time:
            continue
        log_files["main"].append(log_file)
    
    # Container logs
    container_log_dir = log_dir / "containers"
    if container_log_dir.exists():
        for log_file in container_log_dir.glob("*.log"):
            if cutoff_time and datetime.datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_time:
                continue
            log_files["container"].append(log_file)
    
    # Database logs
    db_log_dir = log_dir / "database"
    if db_log_dir.exists():
        for log_file in db_log_dir.glob("*.log"):
            if cutoff_time and datetime.datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_time:
                continue
            log_files["database"].append(log_file)
    
    # Display logs
    total_files = 0
    total_size = 0
    
    categories_to_show = [category] if category != "all" else ["main", "container", "database"]
    
    for cat in categories_to_show:
        if not log_files[cat]:
            continue
            
        click.echo(f"\n📄 {cat.title()} Logs:")
        click.echo("-" * 40)
        
        for log_file in sorted(log_files[cat], key=lambda x: x.stat().st_mtime, reverse=True):
            size = log_file.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
            mtime = datetime.datetime.fromtimestamp(log_file.stat().st_mtime)
            
            click.echo(f"  {log_file.name:40} {size_str:>10} {mtime.strftime('%Y-%m-%d %H:%M')}")
            total_files += 1
            total_size += size
    
    if total_files > 0:
        total_size_str = f"{total_size / 1024 / 1024:.1f} MB" if total_size > 1024*1024 else f"{total_size / 1024:.1f} KB"
        click.echo(f"\nTotal: {total_files} files, {total_size_str}")
    else:
        click.echo("No log files found")


@logs.command("clean")
@click.option(
    "--category",
    type=click.Choice(["all", "container", "database", "main"]),
    default="all",
    help="Clean logs by category",
)
@click.option(
    "--days",
    type=int,
    default=7,
    help="Keep logs from last N days (default: 7)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Remove without confirmation",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be removed without actually removing",
)
@click.pass_context
def logs_clean(ctx: click.Context, category: str, days: int, force: bool, dry_run: bool) -> None:
    """Clean old Poststack log files."""
    config = ctx.obj["config"]
    log_dir = Path(config.log_dir)
    
    if not log_dir.exists():
        click.echo("No log directory found")
        return
    
    import datetime
    import os
    
    cutoff_time = datetime.datetime.now() - datetime.timedelta(days=days)
    
    # Collect files to remove
    files_to_remove = []
    
    def add_old_files(pattern_dir, pattern):
        if not pattern_dir.exists():
            return
        for log_file in pattern_dir.glob(pattern):
            if datetime.datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_time:
                files_to_remove.append(log_file)
    
    categories_to_clean = [category] if category != "all" else ["main", "container", "database"]
    
    if "main" in categories_to_clean:
        add_old_files(log_dir, "poststack_*.log")
    
    if "container" in categories_to_clean:
        add_old_files(log_dir / "containers", "*.log")
    
    if "database" in categories_to_clean:
        add_old_files(log_dir / "database", "*.log")
    
    if not files_to_remove:
        click.echo(f"No log files older than {days} days found")
        return
    
    # Calculate total size
    total_size = sum(f.stat().st_size for f in files_to_remove)
    total_size_str = f"{total_size / 1024 / 1024:.1f} MB" if total_size > 1024*1024 else f"{total_size / 1024:.1f} KB"
    
    if dry_run:
        click.echo(f"🔍 Dry run: Would remove {len(files_to_remove)} files ({total_size_str}):")
        for log_file in sorted(files_to_remove, key=lambda x: x.stat().st_mtime, reverse=True):
            mtime = datetime.datetime.fromtimestamp(log_file.stat().st_mtime)
            click.echo(f"  {log_file.relative_to(log_dir)} ({mtime.strftime('%Y-%m-%d %H:%M')})")
        return
    
    click.echo(f"Found {len(files_to_remove)} log files older than {days} days ({total_size_str}):")
    for log_file in sorted(files_to_remove, key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
        mtime = datetime.datetime.fromtimestamp(log_file.stat().st_mtime)
        click.echo(f"  {log_file.relative_to(log_dir)} ({mtime.strftime('%Y-%m-%d %H:%M')})")
    
    if len(files_to_remove) > 5:
        click.echo(f"  ... and {len(files_to_remove) - 5} more")
    
    if not force:
        if not click.confirm(f"\nRemove {len(files_to_remove)} log files older than {days} days?"):
            click.echo("Cleanup cancelled")
            return
    
    # Remove files
    removed_count = 0
    for log_file in files_to_remove:
        try:
            log_file.unlink()
            removed_count += 1
        except Exception as e:
            click.echo(f"Failed to remove {log_file.name}: {e}")
    
    click.echo(f"🗑️  Removed {removed_count}/{len(files_to_remove)} log files ({total_size_str})")


@logs.command("size")
@click.pass_context
def logs_size(ctx: click.Context) -> None:
    """Show total size of log files."""
    config = ctx.obj["config"]
    log_dir = Path(config.log_dir)
    
    if not log_dir.exists():
        click.echo("No log directory found")
        return
    
    import os
    
    total_size = 0
    file_count = 0
    
    for root, dirs, files in os.walk(log_dir):
        for file in files:
            if file.endswith('.log'):
                file_path = Path(root) / file
                total_size += file_path.stat().st_size
                file_count += 1
    
    if total_size > 1024 * 1024 * 1024:  # GB
        size_str = f"{total_size / 1024 / 1024 / 1024:.1f} GB"
    elif total_size > 1024 * 1024:  # MB
        size_str = f"{total_size / 1024 / 1024:.1f} MB"
    elif total_size > 1024:  # KB
        size_str = f"{total_size / 1024:.1f} KB"
    else:
        size_str = f"{total_size} B"
    
    click.echo(f"📊 Log directory: {log_dir}")
    click.echo(f"Total log files: {file_count}")
    click.echo(f"Total size: {size_str}")


# Add command groups
cli.add_command(bootstrap)
cli.add_command(database)
cli.add_command(container)
cli.add_command(logs)


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
