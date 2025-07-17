"""
Data models for Poststack database operations

Defines result classes for database operations, health checks, and runtime management.
Focused on database-centric operations with Docker Compose handling orchestration.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


class RuntimeStatus(Enum):
    """Status values for database runtime operations."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class RuntimeResult:
    """Result of a database runtime operation."""

    success: bool
    message: str = ""
    runtime_seconds: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, str] = field(default_factory=dict)
    
    # Legacy compatibility fields for existing code
    container_name: str = ""
    image_name: str = ""
    status: Optional[RuntimeStatus] = None
    logs: str = ""

    def add_logs(self, logs: str) -> None:
        """Add logs to the result."""
        self.logs += logs + "\n"

    def get_summary(self) -> str:
        """Get a summary string for the runtime result."""
        status = "✅ SUCCESS" if self.success else "❌ FAILED"
        timing = f" ({self.runtime_seconds:.1f}s)" if self.runtime_seconds > 0 else ""
        return f"{status}: {self.message}{timing}"


@dataclass
class HealthCheckResult:
    """Result of a database health check."""

    container_name: str
    check_type: str  # "connection_test", "schema_check", "migration_check"
    passed: bool
    message: str = ""
    response_time: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, str] = field(default_factory=dict)

    def get_summary(self) -> str:
        """Get a summary string for the health check."""
        status = "✅ PASS" if self.passed else "❌ FAIL"
        timing = f" ({self.response_time:.2f}s)" if self.response_time else ""
        return (
            f"{status} {self.check_type} health check for {self.container_name}{timing}"
        )