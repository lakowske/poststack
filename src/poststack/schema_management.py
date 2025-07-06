"""
Schema management module for Poststack

Provides database schema management using Liquibase containers.
Integrates with Phase 5 container runtime capabilities.
"""

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import PoststackConfig
from .container_runtime import LiquibaseRunner
from .database_operations import DatabaseManager, DatabaseURL
from .models import HealthCheckResult, RuntimeResult, RuntimeStatus

logger = logging.getLogger(__name__)


class SchemaManagementError(Exception):
    """Schema management related errors."""
    pass


class SchemaManager:
    """Schema management using Liquibase containers."""
    
    def __init__(self, config: PoststackConfig):
        """Initialize schema manager."""
        self.config = config
        self.liquibase_runner = LiquibaseRunner(config)
        self.database_manager = DatabaseManager(config)
    
    def create_default_changelog(self) -> str:
        """Create default Liquibase changelog for Poststack."""
        changelog_content = """<?xml version="1.0" encoding="UTF-8"?>
<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog
                   http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-4.3.xsd">

    <!-- Poststack Core Schema -->
    <changeSet id="1" author="poststack">
        <comment>Create poststack schema</comment>
        <sql>CREATE SCHEMA IF NOT EXISTS poststack;</sql>
    </changeSet>

    <!-- System Information Table -->
    <changeSet id="2" author="poststack">
        <comment>Create system_info table</comment>
        <createTable schemaName="poststack" tableName="system_info">
            <column name="id" type="SERIAL">
                <constraints primaryKey="true"/>
            </column>
            <column name="key" type="VARCHAR(255)">
                <constraints nullable="false" unique="true"/>
            </column>
            <column name="value" type="TEXT"/>
            <column name="created_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
            <column name="updated_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
        </createTable>
    </changeSet>

    <!-- Services Table -->
    <changeSet id="3" author="poststack">
        <comment>Create services table</comment>
        <createTable schemaName="poststack" tableName="services">
            <column name="id" type="SERIAL">
                <constraints primaryKey="true"/>
            </column>
            <column name="name" type="VARCHAR(255)">
                <constraints nullable="false" unique="true"/>
            </column>
            <column name="type" type="VARCHAR(100)">
                <constraints nullable="false"/>
            </column>
            <column name="status" type="VARCHAR(50)" defaultValue="stopped"/>
            <column name="config" type="JSONB"/>
            <column name="created_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
            <column name="updated_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
        </createTable>
    </changeSet>

    <!-- Containers Table -->
    <changeSet id="4" author="poststack">
        <comment>Create containers table</comment>
        <createTable schemaName="poststack" tableName="containers">
            <column name="id" type="SERIAL">
                <constraints primaryKey="true"/>
            </column>
            <column name="service_id" type="INTEGER">
                <constraints nullable="true" 
                           foreignKeyName="fk_containers_service"
                           referencedTableSchemaName="poststack"
                           referencedTableName="services"
                           referencedColumnNames="id"
                           deleteCascade="true"/>
            </column>
            <column name="container_id" type="VARCHAR(255)">
                <constraints unique="true"/>
            </column>
            <column name="image" type="VARCHAR(255)">
                <constraints nullable="false"/>
            </column>
            <column name="status" type="VARCHAR(50)" defaultValue="created"/>
            <column name="config" type="JSONB"/>
            <column name="created_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
            <column name="updated_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
        </createTable>
    </changeSet>

    <!-- Certificates Table -->
    <changeSet id="5" author="poststack">
        <comment>Create certificates table</comment>
        <createTable schemaName="poststack" tableName="certificates">
            <column name="id" type="SERIAL">
                <constraints primaryKey="true"/>
            </column>
            <column name="domain" type="VARCHAR(255)">
                <constraints nullable="false" unique="true"/>
            </column>
            <column name="status" type="VARCHAR(50)" defaultValue="pending"/>
            <column name="cert_path" type="TEXT"/>
            <column name="key_path" type="TEXT"/>
            <column name="expires_at" type="TIMESTAMP"/>
            <column name="created_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
            <column name="updated_at" type="TIMESTAMP" defaultValueComputed="CURRENT_TIMESTAMP"/>
        </createTable>
    </changeSet>

    <!-- Indexes -->
    <changeSet id="6" author="poststack">
        <comment>Create performance indexes</comment>
        <createIndex schemaName="poststack" tableName="services" indexName="idx_services_type">
            <column name="type"/>
        </createIndex>
        <createIndex schemaName="poststack" tableName="services" indexName="idx_services_status">
            <column name="status"/>
        </createIndex>
        <createIndex schemaName="poststack" tableName="containers" indexName="idx_containers_status">
            <column name="status"/>
        </createIndex>
        <createIndex schemaName="poststack" tableName="certificates" indexName="idx_certificates_domain">
            <column name="domain"/>
        </createIndex>
        <createIndex schemaName="poststack" tableName="certificates" indexName="idx_certificates_expires_at">
            <column name="expires_at"/>
        </createIndex>
    </changeSet>

    <!-- Initial System Data -->
    <changeSet id="7" author="poststack">
        <comment>Insert initial system information</comment>
        <insert schemaName="poststack" tableName="system_info">
            <column name="key" value="schema_version"/>
            <column name="value" value="2.0.0"/>
        </insert>
        <insert schemaName="poststack" tableName="system_info">
            <column name="key" value="created_by"/>
            <column name="value" value="poststack-liquibase"/>
        </insert>
        <insert schemaName="poststack" tableName="system_info">
            <column name="key" value="poststack_version"/>
            <column name="value" value="0.1.0"/>
        </insert>
    </changeSet>

</databaseChangeLog>
"""
        return changelog_content
    
    def write_changelog_to_temp(self, changelog_content: str) -> Path:
        """Write changelog to temporary file."""
        temp_dir = Path(tempfile.mkdtemp(prefix="poststack_liquibase_"))
        changelog_path = temp_dir / "changelog.xml"
        
        changelog_path.write_text(changelog_content)
        logger.info(f"Wrote changelog to {changelog_path}")
        
        return changelog_path
    
    def run_liquibase_command(
        self,
        command: str,
        database_url: str,
        changelog_path: Optional[Path] = None,
        timeout: int = 300
    ) -> RuntimeResult:
        """Run Liquibase command using container."""
        logger.info(f"Running Liquibase command: {command}")
        
        try:
            # Validate database URL
            db_url = self.database_manager.validate_database_url(database_url)
            
            # Use default changelog if none provided
            if changelog_path is None:
                changelog_content = self.create_default_changelog()
                changelog_path = self.write_changelog_to_temp(changelog_content)
            
            # Run Liquibase command
            result = self.liquibase_runner.run_liquibase_command(
                command=command,
                database_url=database_url,
                changelog_file=str(changelog_path),
                timeout=timeout
            )
            
            logger.info(f"Liquibase {command} completed with status: {result.status.value}")
            return result
            
        except Exception as e:
            logger.error(f"Liquibase command {command} failed: {e}")
            result = RuntimeResult(
                container_name="liquibase-temp",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.FAILED
            )
            result.add_logs(f"Liquibase command failed: {e}")
            return result
    
    def health_check_liquibase(self, database_url: str) -> HealthCheckResult:
        """Check if Liquibase can connect to database."""
        logger.info("Performing Liquibase health check")
        
        start_time = time.time()
        
        try:
            # Test Liquibase status command
            result = self.run_liquibase_command("status", database_url, timeout=60)
            
            response_time = time.time() - start_time
            
            if result.success:
                return HealthCheckResult(
                    container_name="liquibase-health",
                    check_type="liquibase_health",
                    passed=True,
                    message="Liquibase health check passed",
                    response_time=response_time,
                    details={"status_output": result.logs}
                )
            else:
                return HealthCheckResult(
                    container_name="liquibase-health",
                    check_type="liquibase_health",
                    passed=False,
                    message=f"Liquibase health check failed: {result.logs}",
                    response_time=response_time
                )
                
        except Exception as e:
            logger.error(f"Liquibase health check failed: {e}")
            return HealthCheckResult(
                container_name="liquibase-health",
                check_type="liquibase_health",
                passed=False,
                message=f"Liquibase health check error: {e}",
                response_time=time.time() - start_time
            )
    
    def initialize_schema(self, database_url: str) -> RuntimeResult:
        """Initialize Poststack schema using Liquibase."""
        logger.info("Initializing Poststack schema")
        
        try:
            # Test database connection first
            connection_test = self.database_manager.test_connection(database_url)
            if not connection_test.passed:
                result = RuntimeResult(
                    container_name="schema-init",
                    image_name="poststack/liquibase:latest",
                    status=RuntimeStatus.FAILED
                )
                result.add_logs(f"Database connection failed: {connection_test.message}")
                return result
            
            # Run Liquibase update
            result = self.run_liquibase_command("update", database_url)
            
            if result.success:
                logger.info("Schema initialization completed successfully")
                
                # Verify schema was created
                verification = self.verify_schema(database_url)
                if verification.passed:
                    success_result = RuntimeResult(
                        container_name=result.container_name,
                        image_name=result.image_name,
                        status=RuntimeStatus.STOPPED
                    )
                    success_result.add_logs(f"Schema initialized successfully. {verification.message}")
                    return success_result
                else:
                    failure_result = RuntimeResult(
                        container_name=result.container_name,
                        image_name=result.image_name,
                        status=RuntimeStatus.FAILED
                    )
                    failure_result.add_logs(f"Schema initialization failed verification: {verification.message}")
                    return failure_result
            else:
                logger.error(f"Schema initialization failed: {result.logs}")
                return result
                
        except Exception as e:
            logger.error(f"Schema initialization error: {e}")
            result = RuntimeResult(
                container_name="schema-init",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.FAILED
            )
            result.add_logs(f"Schema initialization error: {e}")
            return result
    
    def update_schema(self, database_url: str, changelog_path: Optional[Path] = None) -> RuntimeResult:
        """Update schema using Liquibase."""
        logger.info("Updating Poststack schema")
        
        try:
            # Run Liquibase update
            result = self.run_liquibase_command("update", database_url, changelog_path)
            
            if result.success:
                logger.info("Schema update completed successfully")
            else:
                logger.error(f"Schema update failed: {result.logs}")
            
            return result
            
        except Exception as e:
            logger.error(f"Schema update error: {e}")
            result = RuntimeResult(
                container_name="schema-update",
                image_name="poststack/liquibase:latest",
                status=RuntimeStatus.FAILED
            )
            result.add_logs(f"Schema update error: {e}")
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
            required_tables = ['system_info', 'services', 'containers', 'certificates']
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
            
            # Check Liquibase tables exist (databasechangelog, databasechangeloglock)
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_name IN ('databasechangelog', 'databasechangeloglock')
            """)
            liquibase_tables = [row[0] for row in cursor.fetchall()]
            
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
                    "liquibase_tables": liquibase_tables
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
            # Get Liquibase status
            liquibase_result = self.run_liquibase_command("status", database_url, timeout=60)
            
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
                "liquibase": {
                    "status": liquibase_result.status.value,
                    "output": liquibase_result.logs
                },
                "database": db_info
            }
            
        except Exception as e:
            logger.error(f"Failed to get schema status: {e}")
            return {
                "error": str(e),
                "verification": {"passed": False, "message": f"Error: {e}"},
                "liquibase": {"status": "failed", "output": str(e)},
                "database": {}
            }