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
                
                project_containers[container_name] = {
                    "description": f"Project container: {container_name}",
                    "image": f"unified/{container_name}",
                    "dockerfile": str(dockerfile_path),
                    "context": str(containers_path.parent),  # Build context is project root
                    "ports": [],  # Will be determined from Dockerfile or config
                    "volumes": [],
                    "project_level": True,
                }
    
    return project_containers