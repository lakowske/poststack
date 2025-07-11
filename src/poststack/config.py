"""
Configuration management for Poststack

Handles configuration loading from environment variables, files,
and command-line arguments using Pydantic settings.
"""

import os
import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class PoststackConfig(BaseSettings):
    """
    Main configuration class for Poststack.

    Configuration is loaded from:
    1. Environment variables (highest priority)
    2. .env file
    3. Default values (lowest priority)
    """

    model_config = SettingsConfigDict(
        env_prefix="POSTSTACK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database configuration
    database_url: Optional[str] = Field(
        default=None,
        description="PostgreSQL connection URL",
        env="DATABASE_URL",
    )

    # Logging configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    log_dir: str = Field(
        default="logs",
        description="Directory for log files",
    )
    verbose: bool = Field(
        default=False,
        description="Enable verbose console output",
    )

    # Container configuration
    container_runtime: str = Field(
        default="podman",
        description="Container runtime (podman or docker)",
    )
    container_registry: str = Field(
        default="localhost",
        description="Container registry for built images",
    )
    postgres_container_name: str = Field(
        default="poststack-postgres",
        description="Name for the PostgreSQL container",
    )
    postgres_host_port: int = Field(
        default=5432,
        description="Host port for PostgreSQL container",
    )
    project_containers_path: str = Field(
        default="./containers",
        description="Path to project-specific container definitions",
    )
    
    # Project container configuration - containers will be prefixed with project name
    project_container_prefix: str = Field(
        default="",
        description="Prefix for project container names (auto-detected from directory if empty)",
    )
    project_container_network: str = Field(
        default="bridge",
        description="Network mode for project containers",
    )
    project_container_restart_policy: str = Field(
        default="unless-stopped",
        description="Restart policy for project containers",
    )


    # Migration configuration
    migrations_path: str = Field(
        default="./migrations",
        description="Path to database migration files",
    )

    # Development configuration
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )
    test_mode: bool = Field(
        default=False,
        description="Enable test mode",
    )

    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of: {', '.join(valid_levels)}")
        return v.upper()

    @validator("container_runtime")
    def validate_container_runtime(cls, v: str) -> str:
        """Validate container runtime is supported."""
        valid_runtimes = ["podman", "docker"]
        if v.lower() not in valid_runtimes:
            raise ValueError(
                f"container_runtime must be one of: {', '.join(valid_runtimes)}"
            )
        return v.lower()

    @validator("database_url")
    def validate_database_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate database URL format if provided."""
        if v is None:
            return v

        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "database_url must start with 'postgresql://' or 'postgres://'"
            )

        return v


    @property
    def is_database_configured(self) -> bool:
        """Check if database is configured (explicitly or auto-detected)."""
        return self.database_url is not None or self.get_auto_detected_database_url() is not None

    def get_auto_detected_database_url(self) -> Optional[str]:
        """Auto-detect database URL from running PostgreSQL containers."""
        try:
            # Import here to avoid circular imports
            from .container_runtime import PostgreSQLRunner
            
            postgres_runner = PostgreSQLRunner(self)
            auto_url = postgres_runner.get_primary_postgres_url()
            
            if auto_url:
                logger.info(f"Auto-detected PostgreSQL container: {auto_url.split('@')[1] if '@' in auto_url else auto_url}")
                return auto_url
            else:
                logger.debug("No running PostgreSQL containers found for auto-detection")
                return None
                
        except Exception as e:
            logger.debug(f"Failed to auto-detect database URL: {e}")
            return None
    
    @property
    def effective_database_url(self) -> Optional[str]:
        """Get the effective database URL (explicit or auto-detected)."""
        if self.database_url:
            return self.database_url
        
        return self.get_auto_detected_database_url()
    
    def get_project_container_prefix(self) -> str:
        """Get the effective project container prefix."""
        if self.project_container_prefix:
            return self.project_container_prefix
        
        # Auto-detect from current directory name
        import os
        return os.path.basename(os.getcwd())
    
    def get_project_container_name(self, container_name: str) -> str:
        """Get the full container name for a project container."""
        prefix = self.get_project_container_prefix()
        return f"{prefix}-{container_name}"
    
    def get_project_container_env_var(self, container_name: str, setting: str, default: any = None) -> any:
        """Get environment variable for specific project container settings."""
        # Look for container-specific environment variable
        # Format: POSTSTACK_<CONTAINER>_<SETTING>
        env_var_name = f"POSTSTACK_{container_name.upper()}_{setting.upper()}"
        
        value = os.getenv(env_var_name)
        if value is not None:
            # Convert string values to appropriate types
            if setting.endswith('_port') or setting == 'port':
                try:
                    return int(value)
                except ValueError:
                    logger.warning(f"Invalid port value for {env_var_name}: {value}")
                    return default
            elif setting in ['enabled', 'auto_start']:
                return value.lower() in ('true', '1', 'yes', 'on')
            return value
        
        return default

    def get_log_dir_path(self) -> Path:
        """Get log directory as Path object."""
        return Path(self.log_dir)


    def create_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        # Create log directory structure
        log_path = self.get_log_dir_path()
        log_path.mkdir(exist_ok=True)
        (log_path / "containers").mkdir(exist_ok=True)
        (log_path / "database").mkdir(exist_ok=True)

    def mask_sensitive_values(self) -> dict[str, str]:
        """Get configuration dict with sensitive values masked."""
        config_dict = self.model_dump()

        # Mask sensitive fields
        if config_dict.get("database_url"):
            import re

            config_dict["database_url"] = re.sub(
                r"(postgresql://[^:]+:)[^@]+(@.*)",
                r"\1***\2",
                config_dict["database_url"],
            )

        return config_dict

    @classmethod
    def from_cli_args(
        cls,
        database_url: Optional[str] = None,
        verbose: bool = False,
        log_dir: str = "logs",
        log_level: Optional[str] = None,
        **kwargs,
    ) -> "PoststackConfig":
        """
        Create configuration from CLI arguments.

        Args:
            database_url: Database connection URL
            verbose: Enable verbose output
            log_dir: Log directory
            log_level: Log level override
            **kwargs: Additional configuration options

        Returns:
            Configured PoststackConfig instance
        """
        # Build config dict from provided arguments
        config_data = {
            "verbose": verbose,
            "log_dir": log_dir,
        }

        if database_url:
            config_data["database_url"] = database_url

        if log_level:
            config_data["log_level"] = log_level

        # Add any additional kwargs
        config_data.update(kwargs)

        return cls(**config_data)


def load_config(
    config_file: Optional[str] = None,
    cli_overrides: Optional[dict] = None,
) -> PoststackConfig:
    """
    Load configuration with optional file and CLI overrides.

    Args:
        config_file: Optional configuration file path
        cli_overrides: CLI argument overrides

    Returns:
        Loaded configuration
    """
    # Start with base configuration
    if config_file and Path(config_file).exists():
        # If specific config file provided, set as env file
        os.environ["POSTSTACK_ENV_FILE"] = config_file

    config = PoststackConfig()

    # Apply CLI overrides if provided
    if cli_overrides:
        # Create new config with overrides
        config_data = config.model_dump()
        config_data.update(cli_overrides)
        config = PoststackConfig(**config_data)

    # Create necessary directories
    config.create_directories()

    return config


def get_default_config() -> PoststackConfig:
    """
    Get default configuration for development/testing.

    Returns:
        Default configuration instance
    """
    return PoststackConfig(
        log_level="DEBUG",
        verbose=True,
        debug=True,
        test_mode=True,
    )
