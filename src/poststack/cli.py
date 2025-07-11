"""
Command-line interface for Poststack

Provides a CLI for managing PostgreSQL containers and database schema migrations.
"""

import sys
from pathlib import Path
from typing import Dict, Optional

import click

from .config import PoststackConfig, load_config
from .database import database
from .logging_config import setup_logging
from .models import BuildStatus
from .project_containers import discover_project_containers
from .real_container_builder import RealContainerBuilder
from .container_runtime import ContainerLifecycleManager

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
    Poststack: PostgreSQL container and schema migration management

    Manage PostgreSQL containers and database schema migrations through a unified CLI.
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
    type=click.Choice(["all", "base-debian", "postgres"]),
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


@container.command("build-project")
@click.option(
    "--container",
    help="Specific project container to build (default: all discovered containers)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable build cache",
)
@click.pass_context
def container_build_project(
    ctx: click.Context,
    container: Optional[str],
    no_cache: bool,
) -> None:
    """Build project-level containers."""
    config = ctx.obj["config"]
    
    
    click.echo("🚀 Building project containers...")
    
    try:
        # Discover project containers
        project_containers = discover_project_containers(config)
        
        if not project_containers:
            click.echo(f"No project containers found in {config.project_containers_path}")
            click.echo("Create a containers/ directory with Dockerfile to define project containers.")
            return
        
        # Filter by specific container if requested
        if container:
            if container not in project_containers:
                click.echo(f"❌ Container '{container}' not found in project containers")
                click.echo(f"Available containers: {', '.join(project_containers.keys())}")
                sys.exit(1)
            containers_to_build = {container: project_containers[container]}
        else:
            containers_to_build = project_containers
        
        click.echo(f"Found {len(containers_to_build)} project container(s) to build:")
        for name, info in containers_to_build.items():
            click.echo(f"  - {name}: {info['description']}")
        
        # Build containers
        builder = RealContainerBuilder(config)
        results = {}
        
        for name, container_info in containers_to_build.items():
            click.echo(f"\n🔨 Building {name}...")
            
            # Build the container using podman/docker
            result = builder.build_project_container(
                name=name,
                dockerfile_path=container_info["dockerfile"],
                context_path=container_info["context"],
                image_tag=container_info["image"],
                no_cache=no_cache
            )
            results[name] = result
        
        # Display results
        click.echo("\n📊 Build Results:")
        click.echo("-" * 40)
        
        successful = 0
        for name, result in results.items():
            if result.status == BuildStatus.SUCCESS:
                click.echo(f"✅ {name}: {result.status.value} ({result.build_time:.1f}s)")
                successful += 1
            else:
                click.echo(f"❌ {name}: {result.status.value}")
        
        click.echo(f"\n🎉 Successfully built {successful}/{len(results)} project container(s)")
        
        if successful < len(results):
            click.echo(f"\n⚠️  {len(results) - successful} build(s) failed")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Project container build failed: {e}", err=True)
        sys.exit(1)


@container.command("start-project")
@click.option(
    "--container",
    help="Specific project container to start (default: all discovered containers)",
)
@click.option(
    "--port",
    type=int,
    help="Host port for the container (overrides default port mapping)",
)
@click.option(
    "--env-file",
    type=click.Path(exists=True, path_type=Path),
    help="Environment file to load for container",
)
@click.option(
    "--volume",
    multiple=True,
    help="Volume mappings in format host_path:container_path",
)
@click.option(
    "--wait",
    is_flag=True,
    help="Wait for container to be ready before returning",
)
@click.pass_context
def container_start_project(
    ctx: click.Context,
    container: Optional[str],
    port: Optional[int],
    env_file: Optional[Path],
    volume: tuple,
    wait: bool,
) -> None:
    """Start project-level containers."""
    config = ctx.obj["config"]
    
    click.echo("🚀 Starting project containers...")
    
    try:
        # Discover project containers
        project_containers = discover_project_containers(config)
        
        if not project_containers:
            click.echo(f"No project containers found in {config.project_containers_path}")
            click.echo("Create a containers/ directory with Dockerfile to define project containers.")
            return
        
        # Filter by specific container if requested
        if container:
            if container not in project_containers:
                click.echo(f"❌ Container '{container}' not found in project containers")
                click.echo(f"Available containers: {', '.join(project_containers.keys())}")
                sys.exit(1)
            containers_to_start = {container: project_containers[container]}
        else:
            containers_to_start = project_containers
        
        click.echo(f"Found {len(containers_to_start)} project container(s) to start:")
        for name, info in containers_to_start.items():
            click.echo(f"  - {name}: {info['description']}")
        
        # Start containers
        lifecycle_manager = ContainerLifecycleManager(config)
        results = {}
        
        # Load environment variables from file if specified
        env_vars = {}
        if env_file:
            env_vars = _load_env_file(env_file)
        
        # Parse volume mappings
        volume_mappings = {}
        for vol in volume:
            if ':' in vol:
                host_path, container_path = vol.split(':', 1)
                volume_mappings[host_path] = container_path
        
        for name, container_info in containers_to_start.items():
            click.echo(f"\n🔨 Starting {name}...")
            
            # Get port mappings
            port_mappings = container_info["default_port_mappings"]
            if port and port_mappings:
                # Override first port mapping with custom port
                first_container_port = list(port_mappings.values())[0]
                port_mappings = {port: first_container_port}
            
            # Check for container-specific port override
            custom_port = config.get_project_container_env_var(name, 'port')
            if custom_port and port_mappings:
                first_container_port = list(port_mappings.values())[0]
                port_mappings = {custom_port: first_container_port}
            
            # Start the container
            result = lifecycle_manager.project_runner.start_project_container(
                container_name=name,
                image_name=container_info["image"],
                port_mappings=port_mappings,
                environment=env_vars,
                volumes=volume_mappings,
                wait_for_ready=wait,
                timeout=120,
            )
            results[name] = result
            
            if result.success:
                full_name = config.get_project_container_name(name)
                click.echo(f"✅ {name} started successfully")
                click.echo(f"   Container: {full_name}")
                if port_mappings:
                    for host_port, container_port in port_mappings.items():
                        click.echo(f"   Port: {host_port} -> {container_port}")
            else:
                click.echo(f"❌ {name} failed to start: {result.logs}")
        
        # Display results summary
        successful = sum(1 for r in results.values() if r.success)
        click.echo(f"\n🎉 Successfully started {successful}/{len(results)} project container(s)")
        
        if successful < len(results):
            click.echo(f"\n⚠️  {len(results) - successful} container(s) failed to start")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Project container start failed: {e}", err=True)
        sys.exit(1)


@container.command("stop-project")
@click.option(
    "--container",
    help="Specific project container to stop (default: all running project containers)",
)
@click.option(
    "--all-project",
    is_flag=True,
    help="Stop all project containers",
)
@click.pass_context
def container_stop_project(
    ctx: click.Context,
    container: Optional[str],
    all_project: bool,
) -> None:
    """Stop project-level containers."""
    config = ctx.obj["config"]
    
    try:
        lifecycle_manager = ContainerLifecycleManager(config)
        
        if container:
            # Stop specific container
            full_name = config.get_project_container_name(container)
            click.echo(f"🛑 Stopping project container: {container}")
            
            result = lifecycle_manager.project_runner.stop_container(full_name)
            if result.success:
                click.echo(f"✅ Stopped {container}")
            else:
                click.echo(f"❌ Failed to stop {container}: {result.logs}")
                sys.exit(1)
                
        elif all_project:
            # Stop all project containers
            click.echo("🛑 Stopping all project containers...")
            
            running_containers = lifecycle_manager.project_runner.get_running_project_containers()
            if not running_containers:
                click.echo("No running project containers found")
                return
            
            stopped_count = 0
            for container_info in running_containers:
                container_name = container_info['container_name']
                try:
                    result = lifecycle_manager.project_runner.stop_container(container_name)
                    if result.success:
                        click.echo(f"✅ Stopped {container_name}")
                        stopped_count += 1
                    else:
                        click.echo(f"❌ Failed to stop {container_name}")
                except Exception as e:
                    click.echo(f"❌ Error stopping {container_name}: {e}")
            
            click.echo(f"\n🎉 Stopped {stopped_count}/{len(running_containers)} project containers")
        else:
            click.echo("❓ Please specify --container NAME or --all-project")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to stop project containers: {e}", err=True)
        sys.exit(1)


def _load_env_file(env_file: Path) -> Dict[str, str]:
    """Load environment variables from file."""
    env_vars = {}
    try:
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    except Exception as e:
        logger.warning(f"Failed to load env file {env_file}: {e}")
    
    return env_vars


@container.command("list")
@click.pass_context
def container_list(ctx: click.Context) -> None:
    """List built Poststack container images."""
    config = ctx.obj["config"]
    
    try:
        builder = RealContainerBuilder(config)
        
        images = ["poststack/base-debian:latest", "poststack/postgres:latest"]
        
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
                "poststack/postgres:15"
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


@container.command("start")
@click.option(
    "--postgres-port",
    type=int,
    default=None,
    help="PostgreSQL host port (uses config default if not specified)",
)
@click.option(
    "--wait-timeout",
    type=int,
    default=120,
    help="Timeout for waiting for services to be ready (default: 120s)",
)
@click.pass_context
def container_start(ctx: click.Context, postgres_port: int, wait_timeout: int) -> None:
    """Start PostgreSQL container."""
    config = ctx.obj["config"]
    
    # Use configured port if not specified
    if postgres_port is None:
        postgres_port = config.postgres_host_port
    
    click.echo("🚀 Starting PostgreSQL container...")
    
    try:
        lifecycle_manager = ContainerLifecycleManager(config)
        
        postgres_result, health_result = lifecycle_manager.start_test_environment(
            postgres_port=postgres_port,
            cleanup_on_failure=True,
        )
        
        if postgres_result.success and health_result and health_result.passed:
            click.echo(f"✅ PostgreSQL container started successfully")
            click.echo(f"   Container: {postgres_result.container_name}")
            click.echo(f"   Port: {postgres_port}")
            click.echo(f"   Health: {health_result.message}")
            click.echo(f"   Database URL: postgresql://poststack:poststack_dev@localhost:{postgres_port}/poststack")
            
            # Show running containers
            running = lifecycle_manager.get_running_containers()
            if running:
                click.echo(f"\n📦 Running containers: {', '.join(running)}")
        else:
            click.echo("❌ Failed to start test environment")
            if not postgres_result.success:
                click.echo(f"   PostgreSQL error: {postgres_result.logs}")
            if health_result and not health_result.passed:
                click.echo(f"   Health check error: {health_result.message}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to start containers: {e}", err=True)
        sys.exit(1)


@container.command("stop")
@click.option(
    "--all",
    "stop_all",
    is_flag=True,
    help="Stop all running containers",
)
@click.argument("container_names", nargs=-1)
@click.pass_context
def container_stop(ctx: click.Context, stop_all: bool, container_names: tuple) -> None:
    """Stop running containers."""
    config = ctx.obj["config"]
    
    try:
        lifecycle_manager = ContainerLifecycleManager(config)
        
        if stop_all:
            click.echo("🛑 Stopping all test containers...")
            success = lifecycle_manager.cleanup_test_environment()
            
            if success:
                click.echo("✅ All containers stopped and cleaned up")
            else:
                click.echo("⚠️  Some containers failed to stop cleanly")
                sys.exit(1)
        elif container_names:
            click.echo(f"🛑 Stopping containers: {', '.join(container_names)}")
            
            stopped_count = 0
            for container_name in container_names:
                try:
                    result = lifecycle_manager.postgres_runner.stop_container(container_name)
                    if result.success:
                        click.echo(f"✅ Stopped {container_name}")
                        stopped_count += 1
                    else:
                        click.echo(f"❌ Failed to stop {container_name}")
                except Exception as e:
                    click.echo(f"❌ Error stopping {container_name}: {e}")
            
            click.echo(f"\n🎉 Stopped {stopped_count}/{len(container_names)} containers")
        else:
            click.echo("❓ Please specify container names or use --all flag")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to stop containers: {e}", err=True)
        sys.exit(1)


@container.command("remove")
@click.option(
    "--force",
    is_flag=True,
    help="Force removal of containers (even if running)",
)
@click.argument("container_names", nargs=-1)
@click.pass_context
def container_remove(ctx: click.Context, force: bool, container_names: tuple) -> None:
    """Remove containers."""
    config = ctx.obj["config"]
    
    if not container_names:
        click.echo("❓ Please specify container names to remove")
        sys.exit(1)
    
    try:
        lifecycle_manager = ContainerLifecycleManager(config)
        
        click.echo(f"🗑️  Removing containers: {', '.join(container_names)}")
        
        removed_count = 0
        for container_name in container_names:
            try:
                result = lifecycle_manager.postgres_runner.remove_container(container_name, force=force)
                if result.success:
                    click.echo(f"✅ Removed {container_name}")
                    removed_count += 1
                else:
                    click.echo(f"❌ Failed to remove {container_name}: {result.message}")
            except Exception as e:
                click.echo(f"❌ Error removing {container_name}: {e}")
        
        click.echo(f"\n🎉 Removed {removed_count}/{len(container_names)} containers")
        
    except Exception as e:
        click.echo(f"❌ Failed to remove containers: {e}", err=True)
        sys.exit(1)


@container.command("status")
@click.pass_context
def container_status(ctx: click.Context) -> None:
    """Show status of Poststack containers."""
    config = ctx.obj["config"]
    
    try:
        lifecycle_manager = ContainerLifecycleManager(config)
        
        # Check configured container name
        container_names = [
            config.postgres_container_name,
        ]
        
        click.echo("📊 Container Status:")
        click.echo("-" * 50)
        
        running_count = 0
        for container_name in container_names:
            status = lifecycle_manager.postgres_runner.get_container_status(container_name)
            
            if status:
                status_icon = "✅" if status.running else "⏹️"
                click.echo(f"{status_icon} {container_name}")
                click.echo(f"   Status: {status.status.value}")
                click.echo(f"   Image: {status.image_name}")
                click.echo(f"   ID: {status.container_id[:12] if status.container_id else 'N/A'}")
                
                if status.running:
                    running_count += 1
                    # Perform health check
                    if "postgres" in container_name:
                        health = lifecycle_manager.postgres_runner.health_check_postgres(container_name)
                        health_icon = "✅" if health.passed else "❌"
                        click.echo(f"   Health: {health_icon} {health.message}")
            else:
                click.echo(f"❌ {container_name} (not found)")
        
        # Check project containers
        project_containers = lifecycle_manager.project_runner.get_running_project_containers()
        if project_containers:
            click.echo("\n📦 Project Containers:")
            click.echo("-" * 50)
            
            for container_info in project_containers:
                container_name = container_info['container_name']
                status = lifecycle_manager.project_runner.get_container_status(container_name)
                
                if status:
                    status_icon = "✅" if status.running else "⏹️"
                    click.echo(f"{status_icon} {container_name}")
                    click.echo(f"   Status: {status.status.value}")
                    click.echo(f"   Image: {status.image_name}")
                    click.echo(f"   ID: {status.container_id[:12] if status.container_id else 'N/A'}")
                    click.echo(f"   Ports: {container_info.get('ports', 'N/A')}")
                    
                    if status.running:
                        running_count += 1
        
        click.echo("-" * 50)
        click.echo(f"Running: {running_count} total containers")
        
    except Exception as e:
        click.echo(f"❌ Failed to get container status: {e}", err=True)
        sys.exit(1)


@container.command("health")
@click.argument("container_name", required=False)
@click.option(
    "--postgres-port",
    type=int,
    default=5433,
    help="PostgreSQL port for health check (default: 5433)",
)
@click.pass_context
def container_health(ctx: click.Context, container_name: str, postgres_port: int) -> None:
    """Perform health checks on containers."""
    config = ctx.obj["config"]
    
    try:
        lifecycle_manager = ContainerLifecycleManager(config)
        
        if not container_name:
            # Check configured container
            container_name = config.postgres_container_name
        
        click.echo(f"🏥 Performing health check on {container_name}...")
        
        # Basic running check
        basic_health = lifecycle_manager.postgres_runner.health_check(container_name)
        click.echo(f"   Running: {'✅' if basic_health.passed else '❌'} {basic_health.message}")
        
        # PostgreSQL specific health check
        if "postgres" in container_name:
            postgres_health = lifecycle_manager.postgres_runner.health_check_postgres(
                container_name, port=postgres_port
            )
            click.echo(f"   PostgreSQL: {'✅' if postgres_health.passed else '❌'} {postgres_health.message}")
            
            if postgres_health.response_time:
                click.echo(f"   Response time: {postgres_health.response_time:.2f}s")
            
            # Side effects verification
            side_effects = lifecycle_manager.postgres_runner.verify_postgres_side_effects(
                container_name, postgres_port
            )
            
            click.echo("   Side effects:")
            for check, result in side_effects.items():
                icon = "✅" if result else "❌"
                click.echo(f"     {icon} {check.replace('_', ' ').title()}")
        
        # Database connectivity check if database URL available
        if config.is_database_configured:
            database_url = f"postgresql://poststack:poststack_dev@localhost:{postgres_port}/poststack"
            # Basic connectivity verification already done by PostgreSQL health check
            click.echo(f"   Database: {'✅' if postgres_health.passed else '❌'} {postgres_health.message}")
        
    except Exception as e:
        click.echo(f"❌ Health check failed: {e}", err=True)
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

    # Check log directory
    try:
        config.create_directories()
        click.echo("✅ Log directories created/verified")
    except Exception as e:
        issues.append(f"❌ Log directory issue: {e}")

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
