"""
Poststack: PostgreSQL container and schema migration management

A Python framework for managing PostgreSQL containers and database schema migrations.
"""

__version__ = "0.1.0"
__author__ = "Poststack Contributors"
__email__ = "noreply@poststack.org"

from .config import PoststackConfig
from .logging_config import setup_logging

__all__ = [
    "PoststackConfig",
    "setup_logging",
]
