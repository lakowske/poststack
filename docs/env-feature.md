# Environment Management Feature Specification

## Overview

This document specifies the implementation of comprehensive environment management for poststack, enabling users to orchestrate standard Docker Compose and Podman Pod files while providing postgres database management, variable substitution, and initialization workflows.

## Core Value Proposition

**"Postgres + Your Apps, Zero Config, Multiple Environments"**

Poststack manages postgres databases and injects database configuration into standard deployment files, allowing users to focus on business logic while maintaining environment isolation and professional deployment practices.

## Feature Goals

1. **Environment Isolation**: Clear separation between dev/staging/production with per-environment postgres databases
2. **Standard Deployment Files**: Use familiar Docker Compose and Podman Pod formats
3. **Database Integration**: Automatic postgres setup and configuration injection
4. **Init/Deploy Workflow**: Proper initialization (migrations, setup) before application deployment
5. **Variable Substitution**: Template-based configuration with debugging support
6. **Portability**: Users can export standard configs and run without poststack

## Architecture Design

### Project Structure
```
my-project/
├── deploy/
│   ├── init-compose.yml          # Database migrations, setup tasks
│   ├── app-compose.yml           # Main application containers
│   ├── staging-compose.yml       # Staging deployment
│   └── prod-pod.yaml            # Production Podman pod
├── containers/
│   ├── web/Dockerfile
│   └── worker/Dockerfile  
├── migrations/
│   ├── 001_create_users.sql
│   └── 002_add_orders.sql
├── environments/
│   ├── dev.env
│   ├── staging.env
│   └── production.env
└── .poststack.yml               # Environment definitions
```

### Configuration Format (.poststack.yml)

```yaml
# .poststack.yml
project:
  name: myapp
  
environments:
  dev:
    postgres:
      database: myapp_dev
      port: 5433
      user: myapp_dev_user
      password: auto_generated
    init:
      - compose: deploy/init-compose.yml
    deployment:
      compose: deploy/app-compose.yml
    variables:
      LOG_LEVEL: debug
      CACHE_TTL: 60
      
  staging:
    postgres:
      database: myapp_staging
      port: 5434
      user: myapp_staging_user
      password: auto_generated
    init:
      - compose: deploy/init-compose.yml
    deployment:
      compose: deploy/staging-compose.yml
    variables:
      LOG_LEVEL: info
      CACHE_TTL: 300
      
  production:
    postgres:
      database: myapp_prod
      port: 5435
      user: myapp_prod_user
      password: auto_generated
    init:
      - pod: deploy/migrate-pod.yaml
    deployment:
      pod: deploy/prod-pod.yaml
    variables:
      LOG_LEVEL: warn
      CACHE_TTL: 3600
```

### Standard Deployment Files with Substitution

#### Docker Compose Example
```yaml
# deploy/app-compose.yml
version: '3.8'
services:
  web:
    build: ../containers/web
    ports:
      - "8080:80"
    environment:
      DATABASE_URL: ${POSTSTACK_DATABASE_URL}
      ENVIRONMENT: ${POSTSTACK_ENVIRONMENT}
      LOG_LEVEL: ${LOG_LEVEL}
      CACHE_TTL: ${CACHE_TTL}
    depends_on:
      - worker
      
  worker:
    build: ../containers/worker
    environment:
      DATABASE_URL: ${POSTSTACK_DATABASE_URL}
      ENVIRONMENT: ${POSTSTACK_ENVIRONMENT}
      LOG_LEVEL: ${LOG_LEVEL}
```

#### Podman Pod Example
```yaml
# deploy/prod-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp-production
spec:
  containers:
  - name: web
    image: myapp/web:latest
    ports:
    - containerPort: 80
      hostPort: 80
    env:
    - name: DATABASE_URL
      value: "${POSTSTACK_DATABASE_URL}"
    - name: ENVIRONMENT
      value: "${POSTSTACK_ENVIRONMENT}"
    - name: LOG_LEVEL
      value: "${LOG_LEVEL}"
```

#### Init/Migration Example
```yaml
# deploy/init-compose.yml
version: '3.8'
services:
  migrations:
    build: ../containers/migrations
    environment:
      DATABASE_URL: ${POSTSTACK_DATABASE_URL}
    command: ["npm", "run", "migrate"]
    
  seed-data:
    build: ../containers/seed
    environment:
      DATABASE_URL: ${POSTSTACK_DATABASE_URL}
      ENVIRONMENT: ${POSTSTACK_ENVIRONMENT}
    command: ["npm", "run", "seed"]
    depends_on:
      - migrations
```

## Implementation Details

### 1. Configuration System

#### PoststackConfig Extensions
```python
# config.py additions
class EnvironmentConfig(BaseModel):
    postgres: PostgresConfig
    init: List[DeploymentRef] = []
    deployment: DeploymentRef
    variables: Dict[str, str] = {}

class PostgresConfig(BaseModel):
    database: str
    port: int = 5432
    user: str = "poststack"
    password: str = "auto_generated"
    host: str = "localhost"

class DeploymentRef(BaseModel):
    compose: Optional[str] = None
    pod: Optional[str] = None

class PoststackProjectConfig(BaseModel):
    project: ProjectMeta
    environments: Dict[str, EnvironmentConfig]
```

### 2. Variable Substitution Engine

#### Substitution Variables
Poststack automatically provides:
- `POSTSTACK_DATABASE_URL`: Full postgres connection string
- `POSTSTACK_ENVIRONMENT`: Environment name (dev, staging, production)
- `DB_HOST`: Database host
- `DB_PORT`: Database port
- `DB_NAME`: Database name
- `DB_USER`: Database user
- `DB_PASSWORD`: Database password

Plus user-defined variables from the environment configuration.

#### Template Processing
```python
# substitution.py
class VariableSubstitutor:
    def __init__(self, environment_config: EnvironmentConfig, postgres_info: PostgresInfo):
        self.variables = self._build_variable_map(environment_config, postgres_info)
    
    def process_file(self, file_path: str, output_path: str) -> None:
        """Process template file and write substituted version"""
        
    def dry_run(self, file_path: str) -> Dict[str, str]:
        """Return variables that would be substituted"""
```

### 3. Environment Orchestrator

#### Workflow Implementation
```python
# orchestrator.py
class EnvironmentOrchestrator:
    async def start_environment(self, env_name: str) -> EnvironmentResult:
        """Complete environment startup workflow"""
        1. Validate environment configuration
        2. Start postgres database
        3. Run init phase (migrations, setup)
        4. Validate init phase completion
        5. Run deployment phase
        6. Return status
    
    async def run_init_phase(self, env_config: EnvironmentConfig) -> InitResult:
        """Run initialization containers and validate success"""
        
    async def run_deployment_phase(self, env_config: EnvironmentConfig) -> DeployResult:
        """Run main application deployment"""
```

#### Init Phase Validation
- Each init container must exit with code 0
- If any init container fails, deployment is aborted
- Clear error reporting with container logs
- Support for sequential and parallel init containers

### 4. CLI Commands

#### Environment Management
```bash
# Environment lifecycle
poststack env list                    # Show available environments
poststack env start <env>             # Full environment startup
poststack env stop <env>              # Environment shutdown
poststack env restart <env>           # Restart environment
poststack env status [env]            # Show environment status

# Phase-specific operations
poststack env init <env>              # Run only init phase
poststack env deploy <env>            # Run only deploy phase (assumes init done)

# Debugging and inspection
poststack env dry-run <env>           # Preview variable substitutions
poststack env config <env>            # Show effective configuration
poststack env logs <env> [service]    # Show environment logs
```

#### Database Operations Per Environment
```bash
poststack db migrate <env>            # Run migrations for environment
poststack db rollback <env>           # Rollback migrations
poststack db backup <env>             # Backup environment database
poststack db restore <env> <backup>   # Restore database
poststack db shell <env>              # Connect to environment database
```

### 5. User Experience Workflows

#### Initial Setup
```bash
# Initialize new project
poststack init myapp

# Creates:
# .poststack.yml with dev environment
# deploy/app-compose.yml template
# deploy/init-compose.yml template
# environments/dev.env
```

#### Development Workflow
```bash
# Start development environment
poststack env start dev
# → Creates postgres (myapp_dev on port 5433)
# → Runs init containers (migrations)
# → Starts app containers with injected DATABASE_URL

# Make changes, restart specific services
poststack restart web --env dev
poststack restart worker --env dev

# Check status
poststack env status dev
poststack env logs dev web
```

#### Multi-Environment Deployment
```bash
# Deploy to staging
poststack env start staging
# → Creates postgres (myapp_staging on port 5434)
# → Runs staging-specific init
# → Deploys with staging configuration

# Deploy to production (different deployment format)
poststack env start production
# → Creates postgres (myapp_prod on port 5435)
# → Runs pod-based deployment
# → Uses production variables
```

### 6. Error Handling and Validation

#### Configuration Validation
- Validate .poststack.yml schema
- Check that referenced deployment files exist
- Validate postgres configuration
- Verify environment variable references

#### Runtime Error Handling
- Clear error messages for init failures
- Container log integration for debugging
- Rollback on deployment failures
- Health check integration

#### Init Phase Validation
```bash
# Example init failure handling
poststack env start staging

Init Phase Results:
✅ migrations (exit code: 0, 2.3s)
❌ seed-data (exit code: 1, 0.8s)

Error: Init phase failed. Deployment aborted.

View logs: poststack env logs staging seed-data
Retry init: poststack env init staging
```

### 7. Portability and Exit Strategy

#### Export Functionality
```bash
# Export standard deployment files with variables resolved
poststack env export <env> --format docker-compose
poststack env export <env> --format podman-pod
poststack env export <env> --format env-vars

# Generated files work without poststack
docker-compose -f exported-compose.yml up -d
```

#### Backward Compatibility
- Existing container commands remain functional
- Gradual migration path from container-based to environment-based workflows
- Clear migration documentation

## Success Metrics

### Developer Experience
- **Setup Time**: New project to working database < 2 minutes
- **Environment Parity**: Identical application behavior across environments
- **Error Recovery**: Clear error messages with actionable next steps

### Technical Metrics
- **Postgres Isolation**: Each environment has separate database instance
- **Init Reliability**: 100% validation that init containers succeed
- **Variable Accuracy**: All substitutions resolved correctly

### Adoption Metrics
- **Migration Rate**: Existing poststack users adopt environment management
- **Standard Compliance**: Generated configs work with standard tools
- **Support Reduction**: Fewer configuration-related support requests

## Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Create environment configuration models
- [ ] Implement .poststack.yml parser
- [ ] Add environment validation logic
- [ ] Basic CLI command structure

### Phase 2: Substitution Engine (Week 2)
- [ ] Variable substitution implementation
- [ ] Template processing for compose/pod files
- [ ] Dry-run functionality
- [ ] Variable debugging tools

### Phase 3: Orchestration (Week 3)
- [ ] Environment orchestrator implementation
- [ ] Init phase validation
- [ ] Deployment phase management
- [ ] Postgres integration per environment

### Phase 4: CLI Integration (Week 4)
- [ ] Complete CLI command implementation
- [ ] Error handling and logging
- [ ] Status reporting
- [ ] Environment lifecycle management

### Phase 5: Polish & Documentation (Week 5)
- [ ] Export functionality
- [ ] Example projects
- [ ] Migration guides
- [ ] Comprehensive testing

## Testing Strategy

### Unit Tests
- Configuration parsing and validation
- Variable substitution accuracy
- Environment orchestration logic
- Error handling scenarios

### Integration Tests
- End-to-end environment workflows
- Multi-environment isolation
- Init/deploy phase validation
- Postgres database management

### User Acceptance Tests
- New project setup workflows
- Environment switching scenarios
- Export and portability validation
- Error recovery procedures

## Documentation Updates

### README Updates
- Environment management overview
- Quick start with environments
- Multi-environment workflow examples

### New Documentation
- Environment management guide
- Migration from container commands
- Best practices for environment configuration
- Troubleshooting guide

---

**Document Version**: 1.0  
**Created**: 2025-07-11  
**Status**: Implementation Ready  
**Estimated Effort**: 5 weeks  
**Dependencies**: Existing container lifecycle management system