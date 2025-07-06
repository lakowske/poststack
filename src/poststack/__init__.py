"""
Poststack: Container-based service orchestration

A Python framework for managing containerized services including
PostgreSQL, Apache, Dovecot, BIND, and certificate management.
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
