"""
Pytest configuration and fixtures for Poststack tests.

Provides common fixtures and test utilities across all test modules.
"""

import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from poststack.config import PoststackConfig
from poststack.logging_config import setup_logging


@pytest.fixture(scope="session")
def test_logs_dir() -> Generator[str, None, None]:
    """
    Create temporary directory for test logs that persists for the session.

    Yields:
        Path to temporary logs directory
    """
    temp_dir = tempfile.mkdtemp(prefix="poststack_test_logs_")
    logs_dir = Path(temp_dir) / "logs"
    logs_dir.mkdir(parents=True)

    # Create subdirectories
    (logs_dir / "containers").mkdir()
    (logs_dir / "database").mkdir()

    yield str(logs_dir)

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def isolated_test_env(test_logs_dir: str) -> Generator[dict[str, str], None, None]:
    """
    Create isolated test environment with clean environment variables.

    Args:
        test_logs_dir: Test logs directory from session fixture

    Yields:
        Dictionary of original environment variables
    """
    # Save original environment
    original_env = os.environ.copy()

    # Set test environment variables
    test_env = {
        "POSTSTACK_TEST_MODE": "true",
        "POSTSTACK_LOG_DIR": test_logs_dir,
        "POSTSTACK_LOG_LEVEL": "DEBUG",
        "POSTSTACK_VERBOSE": "true",
    }

    # Clear poststack-related environment variables
    for key in list(os.environ.keys()):
        if key.startswith("POSTSTACK_") or key == "DATABASE_URL":
            del os.environ[key]

    # Set test environment
    os.environ.update(test_env)

    yield original_env

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def test_config(isolated_test_env: dict[str, str]) -> PoststackConfig:
    """
    Create test configuration with safe defaults.

    Args:
        isolated_test_env: Isolated environment fixture

    Returns:
        Test configuration instance
    """
    return PoststackConfig(
        log_level="DEBUG",
        verbose=True,
        debug=True,
        test_mode=True,
        log_dir=os.environ["POSTSTACK_LOG_DIR"],
    )


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """
    Create temporary workspace directory for test files.

    Yields:
        Path to temporary workspace
    """
    temp_dir = tempfile.mkdtemp(prefix="poststack_workspace_")
    workspace = Path(temp_dir)

    yield workspace

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def test_logger(test_config: PoststackConfig):
    """
    Configure logging for tests.

    Args:
        test_config: Test configuration

    Returns:
        Configured logger instance
    """
    return setup_logging(
        log_dir=test_config.log_dir,
        verbose=test_config.verbose,
        log_level=test_config.log_level,
        enable_file_logging=False,  # Disable file logging for most tests
    )


@pytest.fixture
def sample_database_url() -> str:
    """
    Provide sample database URL for testing.

    Returns:
        Test database URL
    """
    return "postgresql://test_user:test_password@localhost:5432/test_db"


@pytest.fixture
def mock_environment_vars(isolated_test_env: dict[str, str]) -> dict[str, str]:
    """
    Set up mock environment variables for testing.

    Args:
        isolated_test_env: Isolated environment fixture

    Returns:
        Dictionary of mock environment variables
    """
    mock_vars = {
        "POSTSTACK_DOMAIN_NAME": "test.example.com",
        "POSTSTACK_LE_EMAIL": "test@example.com",
        "POSTSTACK_DATABASE_URL": "postgresql://test_user:test_password@localhost:5432/test_db",
        "POSTSTACK_CONTAINER_RUNTIME": "podman",
        "POSTSTACK_DEBUG": "true",
    }

    os.environ.update(mock_vars)
    return mock_vars


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "container: marks tests that require containers")
    config.addinivalue_line("markers", "database: marks tests that require database")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers automatically."""
    for item in items:
        # Add markers based on test path/name
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)

        if "container" in item.nodeid:
            item.add_marker(pytest.mark.container)

        if "database" in item.nodeid:
            item.add_marker(pytest.mark.database)

        # Mark slow tests
        if any(keyword in item.nodeid for keyword in ["slow", "performance"]):
            item.add_marker(pytest.mark.slow)


@pytest.fixture
def assert_no_logs_leaked():
    """
    Fixture to ensure no log files are leaked during tests.

    This fixture can be used to verify that tests properly clean up
    any log files they create.
    """
    import logging

    # Get all loggers before test
    initial_loggers = list(logging.Logger.manager.loggerDict.keys())

    yield

    # Check for new loggers after test
    final_loggers = list(logging.Logger.manager.loggerDict.keys())
    new_loggers = set(final_loggers) - set(initial_loggers)

    # Filter out expected new loggers (poststack loggers are OK)
    unexpected_loggers = [
        name for name in new_loggers if not name.startswith("poststack")
    ]

    if unexpected_loggers:
        pytest.fail(f"Test leaked loggers: {unexpected_loggers}")


# Test utilities
class TestHelper:
    """Helper class for common test operations."""

    @staticmethod
    def create_test_file(path: Path, content: str) -> None:
        """Create a test file with given content."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    @staticmethod
    def assert_file_exists(path: Path, message: str = "") -> None:
        """Assert that a file exists."""
        assert path.exists(), f"File does not exist: {path}. {message}"

    @staticmethod
    def assert_directory_exists(path: Path, message: str = "") -> None:
        """Assert that a directory exists."""
        assert path.is_dir(), f"Directory does not exist: {path}. {message}"


@pytest.fixture
def test_helper() -> TestHelper:
    """Provide test helper utilities."""
    return TestHelper()
