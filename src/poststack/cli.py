"""
Command-line interface for Poststack (Simplified)

Provides a unified CLI for environment management, database operations, and building.
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
from .environment.config import EnvironmentConfigParser
from .environment.orchestrator import EnvironmentOrchestrator

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
    Poststack: PostgreSQL container and schema migration management

    Manage PostgreSQL containers and database schema migrations through a
    unified CLI.
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


# Build command (top-level)
@cli.command()
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable build cache",
)
@click.pass_context
def build(ctx: click.Context, no_cache: bool) -> None:
    """Build all required images (base, postgres, project containers)."""
    config = ctx.obj["config"]
    
    click.echo("🚀 Building all Poststack images...")
    
    try:
        builder = RealContainerBuilder(config)
        
        # Step 1: Build base image
        click.echo("\n📦 Building base-debian image...")
        base_result = builder.build_base_image(no_cache=no_cache)
        if not base_result.success:
            click.echo(f"❌ Failed to build base-debian: {base_result.logs}")
            sys.exit(1)
        click.echo(f"✅ base-debian built ({base_result.build_time:.1f}s)")
        
        # Step 2: Build postgres image
        click.echo("\n📦 Building postgres image...")
        postgres_result = builder.build_postgres_image(no_cache=no_cache)
        if not postgres_result.success:
            click.echo(f"❌ Failed to build postgres: {postgres_result.logs}")
            sys.exit(1)
        click.echo(f"✅ postgres built ({postgres_result.build_time:.1f}s)")
        
        # Step 3: Build project containers
        click.echo("\n📦 Building project containers...")
        project_containers = discover_project_containers(config)
        
        if project_containers:
            click.echo(f"Found {len(project_containers)} project container(s):")
            for name, info in project_containers.items():
                click.echo(f"  - {name}: {info['description']}")
            
            for name, container_info in project_containers.items():
                click.echo(f"\n🔨 Building {name}...")
                result = builder.build_project_container(
                    name=name,
                    dockerfile_path=container_info["dockerfile"],
                    context_path=container_info["context"],
                    image_tag=container_info["image"],
                    no_cache=no_cache
                )
                if result.status == BuildStatus.SUCCESS:
                    click.echo(f"✅ {name} built ({result.build_time:.1f}s)")
                else:
                    click.echo(f"❌ {name} failed: {result.logs}")
                    sys.exit(1)
        else:
            click.echo("No project containers found")
        
        click.echo("\n🎉 All images built successfully!")
        
    except Exception as e:
        click.echo(f"❌ Build failed: {e}", err=True)
        sys.exit(1)


# Environment management command group
@cli.group()
@click.pass_context
def env(ctx: click.Context) -> None:
    """Manage environments (start, stop, status, switch)."""
    pass


@env.command("list")
@click.pass_context
def env_list(ctx: click.Context) -> None:
    """List available environments."""
    config = ctx.obj["config"]
    
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        current_env = project_config.environment
        
        click.echo(f"Available environments:")
        for env_name in sorted(project_config.environments.keys()):
            env_config = project_config.environments[env_name]
            marker = "*" if env_name == current_env else " "
            click.echo(f"  {marker} {env_name}")
            
            # Show basic info
            postgres = env_config.postgres
            click.echo(f"      Database: {postgres.database} (port {postgres.port})")
            
    except Exception as e:
        click.echo(f"❌ Failed to list environments: {e}", err=True)
        sys.exit(1)


@env.command("start")
@click.argument("environment", required=False)
@click.pass_context
def env_start(ctx: click.Context, environment: Optional[str]) -> None:
    """Start an environment (current or specified)."""
    config = ctx.obj["config"]
    
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
            click.echo(f"Using current environment: {environment}")
        
        if environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            click.echo(f"Available environments: {', '.join(project_config.environments.keys())}")
            sys.exit(1)
        
        click.echo(f"🚀 Starting environment: {environment}")
        
        # Use the orchestrator to start the environment
        orchestrator = EnvironmentOrchestrator(config)
        result = asyncio.run(orchestrator.start_environment(environment))
        
        if result.success:
            click.echo(f"✅ Environment '{environment}' started successfully")
            click.echo(f"   PostgreSQL: {result.postgres_started}")
            if result.init_results:
                click.echo(f"   Init containers: {len([r for r in result.init_results if r.success])}/{len(result.init_results)} succeeded")
            if result.deployment_result:
                click.echo(f"   Deployment: {'succeeded' if result.deployment_result.success else 'failed'}")
        else:
            click.echo(f"❌ Failed to start environment: {result.error_message}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to start environment: {e}", err=True)
        sys.exit(1)


@env.command("stop")
@click.argument("environment", required=False)
@click.option(
    "--keep-postgres",
    is_flag=True,
    help="Keep PostgreSQL running when stopping environment",
)
@click.option(
    "--rm",
    is_flag=True,
    help="Remove containers after stopping",
)
@click.pass_context
def env_stop(ctx: click.Context, environment: Optional[str], keep_postgres: bool, rm: bool) -> None:
    """Stop an environment."""
    config = ctx.obj["config"]
    
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
            click.echo(f"Using current environment: {environment}")
        
        if environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            sys.exit(1)
        
        action = "🛑 Stopping and removing" if rm else "🛑 Stopping"
        click.echo(f"{action} environment: {environment}")
        
        orchestrator = EnvironmentOrchestrator(config)
        success = asyncio.run(orchestrator.stop_environment(environment, keep_postgres=keep_postgres, remove=rm))
        
        if success:
            action_text = "stopped and removed" if rm else "stopped"
            click.echo(f"✅ Environment '{environment}' {action_text}")
        else:
            action_text = "stop and remove" if rm else "stop"
            click.echo(f"❌ Failed to {action_text} environment properly")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to stop environment: {e}", err=True)
        sys.exit(1)


@env.command("restart")
@click.argument("environment", required=False)
@click.pass_context
def env_restart(ctx: click.Context, environment: Optional[str]) -> None:
    """Restart an environment (always does clean restart with container removal)."""
    config = ctx.obj["config"]
    
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
            click.echo(f"Using current environment: {environment}")
        
        click.echo(f"🔄 Restarting environment: {environment}")
        
        # Stop first (restart should always remove containers for clean start)
        orchestrator = EnvironmentOrchestrator(config)
        stop_success = asyncio.run(orchestrator.stop_environment(environment, keep_postgres=False, remove=True))
        
        if not stop_success:
            click.echo(f"⚠️  Some containers failed to stop and remove cleanly, continuing with restart...")
        
        # Start again
        result = asyncio.run(orchestrator.start_environment(environment))
        
        if result.success:
            click.echo(f"✅ Environment '{environment}' restarted successfully")
        else:
            click.echo(f"❌ Failed to restart environment: {result.error_message}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to restart environment: {e}", err=True)
        sys.exit(1)


@env.command("status")
@click.argument("environment", required=False)
@click.pass_context
def env_status(ctx: click.Context, environment: Optional[str]) -> None:
    """Show environment status."""
    config = ctx.obj["config"]
    
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
        
        if environment and environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            sys.exit(1)
        
        orchestrator = EnvironmentOrchestrator(config)
        
        if environment:
            # Show specific environment status
            click.echo(f"📊 Environment: {environment}")
            if environment == project_config.environment:
                click.echo("   (current environment)")
            click.echo("-" * 40)
            
            status = asyncio.run(orchestrator.get_environment_status(environment))
            
            # PostgreSQL status
            if status['postgres']['running']:
                click.echo(f"✅ PostgreSQL: running")
                click.echo(f"   Container: {status['postgres']['container_name']}")
                click.echo(f"   Port: {status['postgres']['port']}")
            else:
                click.echo(f"❌ PostgreSQL: {status['postgres']['status']}")
            
            # Deployment status
            if status['deployment_containers']:
                click.echo(f"\n🚢 Deployment Containers:")
                for container in status['deployment_containers']:
                    icon = "✅" if container['running'] else "❌"
                    click.echo(f"   {icon} {container['name']}: {container['status']}")
            else:
                click.echo(f"\n🚢 No deployment containers")
                
        else:
            # Show all environments status
            click.echo("📊 All Environments Status")
            click.echo("=" * 50)
            
            for env_name in sorted(project_config.environments.keys()):
                is_current = env_name == project_config.environment
                marker = "(*)" if is_current else ""
                click.echo(f"\n{env_name} {marker}")
                click.echo("-" * 40)
                
                status = asyncio.run(orchestrator.get_environment_status(env_name))
                
                # Quick summary
                postgres_icon = "✅" if status['postgres']['running'] else "❌"
                running_containers = len([c for c in status['deployment_containers'] if c['running']])
                total_containers = len(status['deployment_containers'])
                
                click.echo(f"PostgreSQL: {postgres_icon}")
                if total_containers > 0:
                    click.echo(f"Containers: {running_containers}/{total_containers} running")
                else:
                    click.echo("Containers: none")
                    
    except Exception as e:
        click.echo(f"❌ Failed to get status: {e}", err=True)
        sys.exit(1)


@env.command("switch")
@click.argument("environment")
@click.pass_context
def env_switch(ctx: click.Context, environment: str) -> None:
    """Switch to a different environment."""
    config = ctx.obj["config"]
    
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        if environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            click.echo(f"Available environments: {', '.join(project_config.environments.keys())}")
            sys.exit(1)
        
        if environment == project_config.environment:
            click.echo(f"Already on environment '{environment}'")
            return
        
        # Update the configuration file
        config_path = Path(config.project_config_file)
        
        # Read the file
        with open(config_path, 'r') as f:
            lines = f.readlines()
        
        # Update the environment line
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith('environment:'):
                lines[i] = f"environment: {environment}  # Currently selected environment\n"
                updated = True
                break
        
        if not updated:
            click.echo("❌ Could not find 'environment:' line in .poststack.yml")
            sys.exit(1)
        
        # Write back
        with open(config_path, 'w') as f:
            f.writelines(lines)
        
        click.echo(f"✅ Switched to environment '{environment}'")
        click.echo(f"   Run 'poststack env start' to start this environment")
        
    except Exception as e:
        click.echo(f"❌ Failed to switch environment: {e}", err=True)
        sys.exit(1)


# Database operations (rename from 'database' to 'db')
cli.add_command(database, name="db")


# Add missing import
import asyncio
import shutil
import os
from .init import InitCommand


# Init command
@cli.command()
@click.option("--postgres", is_flag=True, help="Include PostgreSQL container files")
@click.option("--deploy", is_flag=True, help="Include PostgreSQL deployment files")
@click.option("--all", "include_all", is_flag=True, help="Include all PostgreSQL files")
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.pass_context
def init(ctx: click.Context, postgres: bool, deploy: bool, include_all: bool, force: bool) -> None:
    """Initialize project with PostgreSQL configuration files.
    
    Makes PostgreSQL container and deployment configuration visible and customizable
    by copying template files to your project's containers/ and deploy/ directories.
    
    Examples:
        poststack init --all          # Copy all PostgreSQL files
        poststack init --postgres     # Copy only container files  
        poststack init --deploy       # Copy only deployment files
        poststack init --all --force  # Overwrite existing files
    """
    config = ctx.obj["config"]
    
    try:
        # Initialize the init command handler
        init_cmd = InitCommand(config)
        
        # Determine what to include
        if include_all:
            include_postgres = True
            include_deploy = True
        else:
            include_postgres = postgres
            include_deploy = deploy
            
            # Default to all if none specified
            if not include_postgres and not include_deploy:
                include_postgres = True
                include_deploy = True
        
        click.echo("🚀 Initializing project with PostgreSQL configuration files...")
        
        result = init_cmd.initialize_project(
            include_postgres=include_postgres,
            include_deploy=include_deploy,
            force=force
        )
        
        if result.success:
            click.echo("✅ Project initialization completed successfully!")
            
            if result.postgres_files_created:
                click.echo(f"\n📦 PostgreSQL container files created:")
                for file_path in result.postgres_files_created:
                    click.echo(f"   - {file_path}")
            
            if result.deploy_files_created:
                click.echo(f"\n🚢 Deployment files created:")
                for file_path in result.deploy_files_created:
                    click.echo(f"   - {file_path}")
            
            if result.files_skipped:
                click.echo(f"\n⚠️  Files skipped (already exist, use --force to overwrite):")
                for file_path in result.files_skipped:
                    click.echo(f"   - {file_path}")
                    
            click.echo(f"\n📖 Documentation created:")
            for file_path in result.docs_created:
                click.echo(f"   - {file_path}")
                
            click.echo(f"\n🎯 Next steps:")
            click.echo(f"   1. Review and customize the generated files")
            click.echo(f"   2. Run 'poststack build' to build with your configuration")
            click.echo(f"   3. Run 'poststack env start' to deploy")
        else:
            click.echo(f"❌ Initialization failed: {result.error_message}")
            if result.validation_errors:
                click.echo("Validation errors:")
                for error in result.validation_errors:
                    click.echo(f"   - {error}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to initialize project: {e}", err=True)
        sys.exit(1)


# Configuration commands
@cli.command("config-show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration."""
    config = ctx.obj["config"]

    click.echo("Current Poststack Configuration:")
    click.echo("=" * 40)
    click.echo(f"Log Level           : {config.log_level}")
    click.echo(f"Log Dir             : {config.log_dir}")
    click.echo(f"Verbose             : {config.verbose}")
    click.echo(f"Container Runtime   : {config.container_runtime}")
    click.echo(f"Container Registry  : {config.container_registry}")
    click.echo(f"Project Config File : {config.project_config_file}")
    click.echo(f"Debug               : {config.debug}")
    click.echo(f"Test Mode           : {config.test_mode}")
    
    # Show current environment
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        click.echo(f"\nCurrent Environment : {project_config.environment}")
        env_config = project_config.environments[project_config.environment]
        click.echo(f"  Database          : {env_config.postgres.database}")
        click.echo(f"  Port              : {env_config.postgres.port}")
    except:
        pass


@cli.command("config-validate")
@click.pass_context
def config_validate(ctx: click.Context) -> None:
    """Validate current configuration."""
    config = ctx.obj["config"]

    click.echo("🔍 Validating configuration...")

    errors = []
    warnings = []

    # Check container runtime
    try:
        import subprocess

        result = subprocess.run(
            [config.container_runtime, "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"Container runtime '{config.container_runtime}' not available")
    except FileNotFoundError:
        errors.append(f"Container runtime '{config.container_runtime}' not found")

    # Check project configuration
    try:
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        click.echo(f"✅ Found {len(project_config.environments)} environment(s)")
    except Exception as e:
        warnings.append(f"No .poststack.yml configuration found or invalid: {e}")

    # Check log directory
    log_path = Path(config.log_dir)
    if not log_path.exists():
        warnings.append(f"Log directory '{config.log_dir}' does not exist (will be created)")

    # Display results
    if errors:
        click.echo("\n❌ Configuration errors:")
        for error in errors:
            click.echo(f"   - {error}")

    if warnings:
        click.echo("\n⚠️  Configuration warnings:")
        for warning in warnings:
            click.echo(f"   - {warning}")

    if not errors and not warnings:
        click.echo("✅ Configuration is valid")

    if errors:
        sys.exit(1)


@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Display version information."""
    try:
        from importlib.metadata import version as get_version
    except ImportError:
        from importlib_metadata import version as get_version

    try:
        poststack_version = get_version("poststack")
    except Exception:
        poststack_version = "development"

    click.echo(f"Poststack version: {poststack_version}")
    
    # Show container runtime version
    config = ctx.obj["config"]
    try:
        import subprocess
        result = subprocess.run(
            [config.container_runtime, "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            runtime_info = result.stdout.strip().split('\n')[0]
            click.echo(f"Container runtime: {runtime_info}")
    except:
        pass


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()