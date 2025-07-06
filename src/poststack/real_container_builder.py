"""
Real container builder implementation for Phase 4

Extends the Phase 3 container management to work with actual container runtimes,
implementing multi-stage builds, layer caching, and build time measurement.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import PoststackConfig
from .container_management import ContainerBuilder
from .logging_config import SubprocessLogHandler
from .models import BuildResult, BuildStatus

logger = logging.getLogger(__name__)


class RealContainerBuilder(ContainerBuilder):
    """
    Real container builder that actually builds containers using podman/docker.
    
    Extends the mock container builder from Phase 3 to provide real container
    building capabilities with multi-stage builds and layer caching.
    """
    
    def __init__(self, config: PoststackConfig, log_handler: Optional[SubprocessLogHandler] = None):
        """Initialize real container builder."""
        super().__init__(config, log_handler)
        self.base_images_built = set()
        self.build_cache = {}
        
    def build_base_image(self) -> BuildResult:
        """
        Build the base-debian image that other containers depend on.
        
        Returns:
            BuildResult with build status and details
        """
        image_name = "poststack/base-debian:latest"
        dockerfile_path = Path("containers/base-debian/Dockerfile")
        
        logger.info("Building base image: %s", image_name)
        
        result = self.build_image(
            image_name=image_name,
            dockerfile_path=dockerfile_path,
            context_path=Path("."),  # Use project root as context
            tags=["poststack/base-debian:latest", "poststack/base-debian:1.0.0"],
            no_cache=False,  # Use cache for base image
            timeout=900,  # Longer timeout for base image
        )
        
        if result.success:
            self.base_images_built.add(image_name)
            logger.info("Base image built successfully: %s", image_name)
        else:
            logger.error("Failed to build base image: %s", image_name)
            
        return result
    
    def build_postgres_image(self) -> BuildResult:
        """
        Build the PostgreSQL container image.
        
        Returns:
            BuildResult with build status and details
        """
        # Ensure base image is built first
        if "poststack/base-debian:latest" not in self.base_images_built:
            base_result = self.build_base_image()
            if not base_result.success:
                logger.error("Cannot build postgres image: base image build failed")
                return base_result
        
        image_name = "poststack/postgres:latest"
        dockerfile_path = Path("containers/postgres/Dockerfile")
        
        logger.info("Building PostgreSQL image: %s", image_name)
        
        result = self.build_image(
            image_name=image_name,
            dockerfile_path=dockerfile_path,
            context_path=Path("."),  # Use project root as context
            tags=["poststack/postgres:latest", "poststack/postgres:15"],
            build_args={
                "POSTGRES_VERSION": "15",
            },
            no_cache=False,
            timeout=600,
        )
        
        if result.success:
            logger.info("PostgreSQL image built successfully: %s", image_name)
        else:
            logger.error("Failed to build PostgreSQL image: %s", image_name)
            
        return result
    
    def build_liquibase_image(self) -> BuildResult:
        """
        Build the Liquibase container image.
        
        Returns:
            BuildResult with build status and details
        """
        # Ensure base image is built first
        if "poststack/base-debian:latest" not in self.base_images_built:
            base_result = self.build_base_image()
            if not base_result.success:
                logger.error("Cannot build liquibase image: base image build failed")
                return base_result
        
        image_name = "poststack/liquibase:latest"
        dockerfile_path = Path("containers/liquibase/Dockerfile")
        
        logger.info("Building Liquibase image: %s", image_name)
        
        result = self.build_image(
            image_name=image_name,
            dockerfile_path=dockerfile_path,
            context_path=Path("."),  # Use project root as context
            tags=["poststack/liquibase:latest", "poststack/liquibase:4.24.0"],
            build_args={
                "LIQUIBASE_VERSION": "4.24.0",
            },
            no_cache=False,
            timeout=600,
        )
        
        if result.success:
            logger.info("Liquibase image built successfully: %s", image_name)
        else:
            logger.error("Failed to build Liquibase image: %s", image_name)
            
        return result
    
    def build_all_phase4_images(self, parallel: bool = False) -> Dict[str, BuildResult]:
        """
        Build all Phase 4 container images in dependency order.
        
        Args:
            parallel: Whether to build non-dependent images in parallel
            
        Returns:
            Dictionary mapping image names to BuildResult objects
        """
        results = {}
        
        logger.info("Starting Phase 4 multi-stage container build process")
        
        # Stage 1: Build base image (required by all others)
        logger.info("Stage 1: Building base image")
        base_result = self.build_base_image()
        results["base-debian"] = base_result
        
        if not base_result.success:
            logger.error("Base image build failed, cannot continue with dependent images")
            return results
        
        # Stage 2: Build service images (can be done in parallel since they don't depend on each other)
        logger.info("Stage 2: Building service images")
        
        if parallel:
            # Build postgres and liquibase in parallel
            build_specs = [
                {
                    "image_name": "poststack/postgres:latest",
                    "dockerfile_path": Path("containers/postgres/Dockerfile"),
                    "tags": ["poststack/postgres:latest", "poststack/postgres:15"],
                    "build_args": {"POSTGRES_VERSION": "15"},
                    "timeout": 600,
                },
                {
                    "image_name": "poststack/liquibase:latest", 
                    "dockerfile_path": Path("containers/liquibase/Dockerfile"),
                    "tags": ["poststack/liquibase:latest", "poststack/liquibase:4.24.0"],
                    "build_args": {"LIQUIBASE_VERSION": "4.24.0"},
                    "timeout": 600,
                },
            ]
            
            parallel_results = self.build_images_parallel(build_specs, max_concurrent=2)
            results["postgres"] = parallel_results[0]
            results["liquibase"] = parallel_results[1]
        else:
            # Build sequentially
            results["postgres"] = self.build_postgres_image()
            results["liquibase"] = self.build_liquibase_image()
        
        # Log final results
        successful = sum(1 for r in results.values() if r.success)
        total = len(results)
        total_build_time = sum(r.build_time for r in results.values())
        
        logger.info(
            "Phase 4 build complete: %d/%d successful in %.1fs",
            successful, total, total_build_time
        )
        
        if successful == total:
            logger.info("✅ All Phase 4 images built successfully!")
        else:
            logger.error("❌ Some Phase 4 images failed to build")
            for name, result in results.items():
                if not result.success:
                    logger.error("Failed: %s (exit code: %s)", name, result.exit_code)
        
        return results
    
    def verify_layer_caching(self, image_name: str, dockerfile_path: Path) -> Dict[str, any]:
        """
        Verify that layer caching is working by building the same image twice.
        
        Args:
            image_name: Name of image to test
            dockerfile_path: Path to Dockerfile
            
        Returns:
            Dictionary with caching analysis results
        """
        logger.info("Testing layer caching for %s", image_name)
        
        # First build (no cache)
        logger.info("First build (no cache)")
        first_result = self.build_image(
            image_name=f"{image_name}:cache-test-1",
            dockerfile_path=dockerfile_path,
            no_cache=True,
        )
        
        if not first_result.success:
            return {
                "cache_working": False,
                "error": "First build failed",
                "first_build_time": first_result.build_time,
            }
        
        # Second build (with cache)
        logger.info("Second build (with cache)")
        second_result = self.build_image(
            image_name=f"{image_name}:cache-test-2",
            dockerfile_path=dockerfile_path,
            no_cache=False,
        )
        
        if not second_result.success:
            return {
                "cache_working": False,
                "error": "Second build failed", 
                "first_build_time": first_result.build_time,
            }
        
        # Analyze results
        cache_benefit = first_result.build_time - second_result.build_time
        cache_working = cache_benefit > 0 and second_result.build_time < first_result.build_time * 0.8
        
        analysis = {
            "cache_working": cache_working,
            "first_build_time": first_result.build_time,
            "second_build_time": second_result.build_time,
            "cache_benefit_seconds": cache_benefit,
            "cache_benefit_percent": (cache_benefit / first_result.build_time) * 100 if first_result.build_time > 0 else 0,
            "recommendation": "Layer caching is working" if cache_working else "Layer caching may not be optimal",
        }
        
        logger.info("Layer caching analysis: %s", analysis)
        return analysis
    
    def get_image_info(self, image_name: str) -> Optional[Dict[str, any]]:
        """
        Get detailed information about a built image.
        
        Args:
            image_name: Name of image to inspect
            
        Returns:
            Dictionary with image information or None if image doesn't exist
        """
        try:
            cmd = [self.container_runtime, "inspect", image_name]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if result.returncode == 0:
                import json
                image_data = json.loads(result.stdout)[0]
                
                # Extract useful information
                info = {
                    "id": image_data.get("Id", "")[:12],
                    "created": image_data.get("Created", ""),
                    "size_bytes": image_data.get("Size", 0),
                    "size_mb": round(image_data.get("Size", 0) / 1024 / 1024, 1),
                    "architecture": image_data.get("Architecture", ""),
                    "os": image_data.get("Os", ""),
                    "labels": image_data.get("Config", {}).get("Labels", {}),
                    "layers": len(image_data.get("RootFS", {}).get("Layers", [])),
                }
                
                return info
            
            return None
            
        except Exception as e:
            logger.warning("Failed to get image info for %s: %s", image_name, e)
            return None
    
    def cleanup_test_images(self) -> None:
        """Clean up test images created during layer cache testing."""
        logger.info("Cleaning up test images")
        
        try:
            # List all images with cache-test tag
            cmd = [self.container_runtime, "images", "--filter", "reference=*:cache-test-*", "-q"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout.strip():
                image_ids = result.stdout.strip().split('\n')
                
                # Remove test images
                for image_id in image_ids:
                    if image_id.strip():
                        self.remove_image(image_id.strip(), force=True)
                        logger.debug("Removed test image: %s", image_id.strip())
                
                logger.info("Cleaned up %d test images", len(image_ids))
            else:
                logger.info("No test images to clean up")
                
        except Exception as e:
            logger.warning("Failed to cleanup test images: %s", e)