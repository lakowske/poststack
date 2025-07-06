"""
Data models for Poststack operations

Defines result classes and error handling models for container operations,
build processes, and runtime management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class BuildStatus(Enum):
    """Status values for container build operations."""

    PENDING = "pending"
    BUILDING = "building"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeStatus(Enum):
    """Status values for container runtime operations."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class BuildResult:
    """Result of a container build operation."""

    image_name: str
    status: BuildStatus
    build_time: float = 0.0
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    dockerfile_path: Optional[Path] = None
    context_path: Optional[Path] = None
    build_args: Dict[str, str] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Get build duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    @property
    def success(self) -> bool:
        """Check if build was successful."""
        return self.status == BuildStatus.SUCCESS and self.exit_code == 0

    @property
    def failed(self) -> bool:
        """Check if build failed."""
        return self.status == BuildStatus.FAILED or (
            self.exit_code is not None and self.exit_code != 0
        )

    def mark_completed(self, exit_code: int) -> None:
        """Mark build as completed with exit code."""
        self.completed_at = datetime.now()
        self.exit_code = exit_code
        self.build_time = self.duration

        if exit_code == 0:
            self.status = BuildStatus.SUCCESS
        else:
            self.status = BuildStatus.FAILED

    def add_output(self, output: str, is_error: bool = False) -> None:
        """Add output from build process."""
        if is_error:
            self.stderr += output + "\n"
        else:
            self.stdout += output + "\n"

    def get_summary(self) -> str:
        """Get a summary string for the build result."""
        status_emoji = {
            BuildStatus.PENDING: "⏳",
            BuildStatus.BUILDING: "🔨",
            BuildStatus.SUCCESS: "✅",
            BuildStatus.FAILED: "❌",
            BuildStatus.CANCELLED: "🚫",
        }

        emoji = status_emoji.get(self.status, "❓")
        duration_str = f" ({self.build_time:.1f}s)" if self.build_time > 0 else ""

        return f"{emoji} {self.image_name}: {self.status.value}{duration_str}"


@dataclass
class RuntimeResult:
    """Result of a container runtime operation."""

    container_name: str
    image_name: str
    status: RuntimeStatus
    container_id: Optional[str] = None
    exit_code: Optional[int] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    ports: Dict[str, str] = field(default_factory=dict)
    volumes: Dict[str, str] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    health_check_passed: Optional[bool] = None
    logs: str = ""

    @property
    def running(self) -> bool:
        """Check if container is currently running."""
        return self.status == RuntimeStatus.RUNNING

    @property
    def uptime(self) -> Optional[float]:
        """Get container uptime in seconds."""
        if self.started_at:
            end_time = self.stopped_at or datetime.now()
            return (end_time - self.started_at).total_seconds()
        return None

    def mark_started(self, container_id: str) -> None:
        """Mark container as started."""
        self.container_id = container_id
        self.status = RuntimeStatus.RUNNING
        self.started_at = datetime.now()

    def mark_stopped(self, exit_code: Optional[int] = None) -> None:
        """Mark container as stopped."""
        self.status = RuntimeStatus.STOPPED
        self.stopped_at = datetime.now()
        if exit_code is not None:
            self.exit_code = exit_code

    def add_logs(self, logs: str) -> None:
        """Add container logs."""
        self.logs += logs + "\n"

    def get_summary(self) -> str:
        """Get a summary string for the runtime result."""
        status_emoji = {
            RuntimeStatus.STOPPED: "⏹️",
            RuntimeStatus.STARTING: "🚀",
            RuntimeStatus.RUNNING: "✅",
            RuntimeStatus.STOPPING: "🛑",
            RuntimeStatus.FAILED: "❌",
            RuntimeStatus.UNKNOWN: "❓",
        }

        emoji = status_emoji.get(self.status, "❓")
        uptime_str = ""
        if self.uptime:
            uptime_str = f" (uptime: {self.uptime:.1f}s)"

        container_id_str = ""
        if self.container_id:
            container_id_str = f" [{self.container_id[:12]}]"

        return f"{emoji} {self.container_name}: {self.status.value}{uptime_str}{container_id_str}"


@dataclass
class ContainerOperationError:
    """Error information for container operations."""

    operation: str
    error_type: str
    message: str
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        """String representation of the error."""
        return f"{self.operation} failed: {self.message}"

    def get_detailed_message(self) -> str:
        """Get detailed error message with context."""
        details = [f"Operation: {self.operation}"]
        details.append(f"Error: {self.message}")

        if self.exit_code is not None:
            details.append(f"Exit Code: {self.exit_code}")

        if self.stderr.strip():
            details.append(f"Error Output: {self.stderr.strip()}")

        if self.context:
            details.append("Context:")
            for key, value in self.context.items():
                details.append(f"  {key}: {value}")

        return "\n".join(details)


@dataclass
class HealthCheckResult:
    """Result of a container health check."""

    container_name: str
    check_type: str  # "http", "tcp", "exec", "file"
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


@dataclass
class ContainerCleanupResult:
    """Result of container cleanup operations."""

    containers_removed: List[str] = field(default_factory=list)
    images_removed: List[str] = field(default_factory=list)
    volumes_removed: List[str] = field(default_factory=list)
    networks_removed: List[str] = field(default_factory=list)
    errors: List[ContainerOperationError] = field(default_factory=list)
    cleanup_time: float = 0.0

    @property
    def success(self) -> bool:
        """Check if cleanup was successful."""
        return len(self.errors) == 0

    @property
    def total_removed(self) -> int:
        """Get total number of items removed."""
        return (
            len(self.containers_removed)
            + len(self.images_removed)
            + len(self.volumes_removed)
            + len(self.networks_removed)
        )

    def get_summary(self) -> str:
        """Get a summary string for the cleanup result."""
        if self.success:
            return f"✅ Cleanup successful: {self.total_removed} items removed in {self.cleanup_time:.1f}s"
        else:
            return f"⚠️ Cleanup completed with {len(self.errors)} errors: {self.total_removed} items removed"


# Type aliases for common collections
BuildResults = List[BuildResult]
RuntimeResults = List[RuntimeResult]
HealthCheckResults = List[HealthCheckResult]
