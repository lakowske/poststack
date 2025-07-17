"""
Database operations module for Poststack (Database-Focused)

Provides database connectivity, verification, and management for 
external PostgreSQL instances. Container orchestration is handled 
by Docker Compose.
"""

import logging
import re
import socket
import time
from typing import Dict, Optional, Any
from urllib.parse import urlparse

from .config import PoststackConfig
from .models import HealthCheckResult, RuntimeResult

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Database connection related errors."""
    pass


class DatabaseValidationError(Exception):
    """Database URL validation errors."""
    pass


class DatabaseURL:
    """Database URL parser and validator."""
    
    def __init__(self, url: str):
        """Initialize database URL."""
        self.url = url
        self.parsed = urlparse(url)
        
        if not self.parsed.scheme:
            raise DatabaseValidationError(f"Invalid database URL: {url}")
        
        if self.parsed.scheme not in ['postgresql', 'postgres']:
            raise DatabaseValidationError(f"Unsupported database scheme: {self.parsed.scheme}")
    
    @property
    def hostname(self) -> str:
        """Get hostname."""
        return self.parsed.hostname or 'localhost'
    
    @property
    def port(self) -> int:
        """Get port."""
        return self.parsed.port or 5432
    
    @property
    def database(self) -> str:
        """Get database name."""
        return self.parsed.path.lstrip('/') if self.parsed.path else 'postgres'
    
    @property
    def username(self) -> str:
        """Get username."""
        return self.parsed.username or 'postgres'
    
    @property
    def password(self) -> str:
        """Get password."""
        return self.parsed.password or ''
    
    def get_masked_url(self) -> str:
        """Get URL with masked password."""
        if self.password:
            return self.url.replace(f":{self.password}@", ":***@")
        return self.url
    
    def test_connectivity(self, timeout: int = 10) -> bool:
        """Test if database port is reachable."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((self.hostname, self.port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"Port connectivity test failed: {e}")
            return False


class DatabaseManager:
    """Database management for external PostgreSQL instances."""
    
    def __init__(self, config: PoststackConfig):
        """Initialize database manager."""
        self.config = config
    
    def validate_database_url(self, url: str) -> DatabaseURL:
        """Validate and parse database URL."""
        logger.info(f"Validating database URL: {DatabaseURL(url).get_masked_url()}")
        
        try:
            db_url = DatabaseURL(url)
            logger.info(f"Database URL validated: host={db_url.hostname}, port={db_url.port}, db={db_url.database}")
            return db_url
        except DatabaseValidationError as e:
            logger.error(f"Database URL validation failed: {e}")
            raise
    
    def test_connection(
        self,
        database_url: str,
        timeout: int = 30
    ) -> HealthCheckResult:
        """Test database connection."""
        logger.info("Testing database connection")
        
        start_time = time.time()
        
        try:
            db_url = self.validate_database_url(database_url)
            
            # Test port connectivity first
            if not db_url.test_connectivity(timeout=10):
                return HealthCheckResult(
                    container_name="database-test",
                    check_type="connection_test",
                    passed=False,
                    message=f"Cannot connect to database port {db_url.hostname}:{db_url.port}",
                    response_time=time.time() - start_time
                )
            
            # Test actual database connection
            try:
                import psycopg2
                
                conn = psycopg2.connect(
                    host=db_url.hostname,
                    port=db_url.port,
                    database=db_url.database,
                    user=db_url.username,
                    password=db_url.password,
                    connect_timeout=timeout
                )
                
                # Test a simple query
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                cursor.close()
                conn.close()
                
                if result and result[0] == 1:
                    return HealthCheckResult(
                        container_name="database-test",
                        check_type="connection_test",
                        passed=True,
                        message=f"Database connection successful: {db_url.hostname}:{db_url.port}",
                        response_time=time.time() - start_time
                    )
                else:
                    return HealthCheckResult(
                        container_name="database-test",
                        check_type="connection_test",
                        passed=False,
                        message="Database query test failed",
                        response_time=time.time() - start_time
                    )
                    
            except ImportError:
                return HealthCheckResult(
                    container_name="database-test",
                    check_type="connection_test",
                    passed=False,
                    message="psycopg2 not available. Install with: pip install psycopg2-binary",
                    response_time=time.time() - start_time
                )
            except Exception as e:
                return HealthCheckResult(
                    container_name="database-test",
                    check_type="connection_test",
                    passed=False,
                    message=f"Database connection failed: {e}",
                    response_time=time.time() - start_time
                )
        
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return HealthCheckResult(
                container_name="database-test",
                check_type="connection_test",
                passed=False,
                message=f"Connection test failed: {e}",
                response_time=time.time() - start_time
            )
    
    def get_database_info(self, database_url: str) -> Dict[str, Any]:
        """Get database information."""
        logger.info("Getting database information")
        
        try:
            db_url = self.validate_database_url(database_url)
            
            import psycopg2
            
            conn = psycopg2.connect(
                host=db_url.hostname,
                port=db_url.port,
                database=db_url.database,
                user=db_url.username,
                password=db_url.password,
                connect_timeout=10
            )
            
            cursor = conn.cursor()
            
            # Get database version
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            
            # Get database size
            cursor.execute(f"SELECT pg_size_pretty(pg_database_size('{db_url.database}'))")
            size = cursor.fetchone()[0]
            
            # Get connection info
            cursor.execute("SELECT current_database(), current_user")
            current_db, current_user = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            return {
                "version": version,
                "size": size,
                "current_database": current_db,
                "current_user": current_user,
                "hostname": db_url.hostname,
                "port": db_url.port
            }
            
        except Exception as e:
            logger.error(f"Failed to get database info: {e}")
            raise DatabaseConnectionError(f"Failed to get database info: {e}")
    
    def verify_database_availability(self, database_url: str, timeout: int = 30) -> RuntimeResult:
        """Verify database is available and accessible."""
        logger.info("Verifying database availability")
        
        start_time = time.time()
        
        try:
            connection_result = self.test_connection(database_url, timeout)
            
            if connection_result.passed:
                return RuntimeResult(
                    success=True,
                    message="Database is available and accessible",
                    runtime_seconds=time.time() - start_time
                )
            else:
                return RuntimeResult(
                    success=False,
                    message=f"Database unavailable: {connection_result.message}",
                    runtime_seconds=time.time() - start_time
                )
                
        except Exception as e:
            logger.error(f"Database availability check failed: {e}")
            return RuntimeResult(
                success=False,
                message=f"Database availability check failed: {e}",
                runtime_seconds=time.time() - start_time
            )