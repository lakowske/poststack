#!/usr/bin/env python3
"""
Test script to verify Liquibase integration with our PostgreSQL container
"""

import logging
import sys
from pathlib import Path

# Add src to path so we can import poststack modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from poststack.config import PoststackConfig
from poststack.schema_management import SchemaManager

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

def main():
    print("🧪 Testing Liquibase Schema Integration")
    print("=" * 50)
    
    # Create test config
    config = PoststackConfig()
    
    # Database URL for our running container
    database_url = "postgresql://poststack:poststack_dev@localhost:5434/poststack"
    
    print(f"📊 Database URL: {database_url}")
    
    # Create schema manager
    schema_manager = SchemaManager(config)
    
    print("\n1. Testing database connection...")
    connection_result = schema_manager.database_manager.test_connection(database_url)
    print(f"   Connection: {'✅ SUCCESS' if connection_result.passed else '❌ FAILED'}")
    if not connection_result.passed:
        print(f"   Error: {connection_result.message}")
        return 1
    
    print("\n2. Initializing schema with Liquibase...")
    # Skip health check (status) since schema doesn't exist yet, go directly to initialization
    init_result = schema_manager.initialize_schema(database_url)
    print(f"   Initialize: {'✅ SUCCESS' if init_result.success else '❌ FAILED'}")
    if not init_result.success:
        print(f"   Error: {init_result.logs}")
        return 1
    
    print("\n3. Testing Liquibase health check after initialization...")
    health_result = schema_manager.health_check_liquibase(database_url)
    print(f"   Liquibase: {'✅ SUCCESS' if health_result.passed else '❌ FAILED'}")
    if not health_result.passed:
        print(f"   Error: {health_result.message}")
        # Don't return 1 here, just log the error
    
    print("\n4. Verifying schema...")
    verify_result = schema_manager.verify_schema(database_url)
    print(f"   Verify: {'✅ SUCCESS' if verify_result.passed else '❌ FAILED'}")
    if verify_result.passed:
        print(f"   Schema Version: {verify_result.details.get('schema_version', 'unknown')}")
        print(f"   Tables: {', '.join(verify_result.details.get('tables', []))}")
    else:
        print(f"   Error: {verify_result.message}")
    
    print("\n5. Getting schema status...")
    status = schema_manager.get_schema_status(database_url)
    print(f"   Status: {'✅ SUCCESS' if status['verification']['passed'] else '❌ FAILED'}")
    print(f"   Liquibase Status: {status['liquibase']['status']}")
    
    print("\n🎉 Liquibase integration test completed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())