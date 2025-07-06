# Poststack Development Phases

## Overview

This document outlines a phased approach to developing the Poststack project, with each phase building on the previous one and including comprehensive testing before moving forward.

## Phase 1: Project Foundation

### Goals
- Establish Python project structure
- Set up development tooling (ruff, pytest)
- Create basic logging infrastructure
- Implement project configuration

### Deliverables
```
poststack/
├── pyproject.toml          # Project configuration
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Development dependencies
├── .gitignore             # Git ignore patterns
├── .pre-commit-config.yaml # Pre-commit hooks
├── poststack/
│   ├── __init__.py
│   ├── logging_config.py   # Logging setup
│   └── config.py          # Configuration management
├── tests/
│   ├── __init__.py
│   ├── conftest.py        # pytest configuration
│   └── test_config.py     # Basic configuration tests
└── logs/                  # Log directory structure
    ├── containers/
    └── database/
```

### Testing Criteria
- [ ] `ruff check .` passes without errors
- [ ] `ruff format .` runs without issues
- [ ] `pytest tests/` runs successfully
- [ ] Logging configuration works correctly
- [ ] Log directory structure is created properly

### Success Metrics
- All linting and formatting tools work
- Basic test framework is functional
- Logging outputs to both console and files
- Project structure follows Python best practices

---

## Phase 2: CLI Framework

### Goals
- Implement basic CLI argument parsing
- Create command structure for bootstrap tool
- Add help system and error handling
- Integrate logging with CLI operations

### Deliverables
```
poststack/
├── bootstrap.py           # Main CLI entry point
├── cli/
│   ├── __init__.py
│   ├── commands.py        # Command implementations
│   ├── parser.py          # Argument parsing
│   └── utils.py          # CLI utilities
└── tests/
    ├── test_cli.py        # CLI parsing tests
    └── test_commands.py   # Command structure tests
```

### CLI Commands (Stubs)
```bash
# Basic CLI structure with help
python poststack-bootstrap.py --help
python poststack-bootstrap.py build-images --help
python poststack-bootstrap.py verify-db --help
python poststack-bootstrap.py init-schema --help
python poststack-bootstrap.py update-schema --help
python poststack-bootstrap.py setup --help
```

### Testing Criteria
- [ ] All CLI commands parse arguments correctly
- [ ] Help system displays useful information
- [ ] Error handling provides clear messages
- [ ] Logging integrates with CLI operations
- [ ] Command validation works properly

### Success Metrics
- CLI provides intuitive user experience
- All commands have proper help documentation
- Error messages are clear and actionable
- Logging configuration is command-specific

---

## Phase 3: Container Management Library

### Goals
- Implement shared container management functions
- Create container build and runtime management
- Add comprehensive error handling and cleanup
- Establish testing patterns for container operations

### Deliverables
```
poststack/
├── containers.py          # Core container management
├── models.py             # Data models for results
└── tests/
    ├── test_containers.py # Container management tests
    ├── fixtures.py       # Test fixtures
    └── mock_containers.py # Mock container operations
```

### Core Functions
- `ContainerBuilder` class for image building
- `ContainerRunner` class for runtime management
- Build result models and error handling
- Logging integration for subprocess operations

### Testing Criteria
- [ ] Container build functions work with mock containers
- [ ] Runtime management handles startup/shutdown
- [ ] Error handling captures and reports failures
- [ ] Logging captures subprocess output properly
- [ ] Cleanup functions remove test artifacts

### Success Metrics
- Mock container operations complete successfully
- All error conditions are handled gracefully
- Subprocess logging works to dedicated files
- Test isolation and cleanup is effective

---

## Phase 4: Essential Container Build Implementation

### Goals
- Implement container building following [Core Container Architecture](core-container-architecture.md)
- Build common base image with debugging tools from Debian slim
- Create PostgreSQL and Liquibase containers for database scaffolding
- Test multi-stage build process and layer caching

### Architecture Reference
This phase implements the container patterns defined in [docs/core-container-architecture.md](core-container-architecture.md):

- **Base Image Strategy**: Debian bookworm-slim with common tooling
- **Shared Certificate Model**: certgroup/certuser for certificate access
- **Standard Environment Variables**: DOMAIN, LE_EMAIL, CERT_PATH, LOG_LEVEL

### Deliverables
```
containers/
├── base-debian/
│   └── Dockerfile          # Common base with Python, curl, debugging tools
├── postgres/
│   ├── Dockerfile          # FROM base-debian, PostgreSQL + debugging
│   └── entrypoint.sh       # Configuration and startup script
└── liquibase/
    ├── Dockerfile          # FROM base-debian, Liquibase + PostgreSQL client
    └── entrypoint.sh       # Schema management script
```

### Core Functions
- Multi-stage build process (base-debian → service images)
- Real Podman/Docker integration for builds
- Build time measurement and reporting
- Image tagging and metadata management
- Layer caching optimization for faster rebuilds

### Container Specifications

#### Base Debian Image
- **Based on**: debian:bookworm-slim
- **Includes**: Python 3, pip, curl, ca-certificates, bash, debugging tools
- **Users**: certgroup (GID 9999), certuser (UID 9999)
- **Python**: Virtual environment in /data/.venv

#### PostgreSQL Container
- **Based on**: base-debian:latest
- **Includes**: PostgreSQL server, client tools, debugging utilities
- **User**: postgres user added to certgroup
- **Configuration**: Environment-driven via entrypoint script

#### Liquibase Container
- **Based on**: base-debian:latest
- **Includes**: Liquibase, PostgreSQL client, debugging utilities
- **Purpose**: Schema management operations
- **Configuration**: Database URL and changelog path via environment

### Testing Criteria
- [ ] Base Debian image builds successfully with all required tools
- [ ] PostgreSQL container builds from base image
- [ ] Liquibase container builds from base image
- [ ] Build times are measured and reported
- [ ] Layer caching works correctly (rebuild only changed layers)
- [ ] Images are properly tagged and accessible
- [ ] Build failures are handled gracefully
- [ ] Certificate group/user setup works correctly

### Success Metrics
- All 3 images (base + postgres + liquibase) build without errors
- Build performance shows layer caching benefits
- Container build framework follows architecture patterns
- Images include debugging tools for development troubleshooting
- Error handling provides clear diagnostic information

---

## Phase 5: Container Runtime Verification

### Goals
- Implement container runtime testing
- Add health checks for each container type
- Create side effects verification
- Test complete container lifecycle

### Core Functions
- Container startup with proper configuration
- Service-specific health checks (HTTP, TCP, SQL)
- Side effects verification (files, processes, ports)
- Graceful shutdown and cleanup

### Testing Criteria
- [ ] All containers start successfully
- [ ] Health checks pass for each service
- [ ] Expected side effects are verified
- [ ] Containers shut down gracefully
- [ ] Cleanup removes all test artifacts

### Success Metrics
- 100% container runtime verification success
- Health checks complete within expected timeouts
- No resource leaks or leftover containers
- Runtime performance meets expectations

---

## Phase 6: Database Integration

### Goals
- Implement database connectivity and verification using running containers
- Add Liquibase schema management using Liquibase container
- Create database configuration management
- Test database operations with containerized PostgreSQL (requires Phase 5 runtime capabilities)

### Deliverables
```
poststack/
├── database.py           # Database operations
├── schema.py            # Schema management with Liquibase
└── tests/
    ├── test_database.py  # Database connectivity tests
    ├── test_schema.py    # Schema management tests
    └── docker-compose.test.yml # Test database setup
```

### Core Functions
- Database URL parsing and validation
- Connection testing and health checks
- Liquibase container integration (uses Phase 4 built images + Phase 5 runtime)
- Schema initialization and updates

### Testing Criteria
- [ ] Database connectivity verification works with running PostgreSQL container
- [ ] Liquibase operations complete successfully using running container
- [ ] Schema initialization creates expected tables
- [ ] Schema updates apply changes correctly
- [ ] Error handling covers connection failures

### Success Metrics
- Database operations work with running PostgreSQL instance
- Liquibase integration handles schema versioning using running container
- Connection errors provide clear diagnostic information
- Database state is properly managed and cleaned up

---

## Phase 7: CLI Integration and End-to-End Testing

### Goals
- Connect CLI commands to library functions
- Implement full bootstrap workflow
- Add comprehensive end-to-end testing
- Create production-ready CLI tool

### Core Functions
- CLI commands use same functions as tests
- Full setup workflow (build + verify + schema)
- Progress reporting and user feedback
- Comprehensive error handling and recovery

### Testing Criteria
- [ ] CLI build-images command works end-to-end
- [ ] CLI verify-db command validates connectivity
- [ ] CLI init-schema and update-schema work
- [ ] CLI setup command completes full workflow
- [ ] All error conditions are handled properly

### Success Metrics
- CLI tool successfully bootstraps complete environment
- Same code paths used in testing and CLI
- Error handling provides actionable guidance
- Performance meets user expectations

---

## Future Development: Service Container Implementation

After completing Phase 7, subsequent development phases will add the remaining service containers:

### Additional Containers (Future Phases)
```
containers/
├── apache/
│   └── Dockerfile
├── dovecot/
│   └── Dockerfile
├── bind/
│   └── Dockerfile
├── nginx/
│   └── Dockerfile
└── certbot/
    └── Dockerfile
```

### Service Integration
- Each service will follow the established container build patterns
- Runtime testing will use the same framework developed in Phase 6
- CLI integration will extend the bootstrap tool for service management
- Documentation will follow the same standards established in early phases

---

## Phase Testing Strategy

### Per-Phase Testing
Each phase includes:
1. **Unit Tests**: Test individual functions and classes
2. **Integration Tests**: Test component interactions
3. **Performance Tests**: Verify timing and resource usage
4. **Error Handling Tests**: Verify failure scenarios

### Cross-Phase Validation
Before advancing phases:
1. **Regression Testing**: Ensure previous phases still work
2. **Integration Validation**: Test interactions between phases
3. **Documentation Review**: Update docs to match implementation
4. **Code Quality Gates**: Ensure ruff, tests, and coverage pass

### Success Criteria for Phase Advancement
- [ ] All tests pass (unit, integration, performance)
- [ ] Code quality tools pass (ruff check/format)
- [ ] Documentation is updated and accurate
- [ ] No regressions in previous phases
- [ ] Phase deliverables are complete and functional

## Development Commands

### Phase Setup
```bash
# Start new phase
git checkout -b phase-N-description

# Set up development environment
pip install -r requirements-dev.txt
pre-commit install
```

### Testing and Quality
```bash
# Run full test suite
pytest tests/ -v

# Check code quality
ruff check .
ruff format .

# Run performance tests
pytest tests/ -m performance

# Generate coverage report
pytest tests/ --cov=poststack --cov-report=html
```

### Phase Completion
```bash
# Final validation
make test-all  # Run all tests, linting, and checks
make docs      # Generate/update documentation

# Merge phase
git checkout main
git merge phase-N-description
git tag phase-N-complete
```

This phased approach ensures each component is thoroughly tested before building the next layer, reducing integration issues and maintaining high code quality throughout development.