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
from .volumes import volumes
from .logging_config import setup_logging
from .project_containers import discover_project_containers
from .real_container_builder import RealContainerBuilder
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
@click.argument('services', nargs=-1, type=str)
@click.pass_context
def build(ctx: click.Context, no_cache: bool, services: tuple) -> None:
    """Build images. If no services specified, builds all images (base, postgres, project containers).
    
    SERVICES: Optional list of specific services to build (postgres, apache, mail, etc.)
    """
    config = ctx.obj["config"]
    
    # Determine what to build based on services argument
    build_all = len(services) == 0
    services_set = set(services) if services else set()
    
    if build_all:
        click.echo("🚀 Building all Poststack images...")
    else:
        click.echo(f"🚀 Building specified services: {', '.join(services)}...")
    
    try:
        builder = RealContainerBuilder(config)
        
        # Always build base image when building project containers or postgres
        # (since they depend on it)
        needs_base = build_all or 'postgres' in services_set or any(s not in ['postgres'] for s in services_set)
        
        if needs_base:
            # Step 1: Build base image
            click.echo("\n📦 Building base-debian image...")
            base_result = builder.build_base_image()
            if not base_result.success:
                click.echo(f"❌ Failed to build base-debian: {base_result.stderr}")
                sys.exit(1)
            click.echo(f"✅ base-debian built ({base_result.build_time:.1f}s)")
        
        # Step 2: Build postgres image if requested or building all
        if build_all or 'postgres' in services_set:
            click.echo("\n📦 Building postgres image...")
            postgres_result = builder.build_postgres_image()
            if not postgres_result.success:
                click.echo(f"❌ Failed to build postgres: {postgres_result.stderr}")
                sys.exit(1)
            click.echo(f"✅ postgres built ({postgres_result.build_time:.1f}s)")
        
        # Step 3: Build project containers
        project_containers = discover_project_containers(config)
        
        # Filter project containers based on services argument
        if build_all:
            containers_to_build = project_containers
        else:
            containers_to_build = {
                name: info for name, info in project_containers.items() 
                if name in services_set
            }
            
            # Check for invalid service names
            valid_services = {'postgres'} | set(project_containers.keys())
            invalid_services = services_set - valid_services
            if invalid_services:
                click.echo(f"❌ Unknown services: {', '.join(invalid_services)}")
                click.echo(f"Available services: {', '.join(sorted(valid_services))}")
                sys.exit(1)
        
        if containers_to_build:
            if build_all:
                click.echo(f"\n📦 Building all {len(containers_to_build)} project containers...")
            else:
                click.echo(f"\n📦 Building {len(containers_to_build)} specified project containers...")
                
            for name, info in containers_to_build.items():
                click.echo(f"  - {name}: {info['description']}")
            
            for name, container_info in containers_to_build.items():
                click.echo(f"\n🔨 Building {name}...")
                result = builder.build_project_container(
                    name=name,
                    dockerfile_path=container_info["dockerfile"],
                    context_path=container_info["context"],
                    image_tag=container_info["image"],
                    no_cache=no_cache
                )
                if result.success:
                    click.echo(f"✅ {name} built ({result.build_time:.1f}s)")
                else:
                    error_msg = result.stderr or "Unknown error"
                    click.echo(f"❌ {name} failed: {error_msg}")
                    sys.exit(1)
        elif not build_all:
            click.echo("No matching project containers found to build")
        
        if build_all:
            click.echo("\n🎉 All images built successfully!")
        else:
            click.echo(f"\n🎉 Specified services built successfully!")
        
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
@click.option("--dry-run", is_flag=True, help="Show what would be deployed without actually deploying")
@click.pass_context
def env_start(ctx: click.Context, environment: Optional[str], dry_run: bool) -> None:
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
        
        if dry_run:
            click.echo(f"🔍 Dry run: validating environment templates for '{environment}'")
            
            # Use the orchestrator to validate templates without deploying
            orchestrator = EnvironmentOrchestrator(config)
            result = asyncio.run(orchestrator.validate_environment(environment))
            
            if result.success:
                click.echo(f"✅ Environment '{environment}' templates are valid")
                click.echo(f"\n📋 Would deploy:")
                if result.init_results:
                    click.echo(f"   Init containers: {len(result.init_results)}")
                    for init_result in result.init_results:
                        file_name = init_result.file_path.split('/')[-1] if init_result.file_path else "unknown"
                        click.echo(f"     - {file_name}")
                if result.deployment_results:
                    click.echo(f"   Main deployments: {len(result.deployment_results)}")
                    for deploy_result in result.deployment_results:
                        file_name = deploy_result.file_path.split('/')[-1] if deploy_result.file_path else "unknown"
                        click.echo(f"     - {file_name}")
                
                click.echo(f"\n📝 Run without --dry-run to actually deploy")
            else:
                click.echo(f"❌ Template validation failed: {result.error_message}")
                sys.exit(1)
        else:
            click.echo(f"🚀 Starting environment: {environment}")
            
            # Use the orchestrator to start the environment
            orchestrator = EnvironmentOrchestrator(config)
            result = asyncio.run(orchestrator.start_environment(environment))
            
            if result.success:
                click.echo(f"✅ Environment '{environment}' started successfully")
                if result.init_results:
                    click.echo(f"   Init containers: {len([r for r in result.init_results if r.success])}/{len(result.init_results)} succeeded")
                if result.deployment_results:
                    successful_deployments = len([r for r in result.deployment_results if r.success])
                    click.echo(f"   Deployments: {successful_deployments}/{len(result.deployment_results)} succeeded")
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
        success = asyncio.run(orchestrator.stop_environment(environment, remove=rm))
        
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
        stop_success = asyncio.run(orchestrator.stop_environment(environment, remove=True))
        
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
cli.add_command(volumes, name="volumes")


# Service operations command group
@cli.group()
@click.pass_context
def service(ctx: click.Context) -> None:
    """Manage services and perform service-specific operations."""
    pass


@service.command("create-user")
@click.option("--username", required=True, help="Username for the new user")
@click.option("--password", required=True, help="Password for the new user")
@click.option("--email", help="Email address for the new user")
@click.option("--role", type=click.Choice(["user", "admin"]), default="user", help="User role")
@click.option("--environment", help="Environment to target (defaults to current)")
@click.pass_context
def service_create_user(ctx: click.Context, username: str, password: str, email: Optional[str], role: str, environment: Optional[str]) -> None:
    """Create a new user via web service API."""
    config = ctx.obj["config"]
    
    try:
        from .service_operations import ServiceOperations
        
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
            click.echo(f"Using current environment: {environment}")
        
        if environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            sys.exit(1)
        
        click.echo(f"🚀 Creating user '{username}' in environment '{environment}'...")
        
        service_ops = ServiceOperations(config)
        result = asyncio.run(service_ops.create_user(
            environment=environment,
            username=username,
            password=password,
            email=email,
            role=role
        ))
        
        if result['success']:
            user = result['user']
            click.echo(f"✅ User created successfully:")
            click.echo(f"   ID: {user['id']}")
            click.echo(f"   Username: {user['username']}")
            click.echo(f"   Email: {user['email']}")
            click.echo(f"   Role: {user['role']}")
            click.echo(f"   Active: {user['active']}")
            click.echo(f"   Created: {user['created_at']}")
        else:
            click.echo(f"❌ Failed to create user: {result.get('error', 'Unknown error')}")
            if 'details' in result:
                for detail in result['details']:
                    click.echo(f"   - {detail}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to create user: {e}", err=True)
        sys.exit(1)


@service.command("list-users")
@click.option("--limit", type=int, default=50, help="Maximum number of users to return")
@click.option("--offset", type=int, default=0, help="Number of users to skip")
@click.option("--role", type=click.Choice(["user", "admin"]), help="Filter by user role")
@click.option("--active/--inactive", default=None, help="Filter by active status")
@click.option("--search", help="Search in username and email")
@click.option("--environment", help="Environment to target (defaults to current)")
@click.pass_context
def service_list_users(ctx: click.Context, limit: int, offset: int, role: Optional[str], active: Optional[bool], search: Optional[str], environment: Optional[str]) -> None:
    """List users via web service API."""
    config = ctx.obj["config"]
    
    try:
        from .service_operations import ServiceOperations
        
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
            click.echo(f"Using current environment: {environment}")
        
        if environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            sys.exit(1)
        
        click.echo(f"📋 Listing users in environment '{environment}'...")
        
        service_ops = ServiceOperations(config)
        result = asyncio.run(service_ops.list_users(
            environment=environment,
            limit=limit,
            offset=offset,
            role=role,
            active=active,
            search=search
        ))
        
        if result['success']:
            users = result['users']
            pagination = result['pagination']
            
            click.echo(f"✅ Found {pagination['total_count']} users (showing {pagination['returned_count']}):")
            click.echo("-" * 80)
            
            for user in users:
                status = "✅" if user['active'] else "❌"
                click.echo(f"{status} {user['username']} ({user['role']})")
                if user['email']:
                    click.echo(f"   Email: {user['email']}")
                click.echo(f"   ID: {user['id']}, Created: {user['created_at']}")
                click.echo()
            
            # Show pagination info
            if pagination['has_more']:
                next_offset = pagination['offset'] + pagination['limit']
                click.echo(f"📄 To see more users, use: --offset {next_offset}")
        else:
            click.echo(f"❌ Failed to list users: {result.get('error', 'Unknown error')}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to list users: {e}", err=True)
        sys.exit(1)


@service.command("delete-user")
@click.option("--username", help="Username of the user to delete")
@click.option("--user-id", type=int, help="ID of the user to delete")
@click.option("--environment", help="Environment to target (defaults to current)")
@click.confirmation_option(prompt="Are you sure you want to delete this user?")
@click.pass_context
def service_delete_user(ctx: click.Context, username: Optional[str], user_id: Optional[int], environment: Optional[str]) -> None:
    """Delete a user via web service API."""
    config = ctx.obj["config"]
    
    if not username and not user_id:
        click.echo("❌ Either --username or --user-id must be specified")
        sys.exit(1)
    
    if username and user_id:
        click.echo("❌ Specify either --username or --user-id, not both")
        sys.exit(1)
    
    try:
        from .service_operations import ServiceOperations
        
        parser = EnvironmentConfigParser(config)
        project_config = parser.load_project_config()
        
        # Use current environment if not specified
        if not environment:
            environment = project_config.environment
            click.echo(f"Using current environment: {environment}")
        
        if environment not in project_config.environments:
            click.echo(f"❌ Environment '{environment}' not found")
            sys.exit(1)
        
        identifier = username if username else f"ID {user_id}"
        click.echo(f"🗑️ Deleting user '{identifier}' in environment '{environment}'...")
        
        service_ops = ServiceOperations(config)
        result = asyncio.run(service_ops.delete_user(
            environment=environment,
            username=username,
            user_id=user_id
        ))
        
        if result['success']:
            deleted_user = result['deleted_user']
            click.echo(f"✅ User deleted successfully:")
            click.echo(f"   ID: {deleted_user['id']}")
            click.echo(f"   Username: {deleted_user['username']}")
            click.echo(f"   Email: {deleted_user['email']}")
        else:
            click.echo(f"❌ Failed to delete user: {result.get('error', 'Unknown error')}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Failed to delete user: {e}", err=True)
        sys.exit(1)


# Add missing import
import asyncio
from .init import InitCommand


# Init command
@cli.command()
@click.option("--postgres", is_flag=True, help="Include PostgreSQL container files")
@click.option("--deploy", is_flag=True, help="Include PostgreSQL deployment files")
@click.option("--all", "include_all", is_flag=True, help="Include all PostgreSQL files")
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.option("--project-name", help="Project name (defaults to current directory name)")
@click.option("--description", help="Project description")
@click.option("--env-name", default="dev", help="Environment name (default: dev)")
@click.option("--db-name", help="Database name (defaults to {project_name}_{env_name})")
@click.option("--db-port", type=int, default=5433, help="Database port (default: 5433)")
@click.option("--db-user", help="Database user (defaults to {project_name}_user)")
@click.option("--no-interactive", is_flag=True, help="Skip interactive prompts, use defaults/flags")
@click.pass_context
def init(ctx: click.Context, postgres: bool, deploy: bool, include_all: bool, force: bool,
         project_name: Optional[str], description: Optional[str], env_name: str,
         db_name: Optional[str], db_port: int, db_user: Optional[str], no_interactive: bool) -> None:
    """Initialize project with PostgreSQL configuration files.
    
    Makes PostgreSQL container and deployment configuration visible and customizable
    by copying template files to your project's containers/ and deploy/ directories.
    If no .poststack.yml exists, it will offer to create one with sensible defaults.
    
    Examples:
        poststack init --all          # Interactive mode (default)
        poststack init --postgres     # Copy only container files  
        poststack init --deploy       # Copy only deployment files
        poststack init --all --force  # Overwrite existing files
        poststack init --all --project-name myapp --no-interactive  # Non-interactive
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
            force=force,
            project_name=project_name,
            description=description,
            env_name=env_name,
            db_name=db_name,
            db_port=db_port,
            db_user=db_user,
            no_interactive=no_interactive
        )
        
        if result.success:
            click.echo("✅ Project initialization completed successfully!")
            
            if result.config_created:
                click.echo(f"\n📋 Configuration file created:")
                click.echo(f"   - .poststack.yml")
            
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