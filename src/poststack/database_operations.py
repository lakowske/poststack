"""
Database operations module for Poststack

Provides database connectivity, verification, and management using
containerized PostgreSQL instances. Integrates with Phase 5 container
runtime capabilities.
"""

import logging
import re
import socket
import time
from typing import Dict, Optional, Any
from urllib.parse import urlparse

from .config import PoststackConfig
from .container_runtime import ContainerLifecycleManager, PostgreSQLRunner
from .models import HealthCheckResult, RuntimeResult

logger = logging.getLogger(__name__)


class DatabaseConnectionError(Exception):
    """Database connection related errors."""
    pass


class DatabaseValidationError(Exception):
    """Database validation related errors."""
    pass


class DatabaseURL:
    """Database URL parser and validator."""
    
    def __init__(self, url: str):
        """Initialize with database URL."""
        self.url = url
        self.parsed = self._parse_url(url)
    
    def _parse_url(self, url: str) -> Dict[str, Any]:
        """Parse database URL into components."""
        if not url:
            raise DatabaseValidationError("Database URL cannot be empty")
        
        if not url.startswith(('postgresql://', 'postgres://')):
            raise DatabaseValidationError("Database URL must start with postgresql:// or postgres://")
        
        try:
            parsed = urlparse(url)
            
            return {
                'scheme': parsed.scheme,
                'hostname': parsed.hostname or 'localhost',
                'port': parsed.port or 5432,
                'database': parsed.path.lstrip('/') if parsed.path else 'postgres',
                'username': parsed.username or 'postgres',
                'password': parsed.password or '',
            }
        except Exception as e:
            raise DatabaseValidationError(f"Invalid database URL format: {e}")
    
    @property
    def hostname(self) -> str:
        """Get hostname."""
        return self.parsed['hostname']
    
    @property
    def port(self) -> int:
        """Get port."""
        return self.parsed['port']
    
    @property
    def database(self) -> str:
        """Get database name."""
        return self.parsed['database']
    
    @property
    def username(self) -> str:
        """Get username."""
        return self.parsed['username']
    
    @property
    def password(self) -> str:
        """Get password."""
        return self.parsed['password']
    
    def get_masked_url(self) -> str:
        """Get URL with password masked."""
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", self.url)
    
    def test_connectivity(self, timeout: int = 10) -> bool:
        """Test if the database port is accessible."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((self.hostname, self.port))
                return result == 0
        except Exception:
            return False


class DatabaseManager:
    """Database management using containerized PostgreSQL."""
    
    def __init__(self, config: PoststackConfig):
        """Initialize database manager."""
        self.config = config
        self.container_manager = ContainerLifecycleManager(config)
        self.postgres_runner = PostgreSQLRunner(config)
    
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
        timeout: int = 30,
        use_container: bool = False,
        container_port: int = 5433
    ) -> HealthCheckResult:
        """Test database connection."""
        logger.info(f"Testing database connection (use_container={use_container})")
        
        start_time = time.time()
        
        try:
            db_url = self.validate_database_url(database_url)
            
            # If using container, start PostgreSQL container first
            if use_container:
                logger.info("Starting PostgreSQL container for testing")
                postgres_result, health_result = self.container_manager.start_test_environment(
                    postgres_port=container_port
                )
                
                if not postgres_result.success or not health_result.passed:
                    return HealthCheckResult(
                        container_name="database-test",
                        check_type="connection_test",
                        passed=False,
                        message=f"Failed to start test PostgreSQL container: {postgres_result.logs}",
                        response_time=time.time() - start_time
                    )
                
                # Update database URL to use container port
                test_url = database_url.replace(f":{db_url.port}", f":{container_port}")
                db_url = self.validate_database_url(test_url)
            
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
                
                logger.info(f"Attempting PostgreSQL connection to {db_url.get_masked_url()}")
                
                conn = psycopg2.connect(
                    host=db_url.hostname,
                    port=db_url.port,
                    database=db_url.database,
                    user=db_url.username,
                    password=db_url.password,
                    connect_timeout=timeout
                )
                
                # Test basic operations
                cursor = conn.cursor()
                cursor.execute("SELECT version(), current_database(), current_user;")
                version, current_db, current_user = cursor.fetchone()
                
                cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
                table_count = cursor.fetchone()[0]
                
                cursor.close()
                conn.close()
                
                response_time = time.time() - start_time
                
                logger.info(f"Database connection successful in {response_time:.2f}s")
                
                return HealthCheckResult(
                    container_name="database-test",
                    check_type="connection_test",
                    passed=True,
                    message=f"Database connection successful - {current_db} as {current_user}",
                    response_time=response_time,
                    details={
                        "version": version,
                        "database": current_db,
                        "user": current_user,
                        "table_count": table_count,
                        "hostname": db_url.hostname,
                        "port": db_url.port
                    }
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
            logger.error(f"Database connection test failed: {e}")
            return HealthCheckResult(
                container_name="database-test",
                check_type="connection_test",
                passed=False,
                message=f"Connection failed: {e}",
                response_time=time.time() - start_time
            )
        
        finally:
            # Clean up container if we started one
            if use_container:
                logger.info("Cleaning up test PostgreSQL container")
                self.container_manager.cleanup_test_environment()
    
    def verify_database_requirements(self, database_url: str) -> HealthCheckResult:
        """Verify database meets Poststack requirements."""
        logger.info("Verifying database requirements")
        
        start_time = time.time()
        
        try:
            # Test connection first
            connection_result = self.test_connection(database_url)
            if not connection_result.passed:
                return connection_result
            
            import psycopg2
            
            db_url = self.validate_database_url(database_url)
            conn = psycopg2.connect(
                host=db_url.hostname,
                port=db_url.port,
                database=db_url.database,
                user=db_url.username,
                password=db_url.password
            )
            
            cursor = conn.cursor()
            
            # Check PostgreSQL version (require 12+)
            cursor.execute("SHOW server_version_num;")
            version_num = int(cursor.fetchone()[0])
            if version_num < 120000:  # PostgreSQL 12.0
                cursor.close()
                conn.close()
                return HealthCheckResult(
                    container_name="database-requirements",
                    check_type="requirements_check",
                    passed=False,
                    message=f"PostgreSQL version {version_num} is too old. Requires 12.0 or newer.",
                    response_time=time.time() - start_time
                )
            
            # Check required extensions availability
            required_extensions = ['uuid-ossp']  # Add more as needed
            missing_extensions = []
            
            for ext in required_extensions:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_available_extensions WHERE name = %s);",
                    (ext,)
                )
                if not cursor.fetchone()[0]:
                    missing_extensions.append(ext)
            
            cursor.close()
            conn.close()
            
            if missing_extensions:
                return HealthCheckResult(
                    container_name="database-requirements",
                    check_type="requirements_check",
                    passed=False,
                    message=f"Missing required extensions: {', '.join(missing_extensions)}",
                    response_time=time.time() - start_time
                )
            
            return HealthCheckResult(
                container_name="database-requirements",
                check_type="requirements_check",
                passed=True,
                message="Database meets all Poststack requirements",
                response_time=time.time() - start_time,
                details={
                    "postgres_version": version_num,
                    "required_extensions": required_extensions
                }
            )
            
        except Exception as e:
            logger.error(f"Database requirements verification failed: {e}")
            return HealthCheckResult(
                container_name="database-requirements",
                check_type="requirements_check",
                passed=False,
                message=f"Requirements check failed: {e}",
                response_time=time.time() - start_time
            )
    
    def get_database_info(self, database_url: str) -> Dict[str, Any]:
        """Get comprehensive database information."""
        logger.info("Retrieving database information")
        
        try:
            db_url = self.validate_database_url(database_url)
            
            import psycopg2
            
            conn = psycopg2.connect(
                host=db_url.hostname,
                port=db_url.port,
                database=db_url.database,
                user=db_url.username,
                password=db_url.password
            )
            
            cursor = conn.cursor()
            
            # Get basic database info
            cursor.execute("""
                SELECT 
                    version() as version,
                    current_database() as database,
                    current_user as user,
                    inet_server_addr() as server_addr,
                    inet_server_port() as server_port,
                    pg_database_size(current_database()) as size_bytes
            """)
            basic_info = cursor.fetchone()
            
            # Get schema info
            cursor.execute("""
                SELECT 
                    schemaname,
                    COUNT(*) as table_count
                FROM pg_tables 
                GROUP BY schemaname
                ORDER BY schemaname
            """)
            schemas = cursor.fetchall()
            
            # Get connection info
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_connections,
                    COUNT(*) FILTER (WHERE state = 'active') as active_connections
                FROM pg_stat_activity
            """)
            connection_info = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            return {
                "connection": {
                    "hostname": db_url.hostname,
                    "port": db_url.port,
                    "database": basic_info[1],
                    "user": basic_info[2]
                },
                "server": {
                    "version": basic_info[0],
                    "address": basic_info[3],
                    "port": basic_info[4],
                    "size_bytes": basic_info[5],
                    "size_mb": round(basic_info[5] / 1024 / 1024, 2) if basic_info[5] else 0
                },
                "schemas": [{"name": schema[0], "table_count": schema[1]} for schema in schemas],
                "connections": {
                    "total": connection_info[0],
                    "active": connection_info[1]
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get database info: {e}")
            raise DatabaseConnectionError(f"Failed to get database info: {e}")