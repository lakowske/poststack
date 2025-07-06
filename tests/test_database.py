"""
Tests for Phase 6: Database Integration

Tests database connectivity, verification, and management using
containerized PostgreSQL instances.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from poststack.config import PoststackConfig
from poststack.database_operations import DatabaseManager, DatabaseURL, DatabaseConnectionError, DatabaseValidationError
from poststack.models import HealthCheckResult, RuntimeResult, RuntimeStatus


class TestDatabaseURL:
    """Test database URL parsing and validation."""
    
    def test_valid_postgresql_url(self):
        """Test parsing valid PostgreSQL URL."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        db_url = DatabaseURL(url)
        
        assert db_url.hostname == "localhost"
        assert db_url.port == 5432
        assert db_url.database == "testdb"
        assert db_url.username == "user"
        assert db_url.password == "pass"
    
    def test_valid_postgres_url(self):
        """Test parsing valid postgres:// URL."""
        url = "postgres://user:pass@localhost:5432/testdb"
        db_url = DatabaseURL(url)
        
        assert db_url.hostname == "localhost"
        assert db_url.port == 5432
        assert db_url.database == "testdb"
        assert db_url.username == "user"
        assert db_url.password == "pass"
    
    def test_url_with_defaults(self):
        """Test URL parsing with default values."""
        url = "postgresql://localhost/testdb"
        db_url = DatabaseURL(url)
        
        assert db_url.hostname == "localhost"
        assert db_url.port == 5432
        assert db_url.database == "testdb"
        assert db_url.username == "postgres"
        assert db_url.password == ""
    
    def test_masked_url(self):
        """Test password masking in URLs."""
        url = "postgresql://user:secret123@localhost:5432/testdb"
        db_url = DatabaseURL(url)
        
        masked = db_url.get_masked_url()
        assert "secret123" not in masked
        assert "user:***@" in masked
    
    def test_invalid_url_scheme(self):
        """Test invalid URL scheme."""
        with pytest.raises(DatabaseValidationError, match="must start with postgresql://"):
            DatabaseURL("mysql://user:pass@localhost/db")
    
    def test_empty_url(self):
        """Test empty URL."""
        with pytest.raises(DatabaseValidationError, match="cannot be empty"):
            DatabaseURL("")
    
    def test_malformed_url(self):
        """Test malformed URL."""
        with pytest.raises(DatabaseValidationError, match="Invalid database URL format"):
            DatabaseURL("postgresql://[invalid")
    
    @patch('poststack.database_operations.socket.socket')
    def test_connectivity_test_success(self, mock_socket):
        """Test successful connectivity test."""
        mock_socket_instance = Mock()
        mock_socket_instance.connect_ex.return_value = 0
        mock_socket.return_value.__enter__.return_value = mock_socket_instance
        
        db_url = DatabaseURL("postgresql://localhost:5432/test")
        result = db_url.test_connectivity()
        
        assert result is True
        mock_socket_instance.connect_ex.assert_called_once_with(("localhost", 5432))
    
    @patch('poststack.database_operations.socket.socket')
    def test_connectivity_test_failure(self, mock_socket):
        """Test failed connectivity test."""
        mock_socket_instance = Mock()
        mock_socket_instance.connect_ex.return_value = 1  # Connection failed
        mock_socket.return_value.__enter__.return_value = mock_socket_instance
        
        db_url = DatabaseURL("postgresql://localhost:5432/test")
        result = db_url.test_connectivity()
        
        assert result is False


class TestDatabaseManager:
    """Test database management operations."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return PoststackConfig(test_mode=True)
    
    @pytest.fixture
    def db_manager(self, config):
        """Create database manager instance."""
        return DatabaseManager(config)
    
    def test_database_manager_initialization(self, db_manager):
        """Test database manager initialization."""
        assert db_manager.config is not None
        assert db_manager.container_manager is not None
        assert db_manager.postgres_runner is not None
    
    def test_validate_database_url_success(self, db_manager):
        """Test successful database URL validation."""
        url = "postgresql://user:pass@localhost:5432/testdb"
        
        db_url = db_manager.validate_database_url(url)
        
        assert isinstance(db_url, DatabaseURL)
        assert db_url.hostname == "localhost"
        assert db_url.port == 5432
    
    def test_validate_database_url_failure(self, db_manager):
        """Test database URL validation failure."""
        with pytest.raises(DatabaseValidationError):
            db_manager.validate_database_url("invalid-url")
    
    def test_connection_test_success(self, db_manager):
        """Test successful database connection test."""
        with patch('psycopg2.connect') as mock_connect:
            # Mock database connection
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.side_effect = [
                ("PostgreSQL 15.0", "testdb", "testuser"),  # version, db, user
                (5,)  # table count
            ]
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            
            # Mock URL validation and connectivity
            with patch.object(db_manager, 'validate_database_url') as mock_validate:
                mock_db_url = Mock()
                mock_db_url.test_connectivity.return_value = True
                mock_db_url.hostname = "localhost"
                mock_db_url.port = 5432
                mock_db_url.database = "testdb"
                mock_db_url.username = "testuser"
                mock_db_url.password = "testpass"
                mock_db_url.get_masked_url.return_value = "postgresql://testuser:***@localhost:5432/testdb"
                mock_validate.return_value = mock_db_url
                
                result = db_manager.test_connection("postgresql://testuser:testpass@localhost:5432/testdb")
                
                assert result.passed is True
                assert "connection successful" in result.message.lower()
                assert result.details["database"] == "testdb"
                assert result.details["user"] == "testuser"
    
    def test_connection_test_psycopg2_missing(self, db_manager):
        """Test connection test with missing psycopg2."""
        with patch('psycopg2.connect', side_effect=ImportError("No module named 'psycopg2'")):
            with patch.object(db_manager, 'validate_database_url') as mock_validate:
                mock_db_url = Mock()
                mock_db_url.test_connectivity.return_value = True
                mock_validate.return_value = mock_db_url
                
                result = db_manager.test_connection("postgresql://localhost/test")
                
                assert result.passed is False
                assert "psycopg2 not available" in result.message
    
    def test_connection_test_port_not_accessible(self, db_manager):
        """Test connection test with inaccessible port."""
        with patch.object(db_manager, 'validate_database_url') as mock_validate:
            mock_db_url = Mock()
            mock_db_url.test_connectivity.return_value = False
            mock_db_url.hostname = "localhost"
            mock_db_url.port = 5432
            mock_validate.return_value = mock_db_url
            
            result = db_manager.test_connection("postgresql://localhost/test")
            
            assert result.passed is False
            assert "Cannot connect to database port" in result.message
    
    def test_connection_test_with_container(self, db_manager):
        """Test connection test using container."""
        with patch.object(db_manager.container_manager, 'start_test_environment') as mock_start:
            with patch.object(db_manager.container_manager, 'cleanup_test_environment') as mock_cleanup:
                with patch.object(db_manager, 'validate_database_url') as mock_validate:
                    # Mock successful container start
                    mock_postgres_result = Mock()
                    mock_postgres_result.success = True
                    mock_health_result = Mock()
                    mock_health_result.passed = True
                    mock_start.return_value = (mock_postgres_result, mock_health_result)
                    
                    # Mock URL validation
                    mock_db_url = Mock()
                    mock_db_url.test_connectivity.return_value = False  # Port not accessible
                    mock_db_url.port = 5432
                    mock_db_url.hostname = "localhost"
                    mock_validate.return_value = mock_db_url
                    
                    result = db_manager.test_connection(
                        "postgresql://localhost/test",
                        use_container=True,
                        container_port=5433
                    )
                    
                    # Should attempt container start
                    mock_start.assert_called_once_with(postgres_port=5433)
                    # Should cleanup after test
                    mock_cleanup.assert_called_once()
    
    def test_verify_database_requirements_success(self, db_manager):
        """Test successful database requirements verification."""
        with patch('psycopg2.connect') as mock_connect:
            # Mock database connection
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.side_effect = [
                (150000,),  # PostgreSQL 15.0
                (True,),    # uuid-ossp extension available
            ]
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            
            # Mock successful connection test
            with patch.object(db_manager, 'test_connection') as mock_test:
                mock_test.return_value = HealthCheckResult(
                    container_name="test",
                    check_type="connection",
                    passed=True,
                    message="Connection successful"
                )
                
                with patch.object(db_manager, 'validate_database_url') as mock_validate:
                    mock_db_url = Mock()
                    mock_db_url.hostname = "localhost"
                    mock_db_url.port = 5432
                    mock_db_url.database = "testdb"
                    mock_db_url.username = "testuser"
                    mock_db_url.password = "testpass"
                    mock_validate.return_value = mock_db_url
                    
                    result = db_manager.verify_database_requirements("postgresql://localhost/test")
                    
                    assert result.passed is True
                    assert "meets all Poststack requirements" in result.message
                    assert result.details["postgres_version"] == 150000
    
    def test_verify_database_requirements_old_version(self, db_manager):
        """Test database requirements verification with old PostgreSQL version."""
        with patch('psycopg2.connect') as mock_connect:
            # Mock database connection
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.return_value = (110000,)  # PostgreSQL 11.0 (too old)
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            
            # Mock successful connection test
            with patch.object(db_manager, 'test_connection') as mock_test:
                mock_test.return_value = HealthCheckResult(
                    container_name="test",
                    check_type="connection",
                    passed=True,
                    message="Connection successful"
                )
                
                with patch.object(db_manager, 'validate_database_url') as mock_validate:
                    mock_db_url = Mock()
                    mock_db_url.hostname = "localhost"
                    mock_db_url.port = 5432
                    mock_db_url.database = "testdb"
                    mock_db_url.username = "testuser"
                    mock_db_url.password = "testpass"
                    mock_validate.return_value = mock_db_url
                    
                    result = db_manager.verify_database_requirements("postgresql://localhost/test")
                    
                    assert result.passed is False
                    assert "too old" in result.message
    
    def test_get_database_info_success(self, db_manager):
        """Test successful database info retrieval."""
        with patch('psycopg2.connect') as mock_connect:
            # Mock database connection
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.side_effect = [
                ("PostgreSQL 15.0", "testdb", "testuser", "127.0.0.1", 5432, 1048576),  # basic info
                (10, 2),  # connection info
            ]
            mock_cursor.fetchall.return_value = [
                ("public", 5),
                ("information_schema", 50),
            ]  # schema info
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            
            with patch.object(db_manager, 'validate_database_url') as mock_validate:
                mock_db_url = Mock()
                mock_db_url.hostname = "localhost"
                mock_db_url.port = 5432
                mock_db_url.database = "testdb"
                mock_db_url.username = "testuser"
                mock_db_url.password = "testpass"
                mock_validate.return_value = mock_db_url
                
                info = db_manager.get_database_info("postgresql://localhost/test")
                
                assert info["connection"]["hostname"] == "localhost"
                assert info["connection"]["database"] == "testdb"
                assert info["server"]["size_mb"] == 1.0
                assert len(info["schemas"]) == 2
                assert info["connections"]["total"] == 10
                assert info["connections"]["active"] == 2
    
    def test_get_database_info_connection_error(self, db_manager):
        """Test database info retrieval with connection error."""
        with patch.object(db_manager, 'validate_database_url') as mock_validate:
            mock_validate.side_effect = DatabaseValidationError("Invalid URL")
            
            with pytest.raises(DatabaseConnectionError, match="Failed to get database info"):
                db_manager.get_database_info("invalid-url")