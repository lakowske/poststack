"""
Port allocation system for environment copying.

Manages automatic port offset allocation to prevent conflicts between
multiple environments running simultaneously.
"""

import logging
import socket
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


class PortAllocator:
    """Manages port allocation and offset calculation for environment copies."""
    
    # Port allocation constants
    BASE_OFFSET = 0          # Base environment uses no offset
    COPY_OFFSET_INCREMENT = 1000  # Each copy increments by 1000
    MAX_COPIES = 50          # Maximum number of copies (port range 0-50000)
    
    def __init__(self, project_root: Path):
        """Initialize port allocator with project configuration."""
        self.project_root = project_root
        self.registry_file = project_root / ".poststack" / "environment_registry.yaml"
        self.registry_file.parent.mkdir(exist_ok=True)
    
    def allocate_ports_for_copy(self, base_ports: Dict[str, int], parent_env: str, copy_name: str) -> Dict[str, int]:
        """
        Allocate ports for a new environment copy.
        
        Args:
            base_ports: Port configuration from parent environment
            parent_env: Name of parent environment being copied
            copy_name: Name of the new environment copy
            
        Returns:
            Dict mapping service names to allocated port numbers
            
        Raises:
            ValueError: If no available port range found
        """
        logger.info(f"Allocating ports for environment copy: {copy_name} (parent: {parent_env})")
        
        # Find next available offset
        offset = self._find_next_available_offset()
        
        if offset is None:
            raise ValueError(f"No available port ranges. Maximum {self.MAX_COPIES} environment copies supported.")
        
        # Calculate new ports
        allocated_ports = {}
        for service, base_port in base_ports.items():
            new_port = base_port + offset
            allocated_ports[service] = new_port
            
            # Validate port is actually available
            if not self._is_port_available(new_port):
                logger.warning(f"Port {new_port} for service {service} may be in use")
        
        # Register the allocation
        self._register_environment(copy_name, parent_env, offset, allocated_ports)
        
        logger.info(f"Allocated port range with offset {offset} for {copy_name}")
        return allocated_ports
    
    def deallocate_ports_for_environment(self, env_name: str) -> bool:
        """
        Deallocate ports for an environment that's being removed.
        
        Args:
            env_name: Name of environment to deallocate
            
        Returns:
            True if environment was found and deallocated, False otherwise
        """
        logger.info(f"Deallocating ports for environment: {env_name}")
        
        registry = self._load_registry()
        
        if env_name not in registry.get("environments", {}):
            logger.warning(f"Environment {env_name} not found in registry")
            return False
        
        # Remove from registry
        del registry["environments"][env_name]
        self._save_registry(registry)
        
        logger.info(f"Successfully deallocated ports for environment: {env_name}")
        return True
    
    def get_environment_ports(self, env_name: str) -> Optional[Dict[str, int]]:
        """Get port allocation for a specific environment."""
        registry = self._load_registry()
        env_info = registry.get("environments", {}).get(env_name)
        
        if env_info:
            return env_info.get("ports", {})
        return None
    
    def list_allocated_environments(self) -> Dict[str, Dict]:
        """List all allocated environments and their port information."""
        registry = self._load_registry()
        return registry.get("environments", {})
    
    def _find_next_available_offset(self) -> Optional[int]:
        """Find the next available port offset."""
        registry = self._load_registry()
        used_offsets = set()
        
        # Collect all used offsets
        for env_info in registry.get("environments", {}).values():
            offset = env_info.get("port_offset", self.BASE_OFFSET)
            used_offsets.add(offset)
        
        # Find next available offset
        for i in range(1, self.MAX_COPIES + 1):
            offset = i * self.COPY_OFFSET_INCREMENT
            if offset not in used_offsets:
                return offset
        
        return None
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available on localhost."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', port))
                return result != 0  # Port is available if connection fails
        except Exception:
            return False
    
    def _register_environment(self, env_name: str, parent_env: str, offset: int, ports: Dict[str, int]) -> None:
        """Register a new environment allocation in the registry."""
        registry = self._load_registry()
        
        if "environments" not in registry:
            registry["environments"] = {}
        
        registry["environments"][env_name] = {
            "parent": parent_env,
            "port_offset": offset,
            "ports": ports,
            "type": "copy",
            "created": self._get_current_timestamp()
        }
        
        self._save_registry(registry)
    
    def _load_registry(self) -> Dict:
        """Load the environment registry from disk."""
        if not self.registry_file.exists():
            return {"environments": {}}
        
        try:
            with open(self.registry_file, 'r') as f:
                return yaml.safe_load(f) or {"environments": {}}
        except Exception as e:
            logger.warning(f"Failed to load environment registry: {e}")
            return {"environments": {}}
    
    def _save_registry(self, registry: Dict) -> None:
        """Save the environment registry to disk."""
        try:
            with open(self.registry_file, 'w') as f:
                yaml.safe_dump(registry, f, default_flow_style=False, sort_keys=True)
        except Exception as e:
            logger.error(f"Failed to save environment registry: {e}")
            raise
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def cleanup_orphaned_allocations(self) -> List[str]:
        """
        Clean up allocations for environments that no longer exist.
        
        Returns:
            List of cleaned up environment names
        """
        logger.info("Cleaning up orphaned port allocations")
        
        registry = self._load_registry()
        environments = registry.get("environments", {})
        cleaned_up = []
        
        # For now, we'll implement a simple cleanup based on age
        # In the future, this could check if containers actually exist
        
        from datetime import datetime, timedelta
        cutoff_time = datetime.now() - timedelta(days=7)  # Clean up week-old allocations
        
        for env_name, env_info in list(environments.items()):
            created_str = env_info.get("created", "")
            try:
                created_time = datetime.fromisoformat(created_str)
                if created_time < cutoff_time:
                    logger.info(f"Cleaning up old allocation for {env_name} (created: {created_str})")
                    del environments[env_name]
                    cleaned_up.append(env_name)
            except (ValueError, TypeError):
                # Invalid timestamp, skip
                continue
        
        if cleaned_up:
            self._save_registry(registry)
            logger.info(f"Cleaned up {len(cleaned_up)} orphaned allocations")
        
        return cleaned_up