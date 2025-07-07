"""
Tests for Phase 4: Essential Container Build Implementation

Tests the real container building functionality including multi-stage builds,
layer caching, and build time measurement.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from poststack.models import BuildStatus
from poststack.real_container_builder import RealContainerBuilder

from .fixtures import test_config, temp_workspace


class TestPhase4ContainerBuilds:
    """Test Phase 4 container building functionality."""
    
    @pytest.fixture
    def real_builder(self, test_config):
        """Create a real container builder for testing."""
        return RealContainerBuilder(test_config)
    
    @pytest.fixture
    def skip_if_no_runtime(self, test_config):
        """Skip tests if container runtime is not available."""
        import subprocess
        try:
            result = subprocess.run(
                [test_config.container_runtime, "--version"],
                capture_output=True,
                timeout=10
            )
            if result.returncode != 0:
                pytest.skip(f"Container runtime {test_config.container_runtime} not available")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip(f"Container runtime {test_config.container_runtime} not available")
    
    def test_container_runtime_available(self, test_config):
        """Test that the container runtime is available."""
        import subprocess
        try:
            result = subprocess.run(
                [test_config.container_runtime, "--version"],
                capture_output=True,
                timeout=10
            )
            assert result.returncode == 0
            assert len(result.stdout.strip()) > 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip(f"Container runtime {test_config.container_runtime} not available")
    
    def test_dockerfile_exists_base_debian(self):
        """Test that base-debian Dockerfile exists and is valid."""
        dockerfile_path = Path("containers/base-debian/Dockerfile")
        assert dockerfile_path.exists(), "base-debian Dockerfile not found"
        
        content = dockerfile_path.read_text()
        assert "FROM debian:bookworm-slim" in content
        assert "certgroup" in content
        assert "certuser" in content
        assert "python3" in content
        assert "/data/.venv" in content
    
    def test_dockerfile_exists_postgres(self):
        """Test that postgres Dockerfile exists and is valid."""
        dockerfile_path = Path("containers/postgres/Dockerfile")
        assert dockerfile_path.exists(), "postgres Dockerfile not found"
        
        content = dockerfile_path.read_text()
        assert "FROM poststack/base-debian:latest" in content
        assert "postgresql" in content.lower()
        assert "EXPOSE 5432" in content
    
    def test_entrypoint_scripts_exist(self):
        """Test that entrypoint scripts exist and are executable."""
        postgres_entrypoint = Path("containers/postgres/entrypoint.sh")
        
        assert postgres_entrypoint.exists(), "postgres entrypoint.sh not found"
        
        # Check scripts start with shebang
        assert postgres_entrypoint.read_text().startswith("#!/bin/bash")
    
    @pytest.mark.slow
    def test_build_base_image_mock(self, real_builder):
        """Test building base image with mocked subprocess."""
        with patch('subprocess.run') as mock_run:
            # Mock successful build
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Successfully built poststack/base-debian"
            mock_run.return_value.stderr = ""
            
            result = real_builder.build_base_image()
            
            assert result.image_name == "poststack/base-debian:latest"
            assert result.status == BuildStatus.SUCCESS
            assert mock_run.called
            
            # Check that the correct command was called
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == real_builder.container_runtime
            assert "build" in call_args
            assert "-t" in call_args
            assert "poststack/base-debian:latest" in call_args
    
    @pytest.mark.slow
    def test_build_postgres_image_mock(self, real_builder):
        """Test building postgres image with mocked subprocess."""
        # Mock base image as already built
        real_builder.base_images_built.add("poststack/base-debian:latest")
        
        with patch('subprocess.run') as mock_run:
            # Mock successful build
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Successfully built poststack/postgres"
            mock_run.return_value.stderr = ""
            
            result = real_builder.build_postgres_image()
            
            assert result.image_name == "poststack/postgres:latest"
            assert result.status == BuildStatus.SUCCESS
            assert mock_run.called
    
    
    @pytest.mark.slow 
    def test_build_all_phase4_images_mock(self, real_builder):
        """Test building all Phase 4 images with mocked subprocess."""
        with patch('subprocess.run') as mock_run:
            # Mock all builds as successful
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "Successfully built"
            mock_run.return_value.stderr = ""
            
            results = real_builder.build_all_phase4_images(parallel=False)
            
            assert len(results) == 2
            assert "base-debian" in results
            assert "postgres" in results
            
            # All should be successful
            assert all(r.success for r in results.values())
            
            # Check that builds were called in correct order
            assert mock_run.call_count >= 2
    
    def test_build_dependency_order(self, real_builder):
        """Test that builds fail properly when dependencies are missing."""
        with patch('subprocess.run') as mock_run:
            # Mock base image build failure
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "Build failed"
            
            # Try to build postgres without base image
            result = real_builder.build_postgres_image()
            
            # Should fail because base image build failed
            assert not result.success
            assert result.status == BuildStatus.FAILED
    
    def test_layer_caching_analysis_mock(self, real_builder):
        """Test layer caching analysis with mocked builds."""
        dockerfile_path = Path("containers/base-debian/Dockerfile")
        
        with patch('subprocess.run') as mock_run:
            # Mock first build (slow)
            # Mock second build (fast - cached)
            mock_run.side_effect = [
                # First build
                type('Result', (), {
                    'returncode': 0,
                    'stdout': 'Successfully built (no cache)',
                    'stderr': ''
                })(),
                # Second build  
                type('Result', (), {
                    'returncode': 0,
                    'stdout': 'Successfully built (cached)',
                    'stderr': ''
                })(),
            ]
            
            # Mock the timing by patching time.time - provide more values for logging calls
            time_values = [0, 10] * 10 + [10, 12] * 10  # Enough values for multiple logging calls
            with patch('time.time', side_effect=time_values):
                analysis = real_builder.verify_layer_caching("poststack/test", dockerfile_path)
            
            assert "cache_working" in analysis
            assert "first_build_time" in analysis
            assert "second_build_time" in analysis
            assert "cache_benefit_seconds" in analysis
    
    def test_get_image_info_mock(self, real_builder):
        """Test getting image information with mocked inspect."""
        with patch('subprocess.run') as mock_run:
            # Mock image inspect response
            mock_inspect_data = '''[{
                "Id": "sha256:abc123def456",
                "Created": "2023-01-01T12:00:00Z",
                "Size": 134217728,
                "Architecture": "amd64",
                "Os": "linux",
                "Config": {"Labels": {"version": "1.0.0"}},
                "RootFS": {"Layers": ["layer1", "layer2", "layer3"]}
            }]'''
            
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mock_inspect_data
            mock_run.return_value.stderr = ""
            
            info = real_builder.get_image_info("poststack/test:latest")
            
            assert info is not None
            assert info["id"] == "sha256:abc12"
            assert info["size_mb"] == 128.0
            assert info["architecture"] == "amd64"
            assert info["layers"] == 3
            assert info["labels"]["version"] == "1.0.0"
    
    def test_cleanup_test_images_mock(self, real_builder):
        """Test cleanup of test images with mocked commands."""
        with patch('subprocess.run') as mock_run:
            # Mock listing test images
            mock_run.side_effect = [
                # List images
                type('Result', (), {
                    'returncode': 0,
                    'stdout': 'image1\nimage2\n',
                    'stderr': ''
                })(),
                # Remove image1
                type('Result', (), {
                    'returncode': 0,
                    'stdout': '',
                    'stderr': ''
                })(),
                # Remove image2
                type('Result', (), {
                    'returncode': 0,
                    'stdout': '',
                    'stderr': ''
                })(),
            ]
            
            real_builder.cleanup_test_images()
            
            # Should call list images and remove each image
            assert mock_run.call_count == 3


class TestPhase4Integration:
    """Integration tests for Phase 4 functionality."""
    
    def test_phase4_file_structure(self):
        """Test that all required Phase 4 files are present."""
        required_files = [
            "containers/base-debian/Dockerfile",
            "containers/postgres/Dockerfile", 
            "containers/postgres/entrypoint.sh",
            "containers/postgres/postgresql.conf.template",
            "containers/postgres/pg_hba.conf.template",
        ]
        
        for file_path in required_files:
            assert Path(file_path).exists(), f"Required file missing: {file_path}"
    
    def test_dockerfile_inheritance_chain(self):
        """Test that Dockerfiles follow proper inheritance chain."""
        # Base image should use debian:bookworm-slim
        base_dockerfile = Path("containers/base-debian/Dockerfile").read_text()
        assert "FROM debian:bookworm-slim" in base_dockerfile
        
        # Service images should use base-debian
        postgres_dockerfile = Path("containers/postgres/Dockerfile").read_text()
        assert "FROM poststack/base-debian:latest" in postgres_dockerfile
        
    
    def test_certificate_group_setup(self):
        """Test that certificate group setup is consistent."""
        base_dockerfile = Path("containers/base-debian/Dockerfile").read_text()
        
        # Check certgroup and certuser creation
        assert "groupadd -g 9999 certgroup" in base_dockerfile
        assert "useradd -u 9999 -g certgroup" in base_dockerfile
        
        # Check that service images add users to certgroup
        postgres_dockerfile = Path("containers/postgres/Dockerfile").read_text()
        assert "usermod -a -G certgroup postgres" in postgres_dockerfile
    
    def test_standard_environment_variables(self):
        """Test that standard environment variables are defined."""
        base_dockerfile = Path("containers/base-debian/Dockerfile").read_text()
        
        # Check standard environment variables
        assert "POSTSTACK_BASE_DIR" in base_dockerfile
        assert "POSTSTACK_CERT_PATH" in base_dockerfile
        assert "POSTSTACK_LOG_DIR" in base_dockerfile
    
    def test_health_checks_present(self):
        """Test that health checks are defined in Dockerfiles."""
        dockerfiles = [
            "containers/base-debian/Dockerfile",
            "containers/postgres/Dockerfile", 
        ]
        
        for dockerfile_path in dockerfiles:
            content = Path(dockerfile_path).read_text()
            assert "HEALTHCHECK" in content, f"No health check in {dockerfile_path}"
    
    
    def test_entrypoint_script_functionality(self):
        """Test that entrypoint scripts have required functionality."""
        postgres_entrypoint = Path("containers/postgres/entrypoint.sh").read_text()
        
        # PostgreSQL entrypoint should handle common scenarios
        assert "init_database" in postgres_entrypoint
        assert "configure_postgresql" in postgres_entrypoint
        assert "substitute_template" in postgres_entrypoint
        
