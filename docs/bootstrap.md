# Bootstrap Process Specification

## Purpose

This document defines the bootstrap process for the Poststack Python server, including database initialization and fallback mechanisms when database connectivity is unavailable.

## Overview

The Python server must be resilient to database connection failures and provide a self-service mechanism for administrators to configure database connectivity through a web interface.

## Bootstrap Flow

### 1. Startup Sequence

```
┌─────────────────┐
│  Server Start   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Env Vars  │───► DATABASE_URL present?
└────────┬────────┘              │
         │                       │ No
         │ Yes                   ▼
         ▼              ┌─────────────────┐
┌─────────────────┐     │ Start Bootstrap │
│ Test Connection │     │   Web Server    │
└────────┬────────┘     └─────────────────┘
         │                       │
         │ Success               │
         │                       ▼
         ▼              ┌─────────────────┐
┌─────────────────┐     │  Show DB Setup  │
│ Start Full App  │     │      Form       │
└─────────────────┘     └─────────────────┘
```

### 2. Configuration Sources

The server checks for database configuration in the following order:

1. **Environment Variable**: `DATABASE_URL` (preferred)
   - Format: `postgresql://user:password@host:port/database`
   - Example: `postgresql://poststack:secret@localhost:5432/poststack`

2. **Configuration File**: `/etc/poststack/database.conf` (optional)
   - JSON format with connection parameters

3. **Bootstrap Mode**: If no configuration found or connection fails

## Bootstrap Mode Implementation

### Web Server Requirements

When operating in bootstrap mode, the server must:

1. Start a minimal HTTP server on port 8080 (configurable via `BOOTSTRAP_PORT`)
2. Serve only the database configuration endpoints
3. Use in-memory session storage (no database dependency)
4. Provide clear error messages about the connection failure

### Endpoints

#### GET `/bootstrap`
- Returns the database configuration form
- Shows current connection error (if any)
- No authentication required in bootstrap mode

#### POST `/bootstrap/test`
- Tests the provided database connection
- Returns JSON response with success/failure status
- Does not save configuration

#### POST `/bootstrap/save`
- Validates and saves the database configuration
- Attempts to initialize the database schema
- Restarts the server in full mode if successful

### Admin Configuration Form

The bootstrap form must collect:

```html
<form id="db-config">
  <h1>Poststack Database Configuration</h1>
  
  <div class="error">{connection_error}</div>
  
  <fieldset>
    <legend>Database Connection</legend>
    
    <label>
      Host:
      <input type="text" name="host" value="localhost" required>
    </label>
    
    <label>
      Port:
      <input type="number" name="port" value="5432" required>
    </label>
    
    <label>
      Database Name:
      <input type="text" name="database" value="poststack" required>
    </label>
    
    <label>
      Username:
      <input type="text" name="username" required>
    </label>
    
    <label>
      Password:
      <input type="password" name="password" required>
    </label>
  </fieldset>
  
  <button type="button" onclick="testConnection()">Test Connection</button>
  <button type="submit">Save & Initialize</button>
</form>
```

## Database Initialization

### Schema Detection and Management

When a valid database connection is established:

1. Check if schema exists (query for `DATABASECHANGELOG` table from Liquibase)
2. Determine schema state:
   - **No schema**: Offer to bootstrap
   - **Outdated schema**: Offer to update
   - **Current schema**: Start normally

### Schema States

```
┌─────────────────┐
│ DB Connection   │
│   Successful    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     No DATABASECHANGELOG
│ Check Liquibase │─────────────────────────┐
│     Tables      │                         │
└────────┬────────┘                         ▼
         │                         ┌─────────────────┐
         │ Exists                  │  Show Schema    │
         ▼                         │ Bootstrap Form  │
┌─────────────────┐                └─────────────────┘
│ Check Pending   │                         │
│   Changesets    │                         │
└────────┬────────┘                         ▼
         │                         ┌─────────────────┐
         │ None                    │ Run Liquibase   │
         │                         │   Bootstrap     │
         ▼                         └─────────────────┘
┌─────────────────┐
│ Start Full App  │
└─────────────────┘
         │
         │ Pending Changes
         ▼
┌─────────────────┐
│  Show Schema    │
│  Update Form    │
└─────────────────┘
```

### Liquibase Integration

The server uses Liquibase via Podman container for all schema operations:

```python
def run_liquibase(database_url, command='update'):
    """Execute Liquibase command via Podman container"""
    
    # Parse database URL
    db_params = parse_database_url(database_url)
    
    # Liquibase command
    cmd = [
        'podman', 'run', '--rm',
        '-v', f'{os.path.abspath("./changelog")}:/liquibase/changelog:ro',
        'liquibase/liquibase:latest',
        f'--url=jdbc:postgresql://{db_params.host}:{db_params.port}/{db_params.database}',
        f'--username={db_params.username}',
        f'--password={db_params.password}',
        '--changeLogFile=changelog/db.changelog-master.xml',
        command
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result
```

### Changelog Structure

```
changelog/
├── db.changelog-master.xml
├── changes/
│   ├── 001-core-tables.xml
│   ├── 002-service-tables.xml
│   ├── 003-initial-data.xml
│   └── 004-indexes.xml
└── rollback/
    └── emergency-rollback.xml
```

Master changelog example:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<databaseChangeLog
    xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog
        http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-latest.xsd">
    
    <include file="changes/001-core-tables.xml" relativeToChangelogFile="true"/>
    <include file="changes/002-service-tables.xml" relativeToChangelogFile="true"/>
    <include file="changes/003-initial-data.xml" relativeToChangelogFile="true"/>
    <include file="changes/004-indexes.xml" relativeToChangelogFile="true"/>
</databaseChangeLog>
```

### Schema Bootstrap Form

When no schema is detected:

```html
<form id="schema-bootstrap">
  <h1>Database Schema Required</h1>
  
  <div class="info">
    The database connection is successful, but no Poststack schema was found.
    Would you like to initialize the database schema?
  </div>
  
  <div class="warning">
    This will create the following:
    <ul>
      <li>Core configuration tables</li>
      <li>Service management tables</li>
      <li>User and permission tables</li>
      <li>Default configuration values</li>
    </ul>
  </div>
  
  <button type="button" onclick="previewChanges()">Preview Changes</button>
  <button type="submit" onclick="bootstrapSchema()">Initialize Schema</button>
</form>
```

### Schema Update Form

When pending changes are detected:

```html
<form id="schema-update">
  <h1>Database Schema Update Available</h1>
  
  <div class="info">
    {pending_count} database changes are pending.
  </div>
  
  <div id="pending-changes">
    <!-- Populated by Liquibase status command -->
  </div>
  
  <button type="button" onclick="generateSQL()">Generate SQL</button>
  <button type="button" onclick="validateChanges()">Validate</button>
  <button type="submit" onclick="updateSchema()">Apply Updates</button>
  <button type="button" onclick="skipUpdate()">Skip (Start Anyway)</button>
</form>
```

### API Endpoints for Schema Management

#### GET `/bootstrap/schema/status`
```python
def get_schema_status():
    """Check current schema state"""
    result = run_liquibase(database_url, 'status')
    return {
        'has_changelog': check_changelog_exists(),
        'pending_changes': parse_pending_changes(result.stdout),
        'last_update': get_last_changelog_execution()
    }
```

#### GET `/bootstrap/schema/preview`
```python
def preview_changes():
    """Generate SQL for pending changes"""
    result = run_liquibase(database_url, 'updateSQL')
    return {
        'sql': result.stdout,
        'changeset_count': count_changesets(result.stdout)
    }
```

#### POST `/bootstrap/schema/update`
```python
def update_schema():
    """Apply pending schema changes"""
    # Create backup point
    tag_result = run_liquibase(database_url, f'tag --tag=pre-update-{timestamp}')
    
    # Apply updates
    update_result = run_liquibase(database_url, 'update')
    
    if update_result.returncode != 0:
        # Offer rollback
        return {
            'success': False,
            'error': update_result.stderr,
            'rollback_tag': f'pre-update-{timestamp}'
        }
    
    return {
        'success': True,
        'changes_applied': count_applied_changes(update_result.stdout)
    }
```

#### POST `/bootstrap/schema/rollback`
```python
def rollback_schema(tag):
    """Rollback to a specific tag"""
    result = run_liquibase(database_url, f'rollback --tag={tag}')
    return {
        'success': result.returncode == 0,
        'message': result.stdout
    }
```

### Initial Configuration

After schema creation, Liquibase applies initial data:

```xml
<!-- changes/003-initial-data.xml -->
<databaseChangeLog>
    <changeSet id="3.1" author="poststack">
        <insert tableName="config">
            <column name="key" value="domain_name"/>
            <column name="value" value=""/>
            <column name="description" value="Primary domain - must be configured"/>
        </insert>
        <insert tableName="config">
            <column name="key" value="le_email"/>
            <column name="value" value=""/>
            <column name="description" value="Let's Encrypt email - must be configured"/>
        </insert>
        <insert tableName="config">
            <column name="key" value="cert_path"/>
            <column name="value" value="/data/certificates"/>
            <column name="description" value="Certificate storage path"/>
        </insert>
        <insert tableName="config">
            <column name="key" value="log_level"/>
            <column name="value" value="INFO"/>
            <column name="description" value="Default logging level"/>
        </insert>
    </changeSet>
    
    <changeSet id="3.2" author="poststack">
        <insert tableName="services">
            <column name="name" value="postgres"/>
            <column name="enabled" valueBoolean="true"/>
        </insert>
        <insert tableName="services">
            <column name="name" value="apache"/>
            <column name="enabled" valueBoolean="false"/>
        </insert>
        <insert tableName="services">
            <column name="name" value="bind"/>
            <column name="enabled" valueBoolean="false"/>
        </insert>
        <insert tableName="services">
            <column name="name" value="mail"/>
            <column name="enabled" valueBoolean="false"/>
        </insert>
        <insert tableName="services">
            <column name="name" value="certbot"/>
            <column name="enabled" valueBoolean="false"/>
        </insert>
    </changeSet>
</databaseChangeLog>
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

### Bootstrap Mode

- Only accessible from localhost by default
- Can be configured with `BOOTSTRAP_ALLOWED_IPS` environment variable
- Automatically disables after successful configuration
- Rate limiting on configuration attempts (10 per minute)

### Credential Storage

- Database URL never logged in full (password masked)
- Credentials encrypted when saved to configuration file
- Environment variables preferred over file storage

## Implementation Notes

### Python Server Structure

```python
# main.py
import os
from poststack.bootstrap import BootstrapServer
from poststack.app import PoststackApp

def main():
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url or not test_connection(database_url):
        # Start in bootstrap mode
        server = BootstrapServer()
        server.run()
    else:
        # Start full application
        app = PoststackApp(database_url)
        app.run()

if __name__ == '__main__':
    main()
```

### State Transition

The server must handle graceful transition from bootstrap to full mode:

1. Save configuration
2. Test connection and initialize schema
3. Signal current process to shut down
4. Start new process with full application

## Testing Considerations

1. **Unit Tests**: Mock database connections to test bootstrap flow
2. **Integration Tests**: Use Docker to test actual connection scenarios
3. **UI Tests**: Verify form validation and error display
4. **Security Tests**: Ensure bootstrap mode has proper access controls