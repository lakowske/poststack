"""
Container management commands for Poststack

Handles container building, running, and lifecycle management
for PostgreSQL, Apache, Dovecot, BIND, and certificate services.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import click

from .config import PoststackConfig
from .logging_config import SubprocessLogHandler

logger = logging.getLogger(__name__)


# Define the core services and their container configurations
POSTSTACK_SERVICES = {
    "postgresql": {
        "description": "PostgreSQL database server",
        "image": "poststack/postgresql",
        "dockerfile": "containers/postgresql/Dockerfile",
        "ports": ["5432:5432"],
        "volumes": ["poststack_postgres_data:/var/lib/postgresql/data"],
    },
    "apache": {
        "description": "Apache HTTP server with PHP",
        "image": "poststack/apache",
        "dockerfile": "containers/apache/Dockerfile",
        "ports": ["80:80", "443:443"],
        "volumes": ["poststack_web_data:/var/www/html"],
    },
    "dovecot": {
        "description": "Dovecot IMAP/POP3 server",
        "image": "poststack/dovecot",
        "dockerfile": "containers/dovecot/Dockerfile",
        "ports": ["143:143", "993:993", "110:110", "995:995"],
        "volumes": ["poststack_mail_data:/var/mail"],
    },
    "bind": {
        "description": "BIND DNS server",
        "image": "poststack/bind",
        "dockerfile": "containers/bind/Dockerfile",
        "ports": ["53:53/udp", "53:53/tcp"],
        "volumes": ["poststack_dns_data:/etc/bind"],
    },
    "certbot": {
        "description": "Let's Encrypt certificate manager",
        "image": "poststack/certbot",
        "dockerfile": "containers/certbot/Dockerfile",
        "ports": [],
        "volumes": ["poststack_cert_data:/etc/letsencrypt"],
    },
}


@click.group()
def containers() -> None:
    """Manage container operations and lifecycle."""
    pass


@containers.command()
@click.option(
    "--service",
    type=click.Choice(list(POSTSTACK_SERVICES.keys()) + ["all"], case_sensitive=False),
    default="all",
    help="Service to build (default: all)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force rebuild (no cache)",
)
@click.option(
    "--parallel",
    is_flag=True,
    help="Build containers in parallel",
)
@click.pass_context
def build(
    ctx: click.Context,
    service: str,
    force: bool,
    parallel: bool,
) -> None:
    """Build container images for Poststack services."""
    config: PoststackConfig = ctx.obj["config"]

    if service == "all":
        services_to_build = list(POSTSTACK_SERVICES.keys())
    else:
        services_to_build = [service]

    click.echo(f"🔨 Building containers using {config.container_runtime}")
    click.echo(f"Services: {', '.join(services_to_build)}")

    if force:
        click.echo("🚫 Force rebuild enabled (no cache)")

    if parallel and len(services_to_build) > 1:
        click.echo("⚡ Parallel build enabled")

    log_handler = SubprocessLogHandler("container_build", config.log_dir)

    # Check if Dockerfiles exist (for Phase 2, we'll simulate)
    containerfiles_dir = Path("containers")
    if not containerfiles_dir.exists():
        click.echo("ℹ️  Container definitions not found - simulating builds for Phase 2")
        _simulate_container_builds(services_to_build, config, log_handler)
        return

    success_count = 0
    total_count = len(services_to_build)

    for service_name in services_to_build:
        service_config = POSTSTACK_SERVICES[service_name]

        click.echo(f"\n🔨 Building {service_name} ({service_config['description']})")

        dockerfile_path = Path(service_config["dockerfile"])
        if not dockerfile_path.exists():
            click.echo(f"❌ Dockerfile not found: {dockerfile_path}")
            continue

        # Build container command
        build_cmd = [
            config.container_runtime,
            "build",
            "-t",
            service_config["image"],
            "-f",
            str(dockerfile_path),
        ]

        if force:
            build_cmd.append("--no-cache")

        build_cmd.append(str(dockerfile_path.parent))

        # Execute build
        try:
            log_handler.log_command(build_cmd)

            start_time = time.time()
            result = subprocess.run(
                build_cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )
            elapsed_time = time.time() - start_time

            if result.stdout:
                log_handler.log_output(result.stdout)
            if result.stderr:
                log_handler.log_output(result.stderr, logging.WARNING)

            log_handler.log_completion(result.returncode, elapsed_time)

            if result.returncode == 0:
                click.echo(
                    f"✅ {service_name} built successfully in {elapsed_time:.1f}s"
                )
                success_count += 1
            else:
                click.echo(f"❌ {service_name} build failed")

        except subprocess.TimeoutExpired:
            click.echo(f"⏰ {service_name} build timed out after 10 minutes")
        except Exception as e:
            click.echo(f"❌ {service_name} build error: {e}")

    click.echo(f"\n📄 Build logs: {log_handler.get_log_file_path()}")
    click.echo(f"🏁 Build complete: {success_count}/{total_count} successful")

    if success_count < total_count:
        sys.exit(1)


def _simulate_container_builds(
    services: List[str],
    config: PoststackConfig,
    log_handler: SubprocessLogHandler,
) -> None:
    """Simulate container builds for Phase 2 demonstration."""

    for service_name in services:
        service_config = POSTSTACK_SERVICES[service_name]

        click.echo(
            f"\n🔨 Simulating build: {service_name} ({service_config['description']})"
        )

        # Simulate build command logging
        build_cmd = [
            config.container_runtime,
            "build",
            "-t",
            service_config["image"],
            "containers/" + service_name,
        ]

        log_handler.log_command(build_cmd)

        # Simulate build time
        build_time = 2.0 + len(service_name) * 0.3  # Realistic but fast
        time.sleep(min(build_time, 3.0))  # Cap at 3 seconds for demo

        # Simulate successful build output
        log_handler.log_output("Step 1/5 : FROM debian:bookworm-slim")
        log_handler.log_output(
            f"Step 2/5 : RUN apt-get update && apt-get install -y {service_name}"
        )
        log_handler.log_output(f"Step 3/5 : COPY config/ /etc/{service_name}/")
        log_handler.log_output(
            f"Step 4/5 : EXPOSE {service_config['ports'][0].split(':')[1] if service_config['ports'] else '80'}"
        )
        log_handler.log_output(f'Step 5/5 : CMD ["{service_name}", "-f"]')
        log_handler.log_output(f"Successfully built {service_config['image']}")

        log_handler.log_completion(0, build_time)

        click.echo(f"✅ {service_name} simulated build completed")


@containers.command()
@click.option(
    "--service",
    type=click.Choice(list(POSTSTACK_SERVICES.keys()) + ["all"], case_sensitive=False),
    help="Specific service to list",
)
@click.pass_context
def list(ctx: click.Context, service: Optional[str]) -> None:
    """List available container images and running containers."""
    config: PoststackConfig = ctx.obj["config"]

    click.echo(f"📦 Poststack Container Status ({config.container_runtime})")
    click.echo("=" * 50)

    if service and service != "all":
        services_to_check = [service]
    else:
        services_to_check = list(POSTSTACK_SERVICES.keys())

    for service_name in services_to_check:
        service_config = POSTSTACK_SERVICES[service_name]
        image_name = service_config["image"]

        click.echo(f"\n🔧 {service_name.upper()}: {service_config['description']}")

        # Check if image exists
        try:
            result = subprocess.run(
                [config.container_runtime, "images", "-q", image_name],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                click.echo(f"   📦 Image: ✅ {image_name}")
            else:
                click.echo(f"   📦 Image: ❌ {image_name} (not built)")

        except Exception:
            click.echo(f"   📦 Image: ❓ {image_name} (check failed)")

        # Check running containers
        try:
            result = subprocess.run(
                [
                    config.container_runtime,
                    "ps",
                    "--filter",
                    f"ancestor={image_name}",
                    "--format",
                    "table {{.Names}}\\t{{.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[1:]  # Skip header
                if lines and lines[0]:
                    click.echo(f"   🏃 Running: {len(lines)} container(s)")
                    for line in lines:
                        if line.strip():
                            parts = line.split("\t")
                            if len(parts) >= 2:
                                click.echo(f"      • {parts[0]}: {parts[1]}")
                else:
                    click.echo("   🏃 Running: None")
            else:
                click.echo("   🏃 Running: ❓ (check failed)")

        except Exception:
            click.echo("   🏃 Running: ❓ (check failed)")


@containers.command()
@click.option(
    "--service",
    type=click.Choice(list(POSTSTACK_SERVICES.keys()), case_sensitive=False),
    required=True,
    help="Service to start",
)
@click.option(
    "--detached",
    "-d",
    is_flag=True,
    default=True,
    help="Run in detached mode",
)
@click.pass_context
def start(ctx: click.Context, service: str, detached: bool) -> None:
    """Start a Poststack service container."""
    config: PoststackConfig = ctx.obj["config"]
    service_config = POSTSTACK_SERVICES[service]

    click.echo(f"🚀 Starting {service} ({service_config['description']})")

    # Build run command
    run_cmd = [
        config.container_runtime,
        "run",
        "--name",
        f"poststack-{service}",
        "--restart",
        "unless-stopped",
    ]

    if detached:
        run_cmd.append("-d")

    # Add port mappings
    for port_mapping in service_config["ports"]:
        run_cmd.extend(["-p", port_mapping])

    # Add volume mappings
    for volume_mapping in service_config["volumes"]:
        run_cmd.extend(["-v", volume_mapping])

    # Add the image
    run_cmd.append(service_config["image"])

    try:
        click.echo(f"Executing: {' '.join(run_cmd)}")

        result = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            container_id = result.stdout.strip()
            click.echo(f"✅ {service} started successfully")
            click.echo(f"Container ID: {container_id[:12]}...")

            if service_config["ports"]:
                click.echo("Exposed ports:")
                for port in service_config["ports"]:
                    click.echo(f"  • {port}")
        else:
            click.echo(f"❌ Failed to start {service}")
            if result.stderr:
                click.echo(f"Error: {result.stderr}")
            sys.exit(1)

    except subprocess.TimeoutExpired:
        click.echo(f"⏰ {service} start timed out")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error starting {service}: {e}")
        sys.exit(1)


@containers.command()
@click.option(
    "--service",
    type=click.Choice(list(POSTSTACK_SERVICES.keys()) + ["all"], case_sensitive=False),
    default="all",
    help="Service to stop (default: all)",
)
@click.pass_context
def stop(ctx: click.Context, service: str) -> None:
    """Stop Poststack service containers."""
    config: PoststackConfig = ctx.obj["config"]

    if service == "all":
        services_to_stop = list(POSTSTACK_SERVICES.keys())
        click.echo("🛑 Stopping all Poststack services")
    else:
        services_to_stop = [service]
        click.echo(f"🛑 Stopping {service}")

    for service_name in services_to_stop:
        container_name = f"poststack-{service_name}"

        try:
            # Check if container exists and is running
            result = subprocess.run(
                [
                    config.container_runtime,
                    "ps",
                    "-q",
                    "--filter",
                    f"name={container_name}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                # Stop the container
                stop_result = subprocess.run(
                    [config.container_runtime, "stop", container_name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if stop_result.returncode == 0:
                    click.echo(f"✅ {service_name} stopped")
                else:
                    click.echo(f"❌ Failed to stop {service_name}")
            else:
                click.echo(f"ℹ️  {service_name} is not running")

        except Exception as e:
            click.echo(f"❌ Error stopping {service_name}: {e}")


@containers.command()
@click.option(
    "--service",
    type=click.Choice(list(POSTSTACK_SERVICES.keys()) + ["all"], case_sensitive=False),
    default="all",
    help="Service to clean (default: all)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force removal without confirmation",
)
@click.pass_context
def clean(ctx: click.Context, service: str, force: bool) -> None:
    """Remove Poststack containers and images."""
    config: PoststackConfig = ctx.obj["config"]

    if service == "all":
        services_to_clean = list(POSTSTACK_SERVICES.keys())
        click.echo("🧹 Cleaning all Poststack containers and images")
    else:
        services_to_clean = [service]
        click.echo(f"🧹 Cleaning {service}")

    if not force:
        click.echo("⚠️  This will remove containers and images!")
        if not click.confirm("Are you sure you want to continue?"):
            click.echo("Clean operation cancelled")
            return

    for service_name in services_to_clean:
        service_config = POSTSTACK_SERVICES[service_name]
        container_name = f"poststack-{service_name}"
        image_name = service_config["image"]

        # Stop and remove container
        try:
            subprocess.run(
                [config.container_runtime, "stop", container_name],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                [config.container_runtime, "rm", container_name],
                capture_output=True,
                timeout=10,
            )
            click.echo(f"🗑️  Removed {service_name} container")
        except Exception:
            pass  # Container might not exist

        # Remove image
        try:
            result = subprocess.run(
                [config.container_runtime, "rmi", image_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                click.echo(f"🗑️  Removed {service_name} image")
        except Exception:
            pass  # Image might not exist

    click.echo("✅ Cleanup complete")


@containers.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show detailed status of all Poststack containers."""
    config: PoststackConfig = ctx.obj["config"]

    click.echo(f"📊 Poststack Container Status ({config.container_runtime})")
    click.echo("=" * 60)

    try:
        # Get all containers with poststack prefix
        result = subprocess.run(
            [
                config.container_runtime,
                "ps",
                "-a",
                "--filter",
                "name=poststack-",
                "--format",
                "table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout.strip():
            click.echo(result.stdout)
        else:
            click.echo("No Poststack containers found")

    except Exception as e:
        click.echo(f"❌ Failed to get container status: {e}")

    # Show available services
    click.echo("\n📋 Available Services:")
    for service_name, service_config in POSTSTACK_SERVICES.items():
        click.echo(f"  • {service_name}: {service_config['description']}")

    click.echo("\n💡 Use 'poststack containers list' for detailed service status")
