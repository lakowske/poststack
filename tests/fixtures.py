"""
Test fixtures for Poststack container testing

Provides common fixtures, mock objects, and test utilities
for container management testing.
"""

import tempfile
from pathlib import Path
from typing import Dict, List
from unittest.mock import Mock

import pytest

from poststack.config import PoststackConfig
from poststack.logging_config import SubprocessLogHandler


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def test_config(temp_workspace):
    """Create a test configuration."""
    return PoststackConfig(
        database_url="postgresql://test:test@localhost:5432/testdb",
        container_runtime="podman",
        log_level="DEBUG",
        verbose=True,
        log_dir=str(temp_workspace / "logs"),
    )


@pytest.fixture
def test_log_handler(test_config):
    """Create a test log handler."""
    return SubprocessLogHandler("test", test_config.log_dir)


@pytest.fixture
def mock_dockerfile(temp_workspace):
    """Create a mock Dockerfile for testing."""
    dockerfile = temp_workspace / "Dockerfile"
    dockerfile.write_text("""
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y python3
COPY . /app
WORKDIR /app
CMD ["python3", "-c", "print('Hello from test container')"]
""")
    return dockerfile


@pytest.fixture
def mock_build_context(temp_workspace):
    """Create a mock build context directory."""
    context_dir = temp_workspace / "build_context"
    context_dir.mkdir()

    # Create dockerfile in context
    dockerfile_content = """
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y python3
COPY . /app
WORKDIR /app
CMD ["python3", "-c", "print('Hello from test container')"]
"""
    (context_dir / "Dockerfile").write_text(dockerfile_content)

    # Create some mock source files
    (context_dir / "app.py").write_text("print('Mock application')")
    (context_dir / "config.json").write_text('{"test": true}')

    return context_dir


@pytest.fixture
def mock_container_specs():
    """Mock container specifications for testing."""
    return {
        "test-app": {
            "description": "Test application container",
            "image": "poststack/test-app",
            "dockerfile": "containers/test-app/Dockerfile",
            "ports": ["8080:80"],
            "volumes": ["test_data:/data"],
            "environment": {"ENV": "test", "DEBUG": "true"},
        },
        "test-db": {
            "description": "Test database container",
            "image": "poststack/test-db",
            "dockerfile": "containers/test-db/Dockerfile",
            "ports": ["5433:5432"],
            "volumes": ["test_db_data:/var/lib/postgresql/data"],
            "environment": {"POSTGRES_DB": "testdb", "POSTGRES_USER": "test"},
        },
    }


class MockSubprocess:
    """Mock subprocess for testing container operations."""

    def __init__(self):
        self.commands_run = []
        self.return_codes = {}
        self.outputs = {}
        self.timeouts = {}

    def set_return_code(self, command_prefix: str, return_code: int):
        """Set return code for commands starting with prefix."""
        self.return_codes[command_prefix] = return_code

    def set_output(self, command_prefix: str, stdout: str = "", stderr: str = ""):
        """Set output for commands starting with prefix."""
        self.outputs[command_prefix] = {"stdout": stdout, "stderr": stderr}

    def set_timeout(self, command_prefix: str, should_timeout: bool = True):
        """Set whether commands should timeout."""
        self.timeouts[command_prefix] = should_timeout

    def run(self, cmd, **kwargs):
        """Mock subprocess.run implementation."""
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        self.commands_run.append(cmd_str)

        # Find matching configuration
        return_code = 0
        stdout = ""
        stderr = ""
        should_timeout = False

        for prefix, code in self.return_codes.items():
            if cmd_str.startswith(prefix):
                return_code = code
                break

        for prefix, output in self.outputs.items():
            if cmd_str.startswith(prefix):
                stdout = output["stdout"]
                stderr = output["stderr"]
                break

        for prefix, timeout in self.timeouts.items():
            if cmd_str.startswith(prefix):
                should_timeout = timeout
                break

        # Simulate timeout
        if should_timeout:
            from subprocess import TimeoutExpired

            raise TimeoutExpired(cmd, kwargs.get("timeout", 30))

        # Create mock result
        result = Mock()
        result.returncode = return_code
        result.stdout = stdout
        result.stderr = stderr

        return result


@pytest.fixture
def mock_subprocess():
    """Create a mock subprocess for testing."""
    return MockSubprocess()


@pytest.fixture
def successful_build_mock(mock_subprocess):
    """Configure mock subprocess for successful builds."""
    mock_subprocess.set_return_code("podman build", 0)
    mock_subprocess.set_output(
        "podman build", stdout="Successfully built poststack/test-app\n", stderr=""
    )
    return mock_subprocess


@pytest.fixture
def failed_build_mock(mock_subprocess):
    """Configure mock subprocess for failed builds."""
    mock_subprocess.set_return_code("podman build", 1)
    mock_subprocess.set_output(
        "podman build", stdout="", stderr="Error: Could not find Dockerfile\n"
    )
    return mock_subprocess


@pytest.fixture
def successful_runtime_mock(mock_subprocess):
    """Configure mock subprocess for successful container runtime."""
    # Container start
    mock_subprocess.set_return_code("podman run", 0)
    mock_subprocess.set_output(
        "podman run",
        stdout="abc123def456\n",  # Mock container ID
        stderr="",
    )

    # Container status
    mock_subprocess.set_return_code("podman inspect", 0)
    mock_subprocess.set_output(
        "podman inspect", stdout="running,poststack/test-app,abc123def456\n", stderr=""
    )

    # Container stop
    mock_subprocess.set_return_code("podman stop", 0)
    mock_subprocess.set_output("podman stop", stdout="", stderr="")

    return mock_subprocess


@pytest.fixture
def container_cleanup_mock(mock_subprocess):
    """Configure mock subprocess for container cleanup operations."""
    # List containers
    mock_subprocess.set_return_code("podman ps", 0)
    mock_subprocess.set_output(
        "podman ps", stdout="poststack-test-app\npoststack-test-db\n", stderr=""
    )

    # Stop containers
    mock_subprocess.set_return_code("podman stop", 0)

    # Remove containers
    mock_subprocess.set_return_code("podman rm", 0)

    # Remove images
    mock_subprocess.set_return_code("podman rmi", 0)

    return mock_subprocess


class MockHealthCheck:
    """Mock health check utilities."""

    @staticmethod
    def http_check(url: str, timeout: int = 5) -> bool:
        """Mock HTTP health check."""
        # Simulate different responses based on URL
        if "healthy" in url:
            return True
        elif "unhealthy" in url:
            return False
        else:
            return True  # Default to healthy

    @staticmethod
    def tcp_check(host: str, port: int, timeout: int = 5) -> bool:
        """Mock TCP health check."""
        # Simulate different responses based on port
        if port in [80, 443, 8080, 5432]:
            return True
        else:
            return False

    @staticmethod
    def file_check(file_path: Path) -> bool:
        """Mock file existence check."""
        return file_path.name != "missing.txt"


@pytest.fixture
def mock_health_check():
    """Create mock health check utilities."""
    return MockHealthCheck()


# Test data generators
def generate_build_specs(count: int = 3) -> List[Dict]:
    """Generate mock build specifications for testing."""
    specs = []
    for i in range(count):
        specs.append(
            {
                "image_name": f"poststack/test-{i}",
                "dockerfile_path": Path(f"test/Dockerfile.{i}"),
                "context_path": Path(f"test/context_{i}"),
                "build_args": {"BUILD_ID": str(i), "ENV": "test"},
                "tags": [f"poststack/test-{i}:latest", f"poststack/test-{i}:v1.0"],
                "no_cache": False,
                "timeout": 300,
            }
        )
    return specs


def generate_runtime_specs(count: int = 3) -> List[Dict]:
    """Generate mock runtime specifications for testing."""
    specs = []
    for i in range(count):
        specs.append(
            {
                "container_name": f"poststack-test-{i}",
                "image_name": f"poststack/test-{i}",
                "ports": {f"808{i}": "80"},
                "volumes": {f"/tmp/test_{i}": "/data"},
                "environment": {"SERVICE_ID": str(i), "ENV": "test"},
                "detached": True,
                "remove_on_exit": False,
                "timeout": 60,
            }
        )
    return specs
