# Container Testing Documentation

## Overview

This document describes the comprehensive testing strategy for Poststack container builds and runtime verification. The testing suite ensures that both the CLI tool and the underlying container management functions work reliably.

## Architecture

### Shared Codepath Design

The testing framework and CLI tool share the same underlying container management code to ensure high confidence in production deployments:

```
poststack/
├── containers.py          # Shared container management functions
├── testing/
│   ├── test_builds.py     # Container build tests
│   ├── test_runtime.py    # Container runtime tests
│   └── fixtures.py        # Test fixtures and utilities
└── bootstrap.py           # CLI tool using containers.py
```

### Core Principle

**Both the CLI tool and tests use identical codepaths for:**
- Container image building
- Container runtime management
- Configuration handling
- Error handling and cleanup
- Logging and monitoring

## Container Build Testing

### Build Test Suite

Each container image has dedicated pytest tests that verify:

1. **Build Success**: Image builds without errors
2. **Build Performance**: Build time measurement and reporting
3. **Image Verification**: Correct tagging and metadata
4. **Build Reproducibility**: Consistent builds across runs

### Test Implementation

```python
# tests/test_container_builds.py
import pytest
import time
from datetime import datetime
from poststack.containers import ContainerBuilder

class TestContainerBuilds:
    """Test suite for container image builds"""
    
    @pytest.fixture
    def builder(self):
        """Container builder fixture with logging configuration"""
        return ContainerBuilder(
            log_dir="tests/logs",
            verbose=True
        )
    
    @pytest.mark.parametrize("image_name,dockerfile_path", [
        ("postgres", "containers/postgres/Dockerfile"),
        ("apache", "containers/apache/Dockerfile"),
        ("dovecot", "containers/dovecot/Dockerfile"),
        ("bind", "containers/bind/Dockerfile"),
    ])
    def test_container_build(self, builder, image_name, dockerfile_path):
        """Test individual container build with timing"""
        
        # Record start time
        start_time = time.time()
        
        # Build container using shared codepath
        result = builder.build_image(
            image_name=image_name,
            dockerfile_path=dockerfile_path,
            tag=f"poststack-{image_name}:test"
        )
        
        # Record build time
        build_time = time.time() - start_time
        
        # Verify build success
        assert result.success, f"Build failed for {image_name}: {result.error}"
        assert result.image_id is not None, f"No image ID returned for {image_name}"
        
        # Log build metrics
        print(f"✓ {image_name} build completed in {build_time:.2f}s")
        
        # Verify image exists and is properly tagged
        assert builder.image_exists(f"poststack-{image_name}:test")
        
        # Store build metrics for reporting
        builder.record_build_metrics(image_name, build_time, result.image_size)
    
    def test_parallel_build_performance(self, builder):
        """Test parallel vs sequential build performance"""
        
        images = [
            ("postgres", "containers/postgres/Dockerfile"),
            ("apache", "containers/apache/Dockerfile"),
            ("dovecot", "containers/dovecot/Dockerfile"),
        ]
        
        # Sequential build timing
        sequential_start = time.time()
        sequential_results = []
        for image_name, dockerfile_path in images:
            result = builder.build_image(image_name, dockerfile_path)
            sequential_results.append(result)
        sequential_time = time.time() - sequential_start
        
        # Parallel build timing
        parallel_start = time.time()
        parallel_results = builder.build_images_parallel(images)
        parallel_time = time.time() - parallel_start
        
        # Verify all builds succeeded
        assert all(r.success for r in sequential_results)
        assert all(r.success for r in parallel_results)
        
        # Log performance comparison
        print(f"Sequential build: {sequential_time:.2f}s")
        print(f"Parallel build: {parallel_time:.2f}s")
        print(f"Parallel speedup: {sequential_time/parallel_time:.1f}x")
        
        # Parallel should be faster (with some tolerance for overhead)
        assert parallel_time < sequential_time * 0.8
    
    def test_build_with_custom_args(self, builder):
        """Test builds with custom arguments and build contexts"""
        
        # Test build with custom build args
        result = builder.build_image(
            image_name="postgres",
            dockerfile_path="containers/postgres/Dockerfile",
            build_args={
                "POSTGRES_VERSION": "14",
                "CUSTOM_CONFIG": "true"
            }
        )
        
        assert result.success
        
        # Verify build args were applied
        image_info = builder.inspect_image(result.image_id)
        assert "POSTGRES_VERSION=14" in str(image_info.config)
    
    def test_build_failure_handling(self, builder):
        """Test proper handling of build failures"""
        
        # Test with invalid Dockerfile
        result = builder.build_image(
            image_name="invalid",
            dockerfile_path="nonexistent/Dockerfile"
        )
        
        assert not result.success
        assert result.error is not None
        assert "Dockerfile not found" in result.error
        
        # Verify no partial image was created
        assert not builder.image_exists("poststack-invalid:test")
    
    def test_build_cleanup(self, builder):
        """Test proper cleanup of build artifacts"""
        
        # Build an image
        result = builder.build_image(
            image_name="postgres",
            dockerfile_path="containers/postgres/Dockerfile",
            tag="poststack-postgres:cleanup-test"
        )
        
        assert result.success
        
        # Verify cleanup removes image
        builder.cleanup_image("poststack-postgres:cleanup-test")
        assert not builder.image_exists("poststack-postgres:cleanup-test")
```

### Build Metrics and Reporting

```python
# poststack/containers.py (excerpt)
class ContainerBuilder:
    """Shared container building functionality"""
    
    def __init__(self, log_dir="logs", verbose=False):
        self.log_dir = log_dir
        self.verbose = verbose
        self.build_metrics = []
        self.logger = self._setup_logging()
    
    def build_image(self, image_name, dockerfile_path, tag=None, build_args=None):
        """Build container image with comprehensive logging"""
        
        # Create timestamped log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"{self.log_dir}/containers/{image_name}_build_{timestamp}.log"
        
        # Prepare build command
        cmd = self._prepare_build_command(image_name, dockerfile_path, tag, build_args)
        
        # Execute build with logging
        start_time = time.time()
        result = self._run_with_logging(cmd, log_file, f"Building {image_name}")
        build_time = time.time() - start_time
        
        # Parse build result
        if result.returncode == 0:
            image_id = self._extract_image_id(result.stdout)
            image_size = self._get_image_size(image_id)
            
            self.logger.info(f"✓ {image_name} build completed in {build_time:.2f}s")
            return BuildResult(
                success=True,
                image_id=image_id,
                build_time=build_time,
                image_size=image_size
            )
        else:
            self.logger.error(f"✗ {image_name} build failed: {result.stderr}")
            return BuildResult(
                success=False,
                error=result.stderr,
                build_time=build_time
            )
    
    def record_build_metrics(self, image_name, build_time, image_size):
        """Record build metrics for reporting"""
        
        metrics = {
            'image_name': image_name,
            'build_time': build_time,
            'image_size': image_size,
            'timestamp': datetime.now().isoformat(),
            'success': True
        }
        
        self.build_metrics.append(metrics)
        
        # Write metrics to file
        metrics_file = f"{self.log_dir}/build_metrics.json"
        with open(metrics_file, 'a') as f:
            json.dump(metrics, f)
            f.write('\n')
    
    def generate_build_report(self):
        """Generate comprehensive build report"""
        
        if not self.build_metrics:
            return "No build metrics available"
        
        report = []
        report.append("# Container Build Report")
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("")
        
        # Summary table
        report.append("## Build Summary")
        report.append("| Image | Build Time | Size | Status |")
        report.append("|-------|------------|------|--------|")
        
        for metrics in self.build_metrics:
            report.append(f"| {metrics['image_name']} | {metrics['build_time']:.2f}s | {self._format_size(metrics['image_size'])} | ✓ |")
        
        # Performance analysis
        total_time = sum(m['build_time'] for m in self.build_metrics)
        avg_time = total_time / len(self.build_metrics)
        
        report.append("")
        report.append("## Performance Analysis")
        report.append(f"- Total build time: {total_time:.2f}s")
        report.append(f"- Average build time: {avg_time:.2f}s")
        report.append(f"- Largest image: {max(self.build_metrics, key=lambda x: x['image_size'])['image_name']}")
        report.append(f"- Fastest build: {min(self.build_metrics, key=lambda x: x['build_time'])['image_name']}")
        
        return '\n'.join(report)
```

## Container Runtime Testing

### Runtime Test Suite

Runtime tests verify that containers start correctly, perform their expected functions, and shut down cleanly:

```python
# tests/test_container_runtime.py
import pytest
import time
import requests
import psycopg2
from poststack.containers import ContainerRunner

class TestContainerRuntime:
    """Test suite for container runtime verification"""
    
    @pytest.fixture
    def runner(self):
        """Container runner fixture"""
        return ContainerRunner(
            log_dir="tests/logs",
            cleanup_on_exit=True
        )
    
    @pytest.mark.parametrize("container_config", [
        {
            "name": "postgres",
            "image": "poststack-postgres:test",
            "ports": {"5432/tcp": 5432},
            "environment": {
                "POSTGRES_DB": "test_db",
                "POSTGRES_USER": "test_user", 
                "POSTGRES_PASSWORD": "test_pass"
            },
            "health_check": "postgres_health_check",
            "startup_time": 30
        },
        {
            "name": "apache",
            "image": "poststack-apache:test",
            "ports": {"80/tcp": 8080, "443/tcp": 8443},
            "volumes": {
                "/tmp/apache-test": "/var/www/html"
            },
            "health_check": "apache_health_check",
            "startup_time": 10
        },
        {
            "name": "dovecot", 
            "image": "poststack-dovecot:test",
            "ports": {"993/tcp": 993, "587/tcp": 587},
            "health_check": "dovecot_health_check",
            "startup_time": 15
        },
        {
            "name": "bind",
            "image": "poststack-bind:test", 
            "ports": {"53/tcp": 5353, "53/udp": 5353},
            "health_check": "bind_health_check",
            "startup_time": 10
        }
    ])
    def test_container_runtime(self, runner, container_config):
        """Test container startup, health check, and shutdown"""
        
        container_name = container_config["name"]
        
        # Start container
        start_time = time.time()
        container = runner.start_container(container_config)
        
        assert container.status == "running"
        print(f"✓ {container_name} started successfully")
        
        # Wait for startup with timeout
        startup_timeout = container_config.get("startup_time", 30)
        if not runner.wait_for_startup(container, timeout=startup_timeout):
            pytest.fail(f"{container_name} failed to start within {startup_timeout}s")
        
        startup_time = time.time() - start_time
        print(f"✓ {container_name} ready in {startup_time:.2f}s")
        
        # Run health check
        health_check_func = getattr(self, container_config["health_check"])
        health_result = health_check_func(container, container_config)
        
        assert health_result.healthy, f"{container_name} health check failed: {health_result.message}"
        print(f"✓ {container_name} health check passed")
        
        # Test expected side effects
        side_effects_result = self.verify_side_effects(container, container_config)
        assert side_effects_result.success, f"{container_name} side effects verification failed"
        print(f"✓ {container_name} side effects verified")
        
        # Test graceful shutdown
        shutdown_start = time.time()
        runner.stop_container(container, timeout=10)
        shutdown_time = time.time() - shutdown_start
        
        assert container.status == "stopped"
        print(f"✓ {container_name} stopped gracefully in {shutdown_time:.2f}s")
        
        # Verify cleanup
        runner.cleanup_container(container)
        assert not runner.container_exists(container.name)
        print(f"✓ {container_name} cleanup completed")
    
    def postgres_health_check(self, container, config):
        """Health check for PostgreSQL container"""
        
        try:
            # Wait for PostgreSQL to be ready
            time.sleep(5)
            
            # Test connection
            conn = psycopg2.connect(
                host="localhost",
                port=config["ports"]["5432/tcp"],
                database=config["environment"]["POSTGRES_DB"],
                user=config["environment"]["POSTGRES_USER"],
                password=config["environment"]["POSTGRES_PASSWORD"]
            )
            
            # Test basic query
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            
            conn.close()
            
            return HealthResult(
                healthy=True,
                message=f"PostgreSQL responding, version: {version[:50]}..."
            )
            
        except Exception as e:
            return HealthResult(
                healthy=False,
                message=f"PostgreSQL health check failed: {str(e)}"
            )
    
    def apache_health_check(self, container, config):
        """Health check for Apache container"""
        
        try:
            # Test HTTP response
            response = requests.get(
                f"http://localhost:{config['ports']['80/tcp']}/",
                timeout=5
            )
            
            if response.status_code == 200:
                return HealthResult(
                    healthy=True,
                    message="Apache responding with HTTP 200"
                )
            else:
                return HealthResult(
                    healthy=False,
                    message=f"Apache returned HTTP {response.status_code}"
                )
                
        except Exception as e:
            return HealthResult(
                healthy=False,
                message=f"Apache health check failed: {str(e)}"
            )
    
    def dovecot_health_check(self, container, config):
        """Health check for Dovecot container"""
        
        try:
            import socket
            
            # Test IMAP port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(("localhost", config["ports"]["993/tcp"]))
            sock.close()
            
            if result == 0:
                return HealthResult(
                    healthy=True,
                    message="Dovecot IMAP port responding"
                )
            else:
                return HealthResult(
                    healthy=False,
                    message="Dovecot IMAP port not responding"
                )
                
        except Exception as e:
            return HealthResult(
                healthy=False,
                message=f"Dovecot health check failed: {str(e)}"
            )
    
    def bind_health_check(self, container, config):
        """Health check for BIND DNS container"""
        
        try:
            import dns.resolver
            
            # Configure resolver to use our DNS server
            resolver = dns.resolver.Resolver()
            resolver.nameservers = ["localhost"]
            resolver.port = config["ports"]["53/tcp"]
            
            # Test DNS query
            result = resolver.resolve("localhost", "A")
            
            if result:
                return HealthResult(
                    healthy=True,
                    message="BIND DNS responding to queries"
                )
            else:
                return HealthResult(
                    healthy=False,
                    message="BIND DNS not responding"
                )
                
        except Exception as e:
            return HealthResult(
                healthy=False,
                message=f"BIND health check failed: {str(e)}"
            )
    
    def verify_side_effects(self, container, config):
        """Verify expected side effects of container operation"""
        
        container_name = config["name"]
        
        try:
            if container_name == "postgres":
                # Verify database files created
                result = container.exec_run("ls -la /var/lib/postgresql/data/")
                assert "postgresql.conf" in result.output.decode()
                
            elif container_name == "apache":
                # Verify web root is accessible
                result = container.exec_run("ls -la /var/www/html/")
                assert result.exit_code == 0
                
            elif container_name == "dovecot":
                # Verify mail directories created
                result = container.exec_run("ls -la /var/mail/")
                assert result.exit_code == 0
                
            elif container_name == "bind":
                # Verify zone files loaded
                result = container.exec_run("rndc status")
                assert "server is up and running" in result.output.decode()
            
            return SideEffectsResult(
                success=True,
                message=f"{container_name} side effects verified"
            )
            
        except Exception as e:
            return SideEffectsResult(
                success=False,
                message=f"{container_name} side effects verification failed: {str(e)}"
            )
    
    def test_container_resource_usage(self, runner):
        """Test container resource usage monitoring"""
        
        # Start a container
        config = {
            "name": "postgres",
            "image": "poststack-postgres:test",
            "ports": {"5432/tcp": 5432},
            "environment": {
                "POSTGRES_DB": "test_db",
                "POSTGRES_USER": "test_user",
                "POSTGRES_PASSWORD": "test_pass"
            }
        }
        
        container = runner.start_container(config)
        
        # Monitor resource usage
        stats = runner.get_container_stats(container)
        
        # Verify reasonable resource usage
        assert stats.memory_usage < 512 * 1024 * 1024  # < 512MB
        assert stats.cpu_usage < 50.0  # < 50% CPU
        
        print(f"PostgreSQL container stats:")
        print(f"  Memory: {stats.memory_usage / 1024 / 1024:.1f} MB")
        print(f"  CPU: {stats.cpu_usage:.1f}%")
        
        # Cleanup
        runner.stop_container(container)
        runner.cleanup_container(container)
    
    def test_container_log_output(self, runner):
        """Test container log output capture"""
        
        config = {
            "name": "apache",
            "image": "poststack-apache:test",
            "ports": {"80/tcp": 8080}
        }
        
        container = runner.start_container(config)
        
        # Generate some log activity
        requests.get(f"http://localhost:8080/", timeout=5)
        
        # Capture logs
        logs = runner.get_container_logs(container)
        
        # Verify logs contain expected content
        assert "GET /" in logs
        assert "200" in logs  # HTTP status code
        
        print(f"Apache logs captured: {len(logs)} characters")
        
        # Cleanup
        runner.stop_container(container)
        runner.cleanup_container(container)
```

## Test Configuration and Fixtures

### pytest Configuration

```python
# tests/conftest.py
import pytest
import os
import tempfile
import shutil
from pathlib import Path

@pytest.fixture(scope="session")
def test_logs_dir():
    """Create temporary directory for test logs"""
    
    temp_dir = tempfile.mkdtemp(prefix="poststack_test_")
    logs_dir = Path(temp_dir) / "logs"
    logs_dir.mkdir(parents=True)
    
    # Create subdirectories
    (logs_dir / "containers").mkdir()
    (logs_dir / "database").mkdir()
    
    yield str(logs_dir)
    
    # Cleanup
    shutil.rmtree(temp_dir)

@pytest.fixture(scope="session")
def container_images():
    """Ensure test images are built before running tests"""
    
    from poststack.containers import ContainerBuilder
    
    builder = ContainerBuilder(log_dir="tests/logs")
    
    images = [
        ("postgres", "containers/postgres/Dockerfile"),
        ("apache", "containers/apache/Dockerfile"),
        ("dovecot", "containers/dovecot/Dockerfile"),
        ("bind", "containers/bind/Dockerfile"),
    ]
    
    built_images = []
    
    for image_name, dockerfile_path in images:
        if not builder.image_exists(f"poststack-{image_name}:test"):
            result = builder.build_image(
                image_name=image_name,
                dockerfile_path=dockerfile_path,
                tag=f"poststack-{image_name}:test"
            )
            assert result.success, f"Failed to build test image {image_name}"
        
        built_images.append(f"poststack-{image_name}:test")
    
    yield built_images
    
    # Cleanup test images
    for image_tag in built_images:
        builder.cleanup_image(image_tag)

@pytest.fixture
def isolated_test_env():
    """Create isolated test environment"""
    
    # Create temporary directory for test files
    temp_dir = tempfile.mkdtemp(prefix="poststack_isolated_")
    
    # Set environment variables
    old_env = os.environ.copy()
    os.environ["POSTSTACK_TEST_MODE"] = "true"
    os.environ["POSTSTACK_LOG_DIR"] = temp_dir
    
    yield temp_dir
    
    # Restore environment
    os.environ.clear()
    os.environ.update(old_env)
    
    # Cleanup
    shutil.rmtree(temp_dir)
```

### Test Data and Fixtures

```python
# tests/fixtures.py
import pytest
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class BuildResult:
    """Container build result"""
    success: bool
    image_id: Optional[str] = None
    build_time: float = 0.0
    image_size: int = 0
    error: Optional[str] = None

@dataclass
class HealthResult:
    """Container health check result"""
    healthy: bool
    message: str
    response_time: float = 0.0

@dataclass
class SideEffectsResult:
    """Container side effects verification result"""
    success: bool
    message: str
    details: Dict = None

@dataclass
class ContainerStats:
    """Container resource usage statistics"""
    memory_usage: int  # bytes
    cpu_usage: float   # percentage
    network_io: Dict   # bytes in/out
    disk_io: Dict      # bytes read/write

# Test data for different container configurations
CONTAINER_TEST_CONFIGS = {
    "postgres": {
        "name": "postgres",
        "image": "poststack-postgres:test",
        "ports": {"5432/tcp": 5432},
        "environment": {
            "POSTGRES_DB": "test_db",
            "POSTGRES_USER": "test_user",
            "POSTGRES_PASSWORD": "test_pass"
        },
        "health_check": "postgres_health_check",
        "startup_time": 30,
        "expected_memory": 128 * 1024 * 1024,  # 128MB
        "expected_cpu": 10.0  # 10%
    },
    "apache": {
        "name": "apache",
        "image": "poststack-apache:test",
        "ports": {"80/tcp": 8080, "443/tcp": 8443},
        "volumes": {
            "/tmp/apache-test": "/var/www/html"
        },
        "health_check": "apache_health_check",
        "startup_time": 10,
        "expected_memory": 64 * 1024 * 1024,  # 64MB
        "expected_cpu": 5.0  # 5%
    },
    "dovecot": {
        "name": "dovecot",
        "image": "poststack-dovecot:test",
        "ports": {"993/tcp": 993, "587/tcp": 587},
        "health_check": "dovecot_health_check",
        "startup_time": 15,
        "expected_memory": 32 * 1024 * 1024,  # 32MB
        "expected_cpu": 3.0  # 3%
    },
    "bind": {
        "name": "bind",
        "image": "poststack-bind:test",
        "ports": {"53/tcp": 5353, "53/udp": 5353},
        "health_check": "bind_health_check",
        "startup_time": 10,
        "expected_memory": 16 * 1024 * 1024,  # 16MB
        "expected_cpu": 2.0  # 2%
    }
}

@pytest.fixture(params=CONTAINER_TEST_CONFIGS.values())
def container_config(request):
    """Parameterized fixture for container configurations"""
    return request.param

@pytest.fixture
def performance_expectations():
    """Performance expectations for different operations"""
    return {
        "build_time_limits": {
            "postgres": 120.0,  # 2 minutes
            "apache": 60.0,     # 1 minute
            "dovecot": 90.0,    # 1.5 minutes
            "bind": 45.0,       # 45 seconds
        },
        "startup_time_limits": {
            "postgres": 30.0,   # 30 seconds
            "apache": 10.0,     # 10 seconds
            "dovecot": 15.0,    # 15 seconds
            "bind": 10.0        # 10 seconds
        },
        "health_check_timeouts": {
            "postgres": 5.0,    # 5 seconds
            "apache": 3.0,      # 3 seconds
            "dovecot": 5.0,     # 5 seconds
            "bind": 3.0         # 3 seconds
        }
    }
```

## Integration with CLI Tool

### Shared Container Management

The CLI tool uses the same container management functions as the tests:

```python
# poststack/bootstrap.py (CLI tool)
from poststack.containers import ContainerBuilder, ContainerRunner

def build_images_command(args):
    """CLI command for building images - uses same code as tests"""
    
    builder = ContainerBuilder(
        log_dir=args.log_dir,
        verbose=args.verbose
    )
    
    # Use same build function as tests
    images = [
        ("postgres", "containers/postgres/Dockerfile"),
        ("apache", "containers/apache/Dockerfile"),
        ("dovecot", "containers/dovecot/Dockerfile"),
        ("bind", "containers/bind/Dockerfile"),
    ]
    
    if args.parallel:
        results = builder.build_images_parallel(images)
    else:
        results = []
        for image_name, dockerfile_path in images:
            result = builder.build_image(image_name, dockerfile_path)
            results.append(result)
    
    # Generate same report as tests
    report = builder.generate_build_report()
    print(report)
    
    return all(r.success for r in results)

def verify_containers_command(args):
    """CLI command for verifying containers - uses same code as tests"""
    
    runner = ContainerRunner(
        log_dir=args.log_dir,
        cleanup_on_exit=True
    )
    
    # Use same test configurations
    from tests.fixtures import CONTAINER_TEST_CONFIGS
    
    success_count = 0
    
    for config_name, config in CONTAINER_TEST_CONFIGS.items():
        print(f"▶ Verifying {config_name} container...")
        
        # Use same runtime verification as tests
        container = runner.start_container(config)
        
        if runner.wait_for_startup(container, timeout=config["startup_time"]):
            # Use same health check functions as tests
            health_result = getattr(runner, config["health_check"])(container, config)
            
            if health_result.healthy:
                print(f" ✓ {config_name} verification passed")
                success_count += 1
            else:
                print(f" ✗ {config_name} health check failed: {health_result.message}")
        else:
            print(f" ✗ {config_name} failed to start")
        
        # Cleanup
        runner.stop_container(container)
        runner.cleanup_container(container)
    
    print(f"\nContainer verification: {success_count}/{len(CONTAINER_TEST_CONFIGS)} passed")
    return success_count == len(CONTAINER_TEST_CONFIGS)
```

## Running the Tests

### Test Execution

```bash
# Run all tests
pytest tests/

# Run only build tests
pytest tests/test_container_builds.py

# Run only runtime tests
pytest tests/test_container_runtime.py

# Run tests with verbose output
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=poststack --cov-report=html

# Run performance tests
pytest tests/ -m performance

# Run tests for specific container
pytest tests/ -k postgres
```

### Test Reports

The test suite generates comprehensive reports:

```bash
# Generate build performance report
pytest tests/test_container_builds.py --build-report

# Generate runtime verification report
pytest tests/test_container_runtime.py --runtime-report

# Generate combined test report
pytest tests/ --html=reports/test_results.html --self-contained-html
```

## Continuous Integration

### GitHub Actions Integration

```yaml
# .github/workflows/container-tests.yml
name: Container Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r requirements-test.txt
    
    - name: Install Podman
      run: |
        sudo apt-get update
        sudo apt-get install -y podman
    
    - name: Run container build tests
      run: |
        pytest tests/test_container_builds.py -v --build-report
    
    - name: Run container runtime tests
      run: |
        pytest tests/test_container_runtime.py -v --runtime-report
    
    - name: Generate test reports
      run: |
        pytest tests/ --html=reports/test_results.html --self-contained-html
    
    - name: Upload test reports
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: test-reports
        path: reports/
```

This comprehensive testing framework ensures that:

1. **All container builds are tested** with timing and success verification
2. **All container runtime scenarios are verified** with health checks and side effects
3. **The CLI tool uses identical code paths** as the tests for high confidence
4. **Performance metrics are tracked** and reported
5. **Comprehensive logging** is provided for debugging
6. **Automated CI/CD integration** ensures tests run on every change

The shared codepath design means that if the tests pass, the CLI tool will work reliably, providing high confidence in production deployments.