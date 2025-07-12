"""
Schema management module for Poststack

Provides database schema management using SQL-based migrations.
Integrates with the new schema migration system.
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import PoststackConfig
from .database_operations import DatabaseManager
from .models import HealthCheckResult, RuntimeResult, RuntimeStatus
from .schema_migration import MigrationRunner

logger = logging.getLogger(__name__)


class SchemaManagementError(Exception):
    """Schema management related errors."""
    pass


class SchemaManager:
    """Schema management using SQL-based migrations."""
    
    def __init__(self, config: PoststackConfig):
        """Initialize schema manager."""
        self.config = config
        self.database_manager = DatabaseManager(config)
        self.migrations_path = getattr(config, 'migrations_path', './migrations')
    
    def _get_migration_runner(self, database_url: str) -> MigrationRunner:
        """Create a migration runner for the given database URL."""
        return MigrationRunner(
            database_url=database_url,
            migrations_path=self.migrations_path
        )
    
    def _convert_migration_result_to_runtime_result(
        self,
        migration_result,
        container_name: str = "schema-manager",
        image_name: str = "poststack/schema:latest"
    ) -> RuntimeResult:
        """Convert migration result to runtime result."""
        status = RuntimeStatus.STOPPED if migration_result.success else RuntimeStatus.FAILED
        
        result = RuntimeResult(
            container_name=container_name,
            image_name=image_name,
            status=status
        )
        
        if migration_result.message:
            result.add_logs(migration_result.message)
        
        if migration_result.error:
            result.add_logs(f"Error: {migration_result.error}")
        
        return result
    
    def initialize_schema(self, database_url: str) -> RuntimeResult:
        """Initialize Poststack schema using migrations."""
        logger.info("Initializing Poststack schema")
        
        try:
            # Test database connection first
            connection_test = self.database_manager.test_connection(database_url)
            if not connection_test.passed:
                result = RuntimeResult(
                    container_name="schema-init",
                    image_name="poststack/schema:latest",
                    status=RuntimeStatus.FAILED
                )
                result.add_logs(f"Database connection failed: {connection_test.message}")
                return result
            
            # Run migrations
            migration_runner = self._get_migration_runner(database_url)
            migration_result = migration_runner.migrate()
            
            if migration_result.success:
                logger.info("Schema initialization completed successfully")
                
                # Verify schema was created
                verification = self.verify_schema(database_url)
                if verification.passed:
                    success_result = self._convert_migration_result_to_runtime_result(
                        migration_result, "schema-init"
                    )
                    success_result.add_logs(f"Schema initialized successfully. {verification.message}")
                    return success_result
                else:
                    failure_result = RuntimeResult(
                        container_name="schema-init",
                        image_name="poststack/schema:latest",
                        status=RuntimeStatus.FAILED
                    )
                    failure_result.add_logs(f"Schema initialization failed verification: {verification.message}")
                    return failure_result
            else:
                logger.error(f"Schema initialization failed: {migration_result.message}")
                return self._convert_migration_result_to_runtime_result(migration_result, "schema-init")
                
        except Exception as e:
            logger.error(f"Schema initialization error: {e}")
            result = RuntimeResult(
                container_name="schema-init",
                image_name="poststack/schema:latest",
                status=RuntimeStatus.FAILED
            )
            result.add_logs(f"Schema initialization error: {e}")
            return result
    
    def update_schema(self, database_url: str, target_version: Optional[str] = None) -> RuntimeResult:
        """Update schema using migrations."""
        logger.info("Updating Poststack schema")
        
        try:
            # Run migrations
            migration_runner = self._get_migration_runner(database_url)
            migration_result = migration_runner.migrate(target_version=target_version)
            
            if migration_result.success:
                logger.info("Schema update completed successfully")
            else:
                logger.error(f"Schema update failed: {migration_result.message}")
            
            return self._convert_migration_result_to_runtime_result(migration_result, "schema-update")
            
        except Exception as e:
            logger.error(f"Schema update error: {e}")
            result = RuntimeResult(
                container_name="schema-update",
                image_name="poststack/schema:latest",
                status=RuntimeStatus.FAILED
            )
            result.add_logs(f"Schema update error: {e}")
            return result
    
    def rollback_schema(self, database_url: str, target_version: str) -> RuntimeResult:
        """Rollback schema to a specific version."""
        logger.info(f"Rolling back schema to version {target_version}")
        
        try:
            migration_runner = self._get_migration_runner(database_url)
            migration_result = migration_runner.rollback(target_version=target_version)
            
            if migration_result.success:
                logger.info(f"Schema rollback to {target_version} completed successfully")
            else:
                logger.error(f"Schema rollback failed: {migration_result.message}")
            
            return self._convert_migration_result_to_runtime_result(migration_result, "schema-rollback")
            
        except Exception as e:
            logger.error(f"Schema rollback error: {e}")
            result = RuntimeResult(
                container_name="schema-rollback",
                image_name="poststack/schema:latest",
                status=RuntimeStatus.FAILED
            )
            result.add_logs(f"Schema rollback error: {e}")
            return result
    
    def verify_schema(self, database_url: str) -> HealthCheckResult:
        """Verify Poststack schema is properly installed."""
        logger.info("Verifying Poststack schema")
        
        start_time = time.time()
        
        try:
            import psycopg2
            
            db_url = self.database_manager.validate_database_url(database_url)
            conn = psycopg2.connect(
                host=db_url.hostname,
                port=db_url.port,
                database=db_url.database,
                user=db_url.username,
                password=db_url.password
            )
            
            cursor = conn.cursor()
            
            # Check if poststack schema exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata 
                    WHERE schema_name = 'poststack'
                );
            """)
            schema_exists = cursor.fetchone()[0]
            
            if not schema_exists:
                cursor.close()
                conn.close()
                return HealthCheckResult(
                    container_name="schema-verify",
                    check_type="schema_verification",
                    passed=False,
                    message="Poststack schema does not exist",
                    response_time=time.time() - start_time
                )
            
            # Check required tables exist
            required_tables = ['system_info', 'services', 'containers']
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'poststack'
                AND table_name = ANY(%s)
            """, (required_tables,))
            
            existing_tables = [row[0] for row in cursor.fetchall()]
            missing_tables = set(required_tables) - set(existing_tables)
            
            if missing_tables:
                cursor.close()
                conn.close()
                return HealthCheckResult(
                    container_name="schema-verify",
                    check_type="schema_verification",
                    passed=False,
                    message=f"Missing required tables: {', '.join(missing_tables)}",
                    response_time=time.time() - start_time
                )
            
            # Check migration tables exist
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name IN ('schema_migrations', 'schema_migration_lock')
            """)
            migration_tables = [row[0] for row in cursor.fetchall()]
            
            # Get schema version
            schema_version = "unknown"
            try:
                cursor.execute("""
                    SELECT value FROM poststack.system_info 
                    WHERE key = 'schema_version'
                """)
                result = cursor.fetchone()
                if result:
                    schema_version = result[0]
            except:
                pass
            
            cursor.close()
            conn.close()
            
            return HealthCheckResult(
                container_name="schema-verify",
                check_type="schema_verification",
                passed=True,
                message=f"Schema verification passed - version {schema_version}",
                response_time=time.time() - start_time,
                details={
                    "schema_version": schema_version,
                    "tables": existing_tables,
                    "migration_tables": migration_tables
                }
            )
            
        except Exception as e:
            logger.error(f"Schema verification failed: {e}")
            return HealthCheckResult(
                container_name="schema-verify",
                check_type="schema_verification",
                passed=False,
                message=f"Schema verification error: {e}",
                response_time=time.time() - start_time
            )
    
    def get_schema_status(self, database_url: str) -> Dict[str, Any]:
        """Get comprehensive schema status information."""
        logger.info("Getting schema status")
        
        try:
            # Get migration status
            migration_runner = self._get_migration_runner(database_url)
            migration_status = migration_runner.status()
            
            # Verify schema
            verification = self.verify_schema(database_url)
            
            # Get database info
            db_info = self.database_manager.get_database_info(database_url)
            
            return {
                "verification": {
                    "passed": verification.passed,
                    "message": verification.message,
                    "details": verification.details or {}
                },
                "migration": {
                    "current_version": migration_status.current_version,
                    "applied_count": len(migration_status.applied_migrations),
                    "pending_count": len(migration_status.pending_migrations),
                    "is_locked": migration_status.is_locked,
                    "lock_info": migration_status.lock_info
                },
                "database": db_info
            }
            
        except Exception as e:
            logger.error(f"Failed to get schema status: {e}")
            return {
                "error": str(e),
                "verification": {"passed": False, "message": f"Error: {e}"},
                "migration": {"current_version": None, "error": str(e)},
                "database": {}
            }
    
    def get_migration_status(self, database_url: str) -> Dict[str, Any]:
        """Get detailed migration status."""
        try:
            migration_runner = self._get_migration_runner(database_url)
            status = migration_runner.status()
            
            return {
                "current_version": status.current_version,
                "applied_migrations": [
                    {
                        "version": m.version,
                        "description": m.description,
                        "applied_at": m.applied_at.isoformat() if m.applied_at else None,
                        "execution_time_ms": m.execution_time_ms,
                        "applied_by": m.applied_by
                    }
                    for m in status.applied_migrations
                ],
                "pending_migrations": [
                    {
                        "version": m.version,
                        "name": m.name,
                        "description": m.get_description()
                    }
                    for m in status.pending_migrations
                ],
                "is_locked": status.is_locked,
                "lock_info": status.lock_info
            }
        except Exception as e:
            logger.error(f"Failed to get migration status: {e}")
            return {"error": str(e)}
    
    def verify_migrations(self, database_url: str) -> Dict[str, Any]:
        """Verify all applied migrations match their checksums."""
        try:
            migration_runner = self._get_migration_runner(database_url)
            verification = migration_runner.verify()
            
            return {
                "valid": verification.valid,
                "errors": verification.errors,
                "warnings": verification.warnings
            }
        except Exception as e:
            logger.error(f"Failed to verify migrations: {e}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": []
            }
    
    def force_unlock_migrations(self, database_url: str) -> bool:
        """Force release the migration lock."""
        try:
            migration_runner = self._get_migration_runner(database_url)
            return migration_runner.force_unlock()
        except Exception as e:
            logger.error(f"Failed to force unlock migrations: {e}")
            return False