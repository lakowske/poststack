"""
Tests for configuration management module.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from poststack.config import PoststackConfig, get_default_config, load_config


class TestPoststackConfig:
    """Test PoststackConfig class."""

    def test_default_configuration(self, isolated_test_env):
        """Test default configuration values."""
        # Clear any test environment overrides
        test_vars = [
            "POSTSTACK_LOG_LEVEL",
            "POSTSTACK_LOG_DIR",
            "POSTSTACK_VERBOSE",
            "POSTSTACK_TEST_MODE",
        ]
        for var in test_vars:
            if var in os.environ:
                del os.environ[var]

        config = PoststackConfig()

        assert config.log_level == "INFO"
        assert config.log_dir == "logs"
        assert config.verbose is False
        assert config.container_runtime == "podman"
        assert config.debug is False
        assert config.test_mode is False

    def test_environment_variable_loading(self, isolated_test_env):
        """Test loading configuration from environment variables."""
        # Set environment variables
        os.environ.update(
            {
                "POSTSTACK_LOG_LEVEL": "DEBUG",
                "POSTSTACK_VERBOSE": "true",
                "POSTSTACK_DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            }
        )

        config = PoststackConfig()

        assert config.log_level == "DEBUG"
        assert config.verbose is True
        assert config.database_url == "postgresql://user:pass@localhost:5432/db"

    def test_database_url_validation(self, isolated_test_env):
        """Test database URL validation."""
        # Valid URLs
        valid_urls = [
            "postgresql://user:pass@localhost:5432/db",
            "postgres://user:pass@localhost:5432/db",
        ]

        for url in valid_urls:
            config = PoststackConfig(database_url=url)
            assert config.database_url == url

        # Invalid URL
        with pytest.raises(ValueError, match="database_url must start with"):
            PoststackConfig(database_url="mysql://user:pass@localhost:3306/db")

    def test_log_level_validation(self, isolated_test_env):
        """Test log level validation."""
        # Valid levels
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        for level in valid_levels:
            config = PoststackConfig(log_level=level)
            assert config.log_level == level

        # Case insensitive
        config = PoststackConfig(log_level="debug")
        assert config.log_level == "DEBUG"

        # Invalid level
        with pytest.raises(ValueError, match="log_level must be one of"):
            PoststackConfig(log_level="INVALID")

    def test_container_runtime_validation(self, isolated_test_env):
        """Test container runtime validation."""
        # Valid runtimes
        for runtime in ["podman", "docker"]:
            config = PoststackConfig(container_runtime=runtime)
            assert config.container_runtime == runtime

        # Case insensitive
        config = PoststackConfig(container_runtime="PODMAN")
        assert config.container_runtime == "podman"

        # Invalid runtime
        with pytest.raises(ValueError, match="container_runtime must be one of"):
            PoststackConfig(container_runtime="invalid")

    def test_migrations_path_validation(self, isolated_test_env):
        """Test migrations path validation."""
        # Valid path
        config = PoststackConfig(migrations_path="./migrations")
        assert config.migrations_path == "./migrations"

    def test_configuration_properties(self, isolated_test_env):
        """Test configuration property methods."""
        # Mock auto-detection to return None for clean testing
        with patch.object(PoststackConfig, 'get_auto_detected_database_url', return_value=None):
            # Without database URL
            config = PoststackConfig()
            assert not config.is_database_configured

            # With database URL
            config = PoststackConfig(
                database_url="postgresql://user:pass@localhost:5432/db"
            )
            assert config.is_database_configured

    def test_path_properties(self, isolated_test_env):
        """Test path property methods."""
        config = PoststackConfig(log_dir="test_logs")

        assert config.get_log_dir_path() == Path("test_logs")

    def test_create_directories(self, temp_workspace):
        """Test directory creation."""
        log_dir = temp_workspace / "logs"

        config = PoststackConfig(log_dir=str(log_dir))

        config.create_directories()

        assert log_dir.exists()
        assert (log_dir / "containers").exists()
        assert (log_dir / "database").exists()

    def test_mask_sensitive_values(self, isolated_test_env):
        """Test sensitive value masking."""
        config = PoststackConfig(
            database_url="postgresql://user:password123@localhost:5432/db"
        )

        masked = config.mask_sensitive_values()
        assert "password123" not in masked["database_url"]
        assert "postgresql://user:***@localhost:5432/db" == masked["database_url"]

    def test_from_cli_args(self, isolated_test_env):
        """Test configuration from CLI arguments."""
        config = PoststackConfig.from_cli_args(
            database_url="postgresql://cli:pass@localhost:5432/cli_db",
            verbose=True,
            log_level="DEBUG",
            debug=True,
        )

        assert config.database_url == "postgresql://cli:pass@localhost:5432/cli_db"
        assert config.verbose is True
        assert config.log_level == "DEBUG"
        assert config.debug is True


class TestConfigurationLoading:
    """Test configuration loading functions."""

    def test_load_config_default(self, isolated_test_env, temp_workspace):
        """Test loading default configuration."""
        # Clear any test environment overrides and set safe paths
        test_vars = ["POSTSTACK_LOG_LEVEL", "POSTSTACK_LOG_DIR", "POSTSTACK_VERBOSE"]
        for var in test_vars:
            if var in os.environ:
                del os.environ[var]

        # Set safe paths for test
        os.environ["POSTSTACK_LOG_DIR"] = str(temp_workspace / "logs")
        os.environ["POSTSTACK_CERT_PATH"] = str(temp_workspace / "certs")

        config = load_config()
        assert isinstance(config, PoststackConfig)
        assert config.log_level == "INFO"

    def test_load_config_with_cli_overrides(self, isolated_test_env, temp_workspace):
        """Test loading configuration with CLI overrides."""
        # Set safe paths for test
        os.environ["POSTSTACK_CERT_PATH"] = str(temp_workspace / "certs")

        cli_overrides = {
            "verbose": True,
            "log_level": "DEBUG",
            "database_url": "postgresql://override:pass@localhost:5432/override_db",
            "log_dir": str(temp_workspace / "logs"),
        }

        config = load_config(cli_overrides=cli_overrides)

        assert config.verbose is True
        assert config.log_level == "DEBUG"
        assert (
            config.database_url
            == "postgresql://override:pass@localhost:5432/override_db"
        )

    def test_get_default_config(self):
        """Test getting default configuration for development."""
        config = get_default_config()

        assert config.log_level == "DEBUG"
        assert config.verbose is True
        assert config.debug is True
        assert config.test_mode is True


class TestConfigurationIntegration:
    """Integration tests for configuration."""

    def test_configuration_with_environment_file(
        self, temp_workspace, isolated_test_env
    ):
        """Test configuration loading with .env file."""
        env_file = temp_workspace / ".env"
        env_content = """
POSTSTACK_LOG_LEVEL=DEBUG
POSTSTACK_VERBOSE=true
POSTSTACK_DATABASE_URL=postgresql://env:pass@localhost:5432/env_db
"""
        env_file.write_text(env_content)

        # Change to temp workspace so .env file is found
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_workspace)
            config = PoststackConfig()

            assert config.log_level == "DEBUG"
            assert config.verbose is True
            assert config.database_url == "postgresql://env:pass@localhost:5432/env_db"

        finally:
            os.chdir(original_cwd)

    def test_configuration_precedence(self, temp_workspace, isolated_test_env):
        """Test configuration precedence (env vars > .env file > defaults)."""
        # Create .env file
        env_file = temp_workspace / ".env"
        env_file.write_text("POSTSTACK_LOG_LEVEL=WARNING\n")

        # Set environment variable (should override .env file)
        os.environ["POSTSTACK_LOG_LEVEL"] = "ERROR"

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_workspace)
            config = PoststackConfig()

            # Environment variable should win
            assert config.log_level == "ERROR"

        finally:
            os.chdir(original_cwd)
