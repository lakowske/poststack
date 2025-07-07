#!/usr/bin/env python3
"""
Demonstration script for building Phase 4 container images
"""

import logging
import sys
from pathlib import Path

# Add src to path so we can import poststack modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from poststack.config import PoststackConfig
from poststack.real_container_builder import RealContainerBuilder
from poststack.logging_config import setup_logging

def main():
    """Build all Phase 4 container images"""
    
    # Setup logging
    setup_logging(level=logging.INFO, log_dir=Path("logs"))
    logger = logging.getLogger(__name__)
    
    print("🚀 Poststack Phase 4 Container Builder")
    print("=" * 50)
    
    try:
        # Create configuration
        config = PoststackConfig()
        logger.info("Loaded configuration: %s", config.container_runtime)
        
        # Create real container builder
        builder = RealContainerBuilder(config)
        logger.info("Initialized RealContainerBuilder")
        
        print(f"Using container runtime: {config.container_runtime}")
        print(f"Container configuration: {config.container_config}")
        print()
        
        # Build all Phase 4 images
        print("Building Phase 4 container images...")
        print("This will build: base-debian and postgres")
        print()
        
        results = builder.build_all_phase4_images(parallel=False)
        
        # Show results
        print("\n📊 Build Results:")
        print("-" * 30)
        
        total_time = 0
        successful = 0
        
        for name, result in results.items():
            status_icon = "✅" if result.success else "❌"
            print(f"{status_icon} {name:15} | {result.status.value:8} | {result.build_time:6.1f}s")
            
            if result.success:
                successful += 1
            total_time += result.build_time
            
            # Show any errors
            if not result.success and result.error_output:
                print(f"   Error: {result.error_output[:100]}...")
        
        print("-" * 30)
        print(f"Total: {successful}/{len(results)} successful in {total_time:.1f}s")
        
        if successful == len(results):
            print("\n🎉 All Phase 4 images built successfully!")
            
            # Show image info
            print("\n📦 Built Images:")
            for name in results.keys():
                image_name = f"poststack/{name}:latest"
                info = builder.get_image_info(image_name)
                if info:
                    print(f"   {image_name} ({info['size_mb']} MB, {info['layers']} layers)")
        else:
            print(f"\n⚠️  Some builds failed. Check logs for details.")
            return 1
            
    except Exception as e:
        logger.error("Build failed: %s", e)
        print(f"\n❌ Build failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())