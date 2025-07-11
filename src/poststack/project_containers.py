"""
Project-level container discovery and management utilities.
"""

import logging
from pathlib import Path
from typing import Dict

from .config import PoststackConfig

logger = logging.getLogger(__name__)


def discover_project_containers(config: PoststackConfig) -> Dict[str, dict]:
    """
    Discover project-level containers from the configured containers path.
    
    Args:
        config: Poststack configuration
        
    Returns:
        Dictionary of discovered project containers
    """
    project_containers = {}
    containers_path = Path(config.project_containers_path)
    
    if not containers_path.exists():
        logger.debug(f"Project containers path does not exist: {containers_path}")
        return project_containers
    
    # Look for container directories with Dockerfile
    for container_dir in containers_path.iterdir():
        if container_dir.is_dir():
            dockerfile_path = container_dir / "Dockerfile"
            if dockerfile_path.exists():
                container_name = container_dir.name
                logger.info(f"Discovered project container: {container_name}")
                
                # Try to extract port information from Dockerfile
                ports = _extract_ports_from_dockerfile(dockerfile_path)
                
                # Get project name for image tagging
                project_name = config.get_project_container_prefix()
                
                project_containers[container_name] = {
                    "description": f"Project container: {container_name}",
                    "image": f"{project_name}/{container_name}",
                    "dockerfile": str(dockerfile_path),
                    "context": str(containers_path.parent),  # Build context is project root
                    "ports": ports,
                    "volumes": [],
                    "project_level": True,
                    "default_port_mappings": _get_default_port_mappings(container_name, ports),
                    "container_port": ports[0] if ports else None,
                }
    
    return project_containers


def _extract_ports_from_dockerfile(dockerfile_path: Path) -> list:
    """Extract EXPOSE ports from Dockerfile."""
    ports = []
    try:
        with open(dockerfile_path, 'r') as f:
            for line in f:
                line = line.strip().upper()
                if line.startswith('EXPOSE '):
                    port_spec = line.replace('EXPOSE ', '').strip()
                    # Handle multiple ports on one line
                    for port in port_spec.split():
                        # Remove protocol if specified (80/tcp -> 80)
                        port_num = port.split('/')[0]
                        try:
                            ports.append(int(port_num))
                        except ValueError:
                            logger.warning(f"Invalid port in Dockerfile: {port}")
    except Exception as e:
        logger.warning(f"Failed to read Dockerfile {dockerfile_path}: {e}")
    
    return ports


def _get_default_port_mappings(container_name: str, ports: list) -> dict:
    """Get default port mappings for a container."""
    if not ports:
        return {}
    
    # Default mapping strategies for common containers
    defaults = {
        'apache': {80: 8080, 443: 8443},
        'nginx': {80: 8080, 443: 8443},
        'web': {80: 8080, 443: 8443},
        'app': {8000: 8000, 3000: 3000},
        'api': {8000: 8000, 3000: 3000},
        'redis': {6379: 6379},
        'mysql': {3306: 3306},
        'postgres': {5432: 5432},
    }
    
    # Check if container name matches known patterns
    for pattern, mapping in defaults.items():
        if pattern in container_name.lower():
            # Return mapping for ports that exist in the container
            return {host_port: container_port for container_port, host_port in mapping.items() 
                   if container_port in ports}
    
    # Default: map to high ports starting from 8080
    result = {}
    base_port = 8080
    for i, port in enumerate(sorted(ports)):
        result[base_port + i] = port
    
    return result