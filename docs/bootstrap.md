# Bootstrap CLI Tool Specification

## Purpose

This document defines the bootstrap CLI tool for Poststack, which handles container image building, database endpoint verification, and schema management through command-line operations.

## Overview

The bootstrap CLI tool provides a centralized command-line interface for setting up and maintaining Poststack infrastructure. It handles container image builds, database connectivity verification, and schema updates with comprehensive logging to both stdout/stderr and structured log files.

## CLI Commands

### 1. Main Commands

```bash
# Build all container images
poststack-bootstrap build-images

# Verify database connectivity
poststack-bootstrap verify-db --url "postgresql://user:pass@host:port/db"

# Initialize database schema
poststack-bootstrap init-schema --url "postgresql://user:pass@host:port/db"

# Update database schema
poststack-bootstrap update-schema --url "postgresql://user:pass@host:port/db"

# Full bootstrap process (build + verify + init/update)
poststack-bootstrap setup --url "postgresql://user:pass@host:port/db"
```

### 2. Command Flow

```
┌─────────────────┐
│ CLI Invocation  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parse Arguments │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Setup Logging   │───► logs/ directory created
└────────┬────────┘     stdout/stderr configured
         │
         ▼
┌─────────────────┐
│ Execute Command │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Log Results     │
└─────────────────┘
```

### 3. Configuration Sources

The CLI tool checks for database configuration in the following order:

1. **Command Line Arguments**: `--url` parameter (highest priority)
   - Format: `postgresql://user:password@host:port/database`
   - Example: `--url "postgresql://poststack:secret@localhost:5432/poststack"`

2. **Environment Variable**: `DATABASE_URL` (fallback)
   - Format: `postgresql://user:password@host:port/database`
   - Example: `export DATABASE_URL="postgresql://poststack:secret@localhost:5432/poststack"`

3. **Configuration File**: `/etc/poststack/database.conf` (optional)
   - JSON format with connection parameters

## Logging Implementation

### Logging Structure

The CLI tool implements structured logging with the following components:

1. **Console Output**: Summary progress and results to stdout/stderr
2. **Subprocess Logs**: Detailed output from container builds and schema operations
3. **Structured Logs**: JSON-formatted logs for integration with monitoring systems

### Logging Configuration

```python
import logging
import os
from datetime import datetime

# Create logs directory structure
logs_dir = "logs"
os.makedirs(logs_dir, exist_ok=True)
os.makedirs(f"{logs_dir}/containers", exist_ok=True)
os.makedirs(f"{logs_dir}/database", exist_ok=True)

# Configure main logger
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(f"{logs_dir}/bootstrap_{timestamp}.log"),
        logging.StreamHandler()  # stdout
    ]
)
```

### Subprocess Logging

All subprocess operations (container builds, schema management) redirect output to dedicated log files:

```python
def run_with_logging(cmd, log_file, operation_name):
    """Run command with output logged to file and progress to stdout"""
    logger = logging.getLogger(__name__)
    
    logger.info(f"Starting {operation_name}")
    print(f"▶ {operation_name}...")
    
    with open(log_file, 'w') as f:
        process = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Monitor process and show progress
        while process.poll() is None:
            print(".", end="", flush=True)
            time.sleep(1)
        
        return_code = process.wait()
    
    if return_code == 0:
        logger.info(f"✓ {operation_name} completed successfully")
        print(f" ✓ Complete")
    else:
        logger.error(f"✗ {operation_name} failed with code {return_code}")
        print(f" ✗ Failed (see {log_file})")
    
    return return_code
```

## Command Implementations

### Image Building Command

```python
def build_images():
    """Build all container images with logging"""
    logger = logging.getLogger(__name__)
    
    images = [
        ("postgres", "containers/postgres/Dockerfile"),
        ("apache", "containers/apache/Dockerfile"),
        ("dovecot", "containers/dovecot/Dockerfile"),
        ("bind", "containers/bind/Dockerfile"),
    ]
    
    success_count = 0
    total_count = len(images)
    
    for image_name, dockerfile_path in images:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"logs/containers/{image_name}_build_{timestamp}.log"
        
        cmd = [
            "podman", "build", 
            "-t", f"poststack-{image_name}:latest",
            "-f", dockerfile_path,
            "."
        ]
        
        result = run_with_logging(cmd, log_file, f"Building {image_name} image")
        
        if result == 0:
            success_count += 1
        else:
            logger.error(f"Failed to build {image_name} image")
    
    logger.info(f"Image builds completed: {success_count}/{total_count} successful")
    return success_count == total_count
```

### Database Verification Command

```python
def verify_database(database_url):
    """Verify database connectivity and log results"""
    logger = logging.getLogger(__name__)
    
    try:
        # Parse database URL
        parsed = urllib.parse.urlparse(database_url)
        
        logger.info(f"Testing connection to {parsed.hostname}:{parsed.port}/{parsed.path[1:]}")
        print(f"▶ Testing database connection...")
        
        # Test connection
        import psycopg2
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Test basic operations
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        
        cursor.execute("SELECT current_database();")
        database = cursor.fetchone()[0]
        
        conn.close()
        
        logger.info(f"✓ Database connection successful")
        logger.info(f"  Database: {database}")
        logger.info(f"  Version: {version}")
        print(f" ✓ Connection successful")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Database connection failed: {str(e)}")
        print(f" ✗ Connection failed: {str(e)}")
        return False
```

## Database Initialization

### Schema Detection and Management

The CLI tool automatically detects schema state and takes appropriate action:

1. Check if schema exists (query for `poststack` schema)
2. Determine schema state:
   - **No schema**: Initialize with `init-schema` command
   - **Outdated schema**: Update with `update-schema` command
   - **Current schema**: Report status and exit

### Schema States

```
┌─────────────────┐
│ CLI Command     │
│   Executed      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     No Schema
│ Check Schema    │─────────────────────────┐
│     Tables      │                         │
└────────┬────────┘                         ▼
         │                         ┌─────────────────┐
         │ Exists                  │ Run init-schema │
         ▼                         │     Command     │
┌─────────────────┐                └─────────────────┘
│ Check Pending   │                         │
│   Changesets    │                         │
└────────┬────────┘                         ▼
         │                         ┌─────────────────┐
         │ None                    │ Initialize DB   │
         │                         │   with Logs     │
         ▼                         └─────────────────┘
┌─────────────────┐
│ Schema Current  │
│  Exit Success   │
└─────────────────┘
         │
         │ Pending Changes
         ▼
┌─────────────────┐
│Run update-schema│
│    Command      │
└─────────────────┘
```


### Schema Management Integration

The CLI tool uses the built-in SQL migration system for all schema operations:

```python
def init_schema(database_url):
    """Initialize database schema from scratch"""
    logger = logging.getLogger(__name__)
    
    from .schema_management import SchemaManager
    from .config import PoststackConfig
    
    config = PoststackConfig()
    schema_manager = SchemaManager(config)
    
    logger.info("Initializing database schema")
    
    # Run migrations
    result = schema_manager.update_schema(database_url)
    
    if result.success:
        logger.info("Schema initialization completed successfully")
        
        # Verify schema
        verification = schema_manager.verify_schema(database_url)
        if verification.passed:
            logger.info("Schema verification passed")
            return 0
        else:
            logger.error(f"Schema verification failed: {verification.message}")
            return -1
    else:
        logger.error(f"Schema initialization failed: {result.logs}")
        return -1

def update_schema(database_url):
    """Update existing schema to latest version"""
    logger = logging.getLogger(__name__)
    
    from .schema_management import SchemaManager
    from .config import PoststackConfig
    
    config = PoststackConfig()
    schema_manager = SchemaManager(config)
    
    logger.info("Updating database schema")
    
    # Run migrations
    result = schema_manager.update_schema(database_url)
    
    if result.success:
        logger.info("Schema update completed successfully")
        return 0
    else:
        logger.error(f"Schema update failed: {result.logs}")
        return -1
```

## Error Handling

### Connection Failures

Different error types require different responses:

1. **Network Error**: "Cannot connect to database at {host}:{port}"
2. **Authentication Error**: "Invalid username or password"
3. **Database Not Found**: "Database '{name}' does not exist"
4. **Permission Error**: "User lacks permission to create tables"

### Recovery Mechanisms

1. **Automatic Retry**: Attempt reconnection every 30 seconds
2. **Manual Override**: Admin can force bootstrap mode with `--bootstrap` flag
3. **Health Check**: `/health` endpoint returns 503 when in bootstrap mode

## Security Considerations

### CLI Tool Security

- Database URLs are never logged in full (passwords masked in all output)
- Credentials are only passed to subprocesses via secure methods
- Log files containing credentials are created with restricted permissions (600)
- Environment variables are preferred over command-line arguments for credentials

### Log File Security

- All log files are created with restricted permissions (600)
- Subprocess logs are rotated and cleaned up automatically
- Database connection details are sanitized in all log output
- Sensitive information is masked using regex patterns

## Implementation Notes

### CLI Tool Structure

```python
# poststack-bootstrap.py
import argparse
import logging
import os
import sys
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description='Poststack Bootstrap CLI Tool')
    
    # Global options
    parser.add_argument('--url', help='Database URL (overrides DATABASE_URL env var)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--log-dir', default='logs', help='Log directory (default: logs)')
    
    # Commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Build images command
    build_parser = subparsers.add_parser('build-images', help='Build all container images')
    build_parser.add_argument('--parallel', '-p', action='store_true', help='Build images in parallel')
    
    # Database commands
    verify_parser = subparsers.add_parser('verify-db', help='Verify database connectivity')
    
    init_parser = subparsers.add_parser('init-schema', help='Initialize database schema')
    
    update_parser = subparsers.add_parser('update-schema', help='Update database schema')
    
    # Full setup command
    setup_parser = subparsers.add_parser('setup', help='Run full bootstrap process')
    setup_parser.add_argument('--build-images', action='store_true', help='Include image building')
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_dir, args.verbose)
    
    # Get database URL
    database_url = args.url or os.getenv('DATABASE_URL')
    
    # Execute command
    if args.command == 'build-images':
        return build_images(parallel=args.parallel)
    elif args.command == 'verify-db':
        if not database_url:
            print("Error: Database URL required (--url or DATABASE_URL env var)")
            return 1
        return 0 if verify_database(database_url) else 1
    elif args.command == 'init-schema':
        if not database_url:
            print("Error: Database URL required (--url or DATABASE_URL env var)")
            return 1
        return 0 if init_schema(database_url) else 1
    elif args.command == 'update-schema':
        if not database_url:
            print("Error: Database URL required (--url or DATABASE_URL env var)")
            return 1
        return 0 if update_schema(database_url) else 1
    elif args.command == 'setup':
        return full_setup(database_url, args.build_images)
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())
```

### Full Setup Process

The `setup` command orchestrates the complete bootstrap process:

1. **Optional**: Build container images if `--build-images` flag is used
2. **Required**: Verify database connectivity
3. **Required**: Initialize or update database schema
4. **Output**: Summary of completed operations and next steps

## Testing Considerations

1. **Unit Tests**: Mock database connections and subprocess calls to test CLI logic
2. **Integration Tests**: Use Docker containers to test actual database operations
3. **CLI Tests**: Test argument parsing, error handling, and output formatting
4. **Security Tests**: Verify credentials are properly masked in logs and output
5. **Performance Tests**: Test image building and schema operations under load