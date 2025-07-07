"""
Logging configuration for Poststack

Provides structured logging with both console output and file logging.
Subprocess logs are directed to dedicated files in logs/ directory.
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: str = "logs",
    verbose: bool = False,
    log_level: Optional[str] = None,
    enable_file_logging: bool = True,
) -> logging.Logger:
    """
    Set up comprehensive logging for Poststack operations.

    Args:
        log_dir: Directory for log files
        verbose: Enable verbose console output
        log_level: Override log level (DEBUG, INFO, WARNING, ERROR)
        enable_file_logging: Whether to write logs to files

    Returns:
        Configured logger instance
    """
    # Create logs directory structure
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    (log_path / "containers").mkdir(exist_ok=True)
    (log_path / "database").mkdir(exist_ok=True)

    # Determine log level
    if log_level:
        level = getattr(logging, log_level.upper(), logging.INFO)
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # Create formatter for structured logging
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (if enabled)
    if enable_file_logging:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_path / f"poststack_{timestamp}.log"

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,  # 10MB files, 5 backups
        )
        file_handler.setLevel(logging.DEBUG)  # Always debug level for files
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Get poststack logger
    logger = logging.getLogger("poststack")
    logger.debug(f"Logging initialized - Level: {logging.getLevelName(level)}")
    if enable_file_logging:
        logger.debug(f"Log directory: {log_path.absolute()}")

    return logger


def get_subprocess_log_file(operation: str, log_dir: str = "logs") -> str:
    """
    Generate timestamped log file path for subprocess operations.

    Args:
        operation: Operation name (e.g., 'container_build', 'migration_update')
        log_dir: Base log directory

    Returns:
        Full path to log file for subprocess output
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(log_dir)

    # Determine subdirectory based on operation
    if "container" in operation.lower() or "build" in operation.lower():
        subdir = "containers"
    elif "database" in operation.lower() or "migration" in operation.lower():
        subdir = "database"
    else:
        subdir = ""

    if subdir:
        log_file = log_path / subdir / f"{operation}_{timestamp}.log"
    else:
        log_file = log_path / f"{operation}_{timestamp}.log"

    # Ensure parent directory exists
    log_file.parent.mkdir(parents=True, exist_ok=True)

    return str(log_file)


def mask_sensitive_data(message: str) -> str:
    """
    Mask sensitive information in log messages.

    Args:
        message: Log message that may contain sensitive data

    Returns:
        Message with sensitive information masked
    """
    import re

    # Mask database URLs
    message = re.sub(
        r"postgresql://([^:]+):([^@]+)@([^/]+)/([^\s]+)",
        r"postgresql://\1:***@\3/\4",
        message,
    )

    # Mask password parameters
    message = re.sub(
        r"password[=\s]+[^\s]+", "password=***", message, flags=re.IGNORECASE
    )

    # Mask environment variables
    message = re.sub(r"POSTGRES_PASSWORD[=\s]+[^\s]+", "POSTGRES_PASSWORD=***", message)

    return message


class SubprocessLogHandler:
    """
    Handler for subprocess operations with dedicated logging.
    """

    def __init__(self, operation: str, log_dir: str = "logs"):
        """
        Initialize subprocess log handler.

        Args:
            operation: Name of the operation being logged
            log_dir: Base directory for log files
        """
        self.operation = operation
        self.log_file = get_subprocess_log_file(operation, log_dir)
        self.logger = logging.getLogger(f"poststack.subprocess.{operation}")

        # Create file handler for this specific operation
        handler = logging.FileHandler(self.log_file)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)

    def log_command(self, command: list[str]) -> None:
        """Log the command being executed."""
        masked_command = [mask_sensitive_data(arg) for arg in command]
        self.logger.info(f"Executing command: {' '.join(masked_command)}")

    def log_output(self, output: str, level: int = logging.INFO) -> None:
        """Log subprocess output."""
        if output.strip():
            masked_output = mask_sensitive_data(output.strip())
            self.logger.log(level, masked_output)

    def log_completion(self, return_code: int, elapsed_time: float) -> None:
        """Log subprocess completion."""
        if return_code == 0:
            self.logger.info(
                f"✓ {self.operation} completed successfully in {elapsed_time:.2f}s"
            )
        else:
            self.logger.error(
                f"✗ {self.operation} failed with return code {return_code} after {elapsed_time:.2f}s"
            )

    def get_log_file_path(self) -> str:
        """Get the path to the log file for this operation."""
        return self.log_file


def configure_third_party_loggers() -> None:
    """Configure third-party library loggers to reduce noise."""
    # Reduce verbosity of common third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("docker").setLevel(logging.WARNING)
    logging.getLogger("psycopg2").setLevel(logging.WARNING)


# Configure third-party loggers when module is imported
configure_third_party_loggers()
