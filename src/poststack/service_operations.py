"""
Service Operations for Web Services

Provides operations for interacting with web service APIs that support
poststack service management, including user management via API keys.
"""

import asyncio
import aiohttp
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

from .config import PoststackConfig
from .environment.config import EnvironmentConfigParser
from .environment.substitution import VariableSubstitutor

logger = logging.getLogger(__name__)


class ServiceOperationError(Exception):
    """Service operation related errors."""
    pass


class ServiceOperations:
    """Handles operations for web services with API key authentication."""
    
    def __init__(self, poststack_config: PoststackConfig):
        """Initialize service operations handler."""
        self.poststack_config = poststack_config
        self.config_parser = EnvironmentConfigParser(poststack_config)
        
    async def _get_service_info(self, environment: str) -> Dict[str, Any]:
        """Get service connection information for an environment."""
        try:
            # Load environment configuration
            env_config = self.config_parser.get_environment_config(environment)
            project_config = self.config_parser.load_project_config()
            
            # Create variable substitutor
            substitutor = VariableSubstitutor(environment, env_config, project_config.project.name)
            
            # Find web service containers in the environment
            web_services = []
            
            for deployment in env_config.deployments:
                if deployment.type == "web":
                    # Parse pod file to get service URL
                    pod_file = Path(deployment.get_deployment_path())
                    if not pod_file.exists():
                        continue
                    
                    # Extract service information from environment variables
                    # Look for postgres deployment to get port info  
                    postgres_port = 5436  # Default postgres port
                    for postgres_deployment in env_config.deployments:
                        if postgres_deployment.type == "postgres":
                            # Extract port from variables or use default
                            postgres_port = int(postgres_deployment.variables.get('DB_PORT', '5436'))
                            break
                    
                    # Get apache port from environment variables
                    apache_port = 8080  # Default
                    if 'APACHE_HOST_PORT' in env_config.variables:
                        apache_port = int(env_config.variables['APACHE_HOST_PORT'])
                    
                    base_url = f"http://localhost:{apache_port}"
                    
                    web_services.append({
                        'name': deployment.get_deployment_name(),
                        'base_url': base_url,
                        'api_base': urljoin(base_url, '/api/v1/'),
                        'type': deployment.type
                    })
            
            if not web_services:
                raise ServiceOperationError(f"No web services found in environment '{environment}'")
            
            # Use the first web service for now
            service_info = web_services[0]
            
            logger.info(f"Using web service: {service_info['name']} at {service_info['base_url']}")
            return service_info
            
        except Exception as e:
            logger.error(f"Failed to get service info for environment '{environment}': {e}")
            raise ServiceOperationError(f"Failed to get service info: {e}")
    
    async def _get_api_key(self, environment: str) -> str:
        """Get API key from the running web service container."""
        try:
            env_config = self.config_parser.get_environment_config(environment)
            project_config = self.config_parser.load_project_config()
            
            # Find the web service container name
            container_name = None
            for deployment in env_config.deployments:
                if deployment.type == "web":
                    # Construct container name based on deployment
                    # Try the most common patterns for container naming
                    possible_names = [
                        f"{project_config.project.name}-{deployment.get_deployment_name()}-{environment}-{deployment.get_deployment_name()}-web",
                        f"{project_config.project.name}-{deployment.get_deployment_name()}-{environment}-{deployment.get_deployment_name()}",
                        f"{project_config.project.name}-{deployment.get_deployment_name()}-{environment}-apache",
                        f"{project_config.project.name}-{deployment.get_deployment_name()}-{environment}-web",
                    ]
                    
                    # Check which container actually exists
                    for possible_name in possible_names:
                        try:
                            check_cmd = [
                                self.poststack_config.container_runtime,
                                "ps",
                                "--filter", f"name={possible_name}",
                                "--format", "{{.Names}}"
                            ]
                            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
                            if result.returncode == 0 and possible_name in result.stdout:
                                container_name = possible_name
                                break
                        except subprocess.TimeoutExpired:
                            continue
                    
                    if not container_name:
                        container_name = possible_names[0]  # Fall back to first guess
                    break
            
            if not container_name:
                raise ServiceOperationError("No web service container found")
            
            # Execute command to get API key from container
            cmd = [
                self.poststack_config.container_runtime,
                "exec",
                container_name,
                "cat",
                "/var/local/poststack_api_key"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                raise ServiceOperationError(f"Failed to get API key from container: {result.stderr}")
            
            api_key = result.stdout.strip()
            if not api_key:
                raise ServiceOperationError("Empty API key retrieved from container")
            
            logger.debug(f"Retrieved API key from container {container_name}")
            return api_key
            
        except subprocess.TimeoutExpired:
            raise ServiceOperationError("Timeout getting API key from container")
        except Exception as e:
            logger.error(f"Failed to get API key: {e}")
            raise ServiceOperationError(f"Failed to get API key: {e}")
    
    async def _make_api_request(
        self,
        environment: str,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make an authenticated API request to a web service."""
        try:
            # Get service info and API key
            service_info = await self._get_service_info(environment)
            api_key = await self._get_api_key(environment)
            
            # Construct full URL
            url = urljoin(service_info['api_base'], endpoint)
            
            # Prepare headers
            headers = {
                'Content-Type': 'application/json',
                'X-API-Key': api_key
            }
            
            # Prepare request data
            json_data = None
            if data and method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                json_data = data
            
            logger.info(f"Making {method} request to {url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_text = await response.text()
                    
                    # Log response details
                    logger.debug(f"Response status: {response.status}")
                    logger.debug(f"Response body: {response_text}")
                    
                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        raise ServiceOperationError(f"Invalid JSON response: {response_text}")
                    
                    # Check for HTTP errors
                    if response.status >= 400:
                        error_msg = response_data.get('error', f'HTTP {response.status}')
                        raise ServiceOperationError(f"API request failed: {error_msg}")
                    
                    return response_data
                    
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error: {e}")
            raise ServiceOperationError(f"HTTP request failed: {e}")
        except Exception as e:
            logger.error(f"API request failed: {e}")
            raise ServiceOperationError(f"API request failed: {e}")
    
    async def create_user(
        self,
        environment: str,
        username: str,
        password: str,
        email: Optional[str] = None,
        role: str = "user"
    ) -> Dict[str, Any]:
        """Create a new user via web service API."""
        logger.info(f"Creating user '{username}' with role '{role}' in environment '{environment}'")
        
        try:
            # Prepare user data
            user_data = {
                'username': username,
                'password': password,
                'role': role
            }
            
            if email:
                user_data['email'] = email
            
            # Make API request
            response = await self._make_api_request(
                environment=environment,
                endpoint="admin/create_user.php",
                method="POST",
                data=user_data
            )
            
            logger.info(f"User '{username}' created successfully")
            return response
            
        except Exception as e:
            logger.error(f"Failed to create user '{username}': {e}")
            raise
    
    async def list_users(
        self,
        environment: str,
        limit: int = 50,
        offset: int = 0,
        role: Optional[str] = None,
        active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """List users via web service API."""
        logger.info(f"Listing users in environment '{environment}' (limit={limit}, offset={offset})")
        
        try:
            # Prepare query parameters
            params = {
                'limit': limit,
                'offset': offset
            }
            
            if role:
                params['role'] = role
            
            if active is not None:
                params['active'] = 'true' if active else 'false'
            
            if search:
                params['search'] = search
            
            # Make API request
            response = await self._make_api_request(
                environment=environment,
                endpoint="admin/list_users.php",
                method="GET",
                params=params
            )
            
            user_count = response.get('pagination', {}).get('returned_count', 0)
            logger.info(f"Retrieved {user_count} users from environment '{environment}'")
            return response
            
        except Exception as e:
            logger.error(f"Failed to list users in environment '{environment}': {e}")
            raise
    
    async def delete_user(
        self,
        environment: str,
        username: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Delete a user via web service API."""
        identifier = username if username else f"ID {user_id}"
        logger.info(f"Deleting user '{identifier}' in environment '{environment}'")
        
        try:
            # Prepare request data
            data = {}
            if username:
                data['username'] = username
            elif user_id:
                data['user_id'] = user_id
            else:
                raise ValueError("Either username or user_id must be provided")
            
            # Make API request
            response = await self._make_api_request(
                environment=environment,
                endpoint="admin/delete_user.php",
                method="DELETE",
                data=data
            )
            
            if response.get('success'):
                deleted_user = response.get('deleted_user', {})
                logger.info(f"User deleted successfully: username={deleted_user.get('username')}, id={deleted_user.get('id')}")
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to delete user '{identifier}' in environment '{environment}': {e}")
            raise
    
    async def test_service_connectivity(self, environment: str) -> Dict[str, Any]:
        """Test connectivity to web service APIs."""
        logger.info(f"Testing service connectivity for environment '{environment}'")
        
        try:
            # Get service info
            service_info = await self._get_service_info(environment)
            
            # Test basic connectivity (health check or similar)
            try:
                api_key = await self._get_api_key(environment)
                
                # Try to make a simple API request
                response = await self._make_api_request(
                    environment=environment,
                    endpoint="admin/list_users.php",
                    method="GET",
                    params={'limit': 1}
                )
                
                return {
                    'success': True,
                    'service_info': service_info,
                    'api_accessible': True,
                    'message': 'Service connectivity test passed'
                }
                
            except Exception as api_error:
                return {
                    'success': False,
                    'service_info': service_info,
                    'api_accessible': False,
                    'message': f'API test failed: {api_error}'
                }
                
        except Exception as e:
            logger.error(f"Service connectivity test failed: {e}")
            return {
                'success': False,
                'service_info': None,
                'api_accessible': False,
                'message': f'Connectivity test failed: {e}'
            }