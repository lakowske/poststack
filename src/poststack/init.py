"""
Poststack project initialization functionality.

Provides the init command for making PostgreSQL configuration files
visible and customizable in user projects.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict

import click
import yaml

from .config import PoststackConfig
from .environment.config import EnvironmentConfigParser

logger = logging.getLogger(__name__)


@dataclass
class InitResult:
    """Result of project initialization."""
    success: bool
    postgres_files_created: List[str]
    deploy_files_created: List[str]
    docs_created: List[str]
    files_skipped: List[str]
    validation_errors: List[str]
    config_created: bool = False
    error_message: Optional[str] = None


class InitCommand:
    """Handles project initialization with PostgreSQL configuration files."""
    
    def __init__(self, config: PoststackConfig):
        """Initialize with poststack configuration."""
        self.config = config
        self.poststack_root = Path(__file__).parent.parent.parent
        self.project_root = Path.cwd()
        
    def initialize_project(
        self, 
        include_postgres: bool = True, 
        include_deploy: bool = True, 
        force: bool = False,
        project_name: Optional[str] = None,
        description: Optional[str] = None,
        env_name: str = "dev",
        db_name: Optional[str] = None,
        db_port: int = 5433,
        db_user: Optional[str] = None,
        no_interactive: bool = False
    ) -> InitResult:
        """
        Initialize project with PostgreSQL configuration files.
        
        Args:
            include_postgres: Include PostgreSQL container files
            include_deploy: Include PostgreSQL deployment files
            force: Overwrite existing files
            
        Returns:
            InitResult with details of what was created
        """
        logger.info(f"Initializing project at {self.project_root}")
        
        postgres_files_created = []
        deploy_files_created = []
        docs_created = []
        files_skipped = []
        validation_errors = []
        config_created = False
        
        try:
            # Check for .poststack.yml and create if needed
            poststack_config_path = self.project_root / ".poststack.yml"
            if not poststack_config_path.exists():
                config_created = self._check_or_create_config(
                    project_name=project_name,
                    description=description,
                    env_name=env_name,
                    db_name=db_name,
                    db_port=db_port,
                    db_user=db_user,
                    no_interactive=no_interactive
                )
                if not config_created:
                    # User declined to create config
                    return InitResult(
                        success=False,
                        postgres_files_created=[],
                        deploy_files_created=[],
                        docs_created=[],
                        files_skipped=[],
                        validation_errors=["Configuration creation cancelled by user"],
                        config_created=False,
                        error_message="Project initialization cancelled"
                    )
            
            # Validate project structure
            validation_errors = self._validate_project()
            if validation_errors and not force:
                return InitResult(
                    success=False,
                    postgres_files_created=[],
                    deploy_files_created=[],
                    docs_created=[],
                    files_skipped=[],
                    validation_errors=validation_errors,
                    config_created=config_created,
                    error_message="Project validation failed"
                )
            
            # Create containers/postgres/ files
            if include_postgres:
                postgres_result = self._create_postgres_files(force)
                postgres_files_created.extend(postgres_result["created"])
                files_skipped.extend(postgres_result["skipped"])
            
            # Create deploy/postgres-pod.yaml file
            if include_deploy:
                deploy_result = self._create_deploy_files(force)
                deploy_files_created.extend(deploy_result["created"])
                files_skipped.extend(deploy_result["skipped"])
            
            # Create documentation
            docs_result = self._create_documentation(force)
            docs_created.extend(docs_result["created"])
            files_skipped.extend(docs_result["skipped"])
            
            return InitResult(
                success=True,
                postgres_files_created=postgres_files_created,
                deploy_files_created=deploy_files_created,
                docs_created=docs_created,
                files_skipped=files_skipped,
                validation_errors=[],
                config_created=config_created
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize project: {e}")
            return InitResult(
                success=False,
                postgres_files_created=postgres_files_created,
                deploy_files_created=deploy_files_created,
                docs_created=docs_created,
                files_skipped=files_skipped,
                validation_errors=validation_errors,
                config_created=config_created,
                error_message=str(e)
            )
    
    def _validate_project(self) -> List[str]:
        """Validate that this looks like a valid project for initialization."""
        errors = []
        
        # Check for .poststack.yml
        poststack_config = self.project_root / ".poststack.yml"
        if not poststack_config.exists():
            errors.append("No .poststack.yml found. This doesn't appear to be a poststack project.")
        
        # Check if containers/ directory exists or can be created
        containers_dir = self.project_root / "containers"
        if containers_dir.exists() and not containers_dir.is_dir():
            errors.append("'containers' exists but is not a directory")
        
        # Check if deploy/ directory exists or can be created  
        deploy_dir = self.project_root / "deploy"
        if deploy_dir.exists() and not deploy_dir.is_dir():
            errors.append("'deploy' exists but is not a directory")
            
        return errors
    
    def _create_postgres_files(self, force: bool) -> dict:
        """Create PostgreSQL container files in containers/postgres/."""
        created = []
        skipped = []
        
        # Create containers/postgres directory
        postgres_dir = self.project_root / "containers" / "postgres"
        postgres_dir.mkdir(parents=True, exist_ok=True)
        
        # Files to copy from poststack
        source_dir = self.poststack_root / "containers" / "postgres"
        files_to_copy = [
            "Dockerfile",
            "entrypoint.sh", 
            "postgresql.conf.template",
            "pg_hba.conf.template"
        ]
        
        for filename in files_to_copy:
            source_file = source_dir / filename
            target_file = postgres_dir / filename
            
            if target_file.exists() and not force:
                skipped.append(str(target_file.relative_to(self.project_root)))
                continue
                
            if source_file.exists():
                # Process the file through template substitution
                content = self._process_template_file(source_file, filename)
                
                # Write processed content
                with open(target_file, 'w') as f:
                    f.write(content)
                    
                # Preserve executable permissions for entrypoint.sh
                if filename == "entrypoint.sh":
                    target_file.chmod(0o755)
                    
                created.append(str(target_file.relative_to(self.project_root)))
                logger.info(f"Created {target_file.relative_to(self.project_root)}")
            else:
                logger.warning(f"Source file not found: {source_file}")
        
        return {"created": created, "skipped": skipped}
    
    def _create_deploy_files(self, force: bool) -> dict:
        """Create PostgreSQL deployment files in containers/postgres/."""
        created = []
        skipped = []
        
        # Create postgres-pod.yaml template in containers/postgres/
        postgres_dir = self.project_root / "containers" / "postgres"
        postgres_dir.mkdir(parents=True, exist_ok=True)
        
        pod_file = postgres_dir / "postgres-pod.yaml"
        
        if pod_file.exists() and not force:
            skipped.append(str(pod_file.relative_to(self.project_root)))
        else:
            content = self._generate_postgres_pod_template()
            with open(pod_file, 'w') as f:
                f.write(content)
            created.append(str(pod_file.relative_to(self.project_root)))
            logger.info(f"Created {pod_file.relative_to(self.project_root)}")
        
        return {"created": created, "skipped": skipped}
    
    def _create_documentation(self, force: bool) -> dict:
        """Create documentation files in containers/postgres/docs/."""
        created = []
        skipped = []
        
        # Create docs directory inside containers/postgres/
        docs_dir = self.project_root / "containers" / "postgres" / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        
        # Create PostgreSQL configuration documentation
        doc_file = docs_dir / "postgresql-configuration.md"
        
        if doc_file.exists() and not force:
            skipped.append(str(doc_file.relative_to(self.project_root)))
        else:
            content = self._generate_postgres_documentation()
            with open(doc_file, 'w') as f:
                f.write(content)
            created.append(str(doc_file.relative_to(self.project_root)))
            logger.info(f"Created {doc_file.relative_to(self.project_root)}")
        
        return {"created": created, "skipped": skipped}
    
    def _process_template_file(self, source_file: Path, filename: str) -> str:
        """Process a template file, adjusting paths for user projects."""
        with open(source_file, 'r') as f:
            content = f.read()
        
        # For Dockerfile, adjust COPY paths to be relative to project root
        if filename == "Dockerfile":
            # Change poststack internal paths to user project paths
            content = content.replace(
                "COPY containers/postgres/postgresql.conf.template /data/postgres/config/",
                "COPY containers/postgres/postgresql.conf.template /data/postgres/config/"
            )
            content = content.replace(
                "COPY containers/postgres/pg_hba.conf.template /data/postgres/config/",
                "COPY containers/postgres/pg_hba.conf.template /data/postgres/config/"
            )
            content = content.replace(
                "COPY containers/postgres/entrypoint.sh /usr/local/bin/",
                "COPY containers/postgres/entrypoint.sh /usr/local/bin/"
            )
            
            # Update FROM to use the built base image
            content = content.replace(
                "FROM poststack/base-debian:latest",
                "FROM localhost/poststack/base-debian:latest"
            )
        
        return content
    
    def _generate_postgres_pod_template(self) -> str:
        """Generate a PostgreSQL pod deployment template."""
        return '''# PostgreSQL Pod Deployment Template
# Generated by poststack init command
# 
# This file defines how PostgreSQL is deployed in your environment.
# You can customize resource limits, environment variables, and volumes.

apiVersion: v1
kind: Pod
metadata:
  name: postgres-${ENVIRONMENT}
  labels:
    app: postgres
    environment: ${ENVIRONMENT}
    managed-by: poststack
    component: database
spec:
  # Init containers for volume permissions setup
  initContainers:
  - name: setup-postgres-volumes
    image: localhost/poststack/postgres:latest
    command: ['/bin/bash', '-c']
    args:
    - |
      echo "Setting up PostgreSQL volume permissions..."
      mkdir -p /data/postgres/data /data/postgres/logs /data/postgres/config
      chown -R postgres:postgres /data/postgres
      chmod 750 /data/postgres/data
      chmod 755 /data/postgres/logs /data/postgres/config
      echo "PostgreSQL volume setup complete"
    volumeMounts:
    - name: postgres-data
      mountPath: /data/postgres/data
    - name: postgres-logs
      mountPath: /data/postgres/logs
    - name: postgres-config
      mountPath: /data/postgres/config

  containers:
  - name: postgres
    image: localhost/poststack/postgres:latest
    ports:
    - containerPort: 5432
      hostPort: ${DB_PORT}
      protocol: TCP
    env:
    # Database configuration from poststack environment
    - name: POSTGRES_DB
      value: "${DB_NAME}"
    - name: POSTGRES_USER
      value: "${DB_USER}"
    - name: POSTGRES_PASSWORD
      value: "${DB_PASSWORD}"
    - name: POSTGRES_HOST_AUTH_METHOD
      value: "trust"
    
    # PostgreSQL configuration
    - name: PGDATA
      value: "/data/postgres/data"
    - name: POSTGRES_INITDB_ARGS
      value: "--auth-host=trust --auth-local=peer"
    
    # Poststack environment info
    - name: POSTSTACK_ENVIRONMENT
      value: "${ENVIRONMENT}"
    - name: POSTSTACK_CONFIG_DIR
      value: "/data/config"
    - name: POSTSTACK_CERT_PATH
      value: "/data/certificates"
    - name: POSTSTACK_BASE_DIR
      value: "/data"
    - name: POSTSTACK_LOG_DIR
      value: "/data/logs"
    
    volumeMounts:
    - name: postgres-data
      mountPath: /data/postgres/data
    - name: postgres-logs
      mountPath: /data/postgres/logs
    - name: postgres-config
      mountPath: /data/postgres/config
    
    resources:
      requests:
        memory: "256Mi"
        cpu: "250m"
      limits:
        memory: "1Gi"
        cpu: "1000m"
    
    livenessProbe:
      exec:
        command:
        - "/usr/local/bin/postgres-health-check.sh"
      initialDelaySeconds: 30
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
    
    readinessProbe:
      exec:
        command:
        - "pg_isready"
        - "-h"
        - "localhost"
        - "-p"
        - "5432"
      initialDelaySeconds: 5
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 3

  # Volume Configuration Examples
  volumes:
  # Example 1: emptyDir volumes (data doesn't persist across pod restarts)
  - name: postgres-data
    emptyDir: {}
  - name: postgres-logs
    emptyDir: {}
  - name: postgres-config
    emptyDir: {}

  # Example 2: Named persistent volumes (uncomment and configure as needed)
  # Note: Configure these volumes in your .poststack.yml deployment configuration
  #- name: postgres-data
  #  # Persistent volume - data survives pod restarts and environment stops
  #  persistentVolumeClaim:
  #    claimName: postgres-data-${ENVIRONMENT}
  #- name: postgres-logs
  #  # Named volume for log persistence
  #  hostPath:
  #    path: /var/lib/poststack/logs/${ENVIRONMENT}
  #    type: DirectoryOrCreate

  # Example 3: Host path volumes (uncomment and configure as needed)
  #- name: postgres-data
  #  # Direct host path mount - useful for development
  #  hostPath:
  #    path: /var/lib/poststack/postgres/${ENVIRONMENT}/data
  #    type: DirectoryOrCreate
  
  restartPolicy: Always

# ================================================================
# VOLUME CONFIGURATION GUIDE
# ================================================================
#
# Poststack supports three volume types for container storage:
#
# 1. emptyDir (default):
#    - Temporary storage that doesn't persist across pod restarts
#    - Good for development and testing
#    - Example above shows emptyDir configuration
#
# 2. named:
#    - Persistent named volumes managed by container runtime
#    - Data persists across pod restarts and environment stops
#    - Configure in .poststack.yml:
#      volumes:
#        postgres-data:
#          type: named
#          size: "5Gi"
#          retention: 30
#
# 3. hostPath:
#    - Direct mount from host filesystem
#    - Useful for development or specific deployment needs
#    - Configure in .poststack.yml:
#      volumes:
#        postgres-data:
#          type: hostPath
#          path: "/var/lib/myproject/postgres"
#
# Volume Configuration in .poststack.yml:
# ------------------------------------
# environments:
#   dev:
#     deployments:
#       - pod: deploy/postgres-pod.yaml
#         name: postgres
#         variables:
#           DB_NAME: myapp_dev
#           DB_PORT: "5436"
#         volumes:
#           postgres-data:
#             type: named
#             size: "2Gi"
#           postgres-logs:
#             type: hostPath
#             path: "/var/log/myproject/postgres"
#
# Init Container Benefits:
# ----------------------
# - Ensures correct ownership and permissions before main container starts
# - Works with rootless podman and container security policies
# - No need for host UID/GID mapping or privilege escalation
# - Consistent permissions across different container runtimes
#
# Configuration Notes:
# 
# 1. Environment Variables:
#    Variables like ${DB_NAME} are substituted by poststack
#    at deployment time based on your .poststack.yml configuration.
#
# 2. Volumes:
#    By default, this uses emptyDir volumes which don't persist data.
#    Configure persistent volumes in your .poststack.yml for production.
#
# 3. Resource Limits:
#    Adjust memory and CPU limits based on your workload requirements.
#    The defaults should work for development environments.
#
# 4. Health Checks:
#    The liveness probe ensures PostgreSQL is running and responding.
#    The readiness probe ensures the database is ready to accept connections.
#
# 5. Init Containers:
#    Sets up volume permissions without requiring host UID/GID mapping.
#    This pattern works with all volume types and container runtimes.
#
# 6. Customization:
#    You can modify this file to add additional environment variables,
#    change resource limits, add volumes, or adjust health check settings.
'''
    
    def _generate_postgres_documentation(self) -> str:
        """Generate PostgreSQL configuration documentation."""
        return '''# PostgreSQL Configuration Guide

This document explains the PostgreSQL configuration files created by `poststack init`.

## Files Overview

### containers/postgres/Dockerfile
The PostgreSQL container definition. Based on the poststack base image and includes:
- PostgreSQL 15 with PostGIS extensions
- Performance monitoring tools
- Development and debugging tools
- Health check scripts

**Customization**: You can modify this to add additional PostgreSQL extensions,
tools, or configuration.

### containers/postgres/entrypoint.sh
The container startup script that:
- Processes configuration templates
- Initializes the database if needed
- Sets up users and permissions
- Starts PostgreSQL

**Customization**: Add custom initialization logic, additional users, or
database setup steps.

### containers/postgres/postgresql.conf.template
PostgreSQL server configuration template with environment variable substitution.
Key settings include:
- `listen_addresses` - Network interface configuration
- `port` - PostgreSQL port (usually 5432)
- `max_connections` - Connection limit
- `shared_buffers` - Memory allocation
- `log_statement` - SQL logging level

**Customization**: Tune performance settings, logging, and security options
for your specific workload.

### containers/postgres/pg_hba.conf.template
PostgreSQL client authentication configuration. Controls:
- Which users can connect
- Which databases they can access
- Authentication methods (trust, password, etc.)
- Connection sources (local, network)

**Customization**: Add specific authentication rules for your application
users and security requirements.

### deploy/postgres-pod.yaml
Podman/Kubernetes pod specification for PostgreSQL deployment. Defines:
- Container image and ports
- Environment variables
- Volume mounts
- Resource limits
- Health checks

**Customization**: Adjust resource limits, add persistent volumes, or
modify health check settings.

## Environment Variables

The following environment variables are available for configuration:

### Database Settings
- `DB_NAME` - Database name
- `DB_USER` - Database user
- `DB_PASSWORD` - Database password  
- `DB_PORT` - Database port

### PostgreSQL Specific
- `PGDATA` - PostgreSQL data directory
- `POSTGRES_INITDB_ARGS` - Additional initdb arguments
- `POSTGRES_HOST_AUTH_METHOD` - Default authentication method

### Poststack Environment
- `ENVIRONMENT` - Current environment (dev/staging/prod)
- `POSTSTACK_CONFIG_DIR` - Configuration directory
- `POSTSTACK_CERT_PATH` - SSL certificate path
- `POSTSTACK_LOG_DIR` - Log directory

## Configuration Examples

### Development Environment
```yaml
# .poststack.yml
environments:
  dev:
    postgres:
      database: myapp_dev
      port: 5436
      user: dev_user
      password: auto_generated
```

### Production Tuning
```ini
# postgresql.conf.template - Add these settings
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
```

### Custom Authentication
```ini
# pg_hba.conf.template - Add application user
host myapp_prod app_user 10.0.0.0/8 md5
```

## Building and Deployment

After customizing the configuration:

1. **Build the container**:
   ```bash
   poststack build
   ```

2. **Deploy the environment**:
   ```bash
   poststack env start
   ```

3. **Verify deployment**:
   ```bash
   poststack env status
   ```

## Troubleshooting

### Container Build Issues
- Check Dockerfile syntax and COPY paths
- Ensure all referenced files exist
- Verify base image is available

### Startup Problems
- Check entrypoint.sh for syntax errors
- Verify environment variables are set correctly
- Review PostgreSQL logs for initialization errors

### Connection Issues
- Verify pg_hba.conf allows your connection
- Check postgresql.conf listen_addresses setting
- Ensure port is not blocked by firewall

### Performance Issues
- Tune postgresql.conf memory settings
- Monitor resource usage in pod specification
- Check for slow queries in PostgreSQL logs

## Further Reading

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [Podman Pod Documentation](https://docs.podman.io/en/latest/markdown/podman-pod.1.html)
'''
    
    def _check_or_create_config(
        self,
        project_name: Optional[str],
        description: Optional[str],
        env_name: str,
        db_name: Optional[str],
        db_port: int,
        db_user: Optional[str],
        no_interactive: bool
    ) -> bool:
        """Check for .poststack.yml and create if needed.
        
        Returns:
            True if config was created or user wants to proceed, False if cancelled
        """
        if no_interactive:
            # Non-interactive mode: create with defaults
            config_data = self._build_config_data(
                project_name=project_name,
                description=description,
                env_name=env_name,
                db_name=db_name,
                db_port=db_port,
                db_user=db_user
            )
            self._write_config_file(config_data)
            click.echo("✅ Created .poststack.yml")
            return True
        else:
            # Interactive mode
            if click.confirm("\nNo .poststack.yml found. Would you like to create one?", default=True):
                config_data = self._interactive_config_builder(
                    project_name=project_name,
                    description=description,
                    env_name=env_name,
                    db_name=db_name,
                    db_port=db_port,
                    db_user=db_user
                )
                self._write_config_file(config_data)
                click.echo("✅ Created .poststack.yml")
                return True
            else:
                return False
    
    def _interactive_config_builder(
        self,
        project_name: Optional[str],
        description: Optional[str],
        env_name: str,
        db_name: Optional[str],
        db_port: int,
        db_user: Optional[str]
    ) -> Dict:
        """Build configuration interactively with user prompts."""
        # Get project name
        default_project_name = project_name or self.project_root.name
        project_name = click.prompt(
            "\nProject name",
            default=default_project_name,
            type=str
        )
        
        # Get project description
        default_description = description or f"{project_name} project managed by poststack"
        description = click.prompt(
            "Project description",
            default=default_description,
            type=str
        )
        
        # Get environment name
        env_name = click.prompt(
            "Environment name",
            default=env_name,
            type=str
        )
        
        # Get database configuration
        default_db_name = db_name or f"{project_name}_{env_name}"
        db_name = click.prompt(
            "Database name",
            default=default_db_name,
            type=str
        )
        
        db_port = click.prompt(
            "Database port",
            default=db_port,
            type=int
        )
        
        default_db_user = db_user or f"{project_name}_user"
        db_user = click.prompt(
            "Database user",
            default=default_db_user,
            type=str
        )
        
        return self._build_config_data(
            project_name=project_name,
            description=description,
            env_name=env_name,
            db_name=db_name,
            db_port=db_port,
            db_user=db_user
        )
    
    def _build_config_data(
        self,
        project_name: Optional[str],
        description: Optional[str],
        env_name: str,
        db_name: Optional[str],
        db_port: int,
        db_user: Optional[str]
    ) -> Dict:
        """Build configuration data structure."""
        # Use defaults if not provided
        project_name = project_name or self.project_root.name
        description = description or f"{project_name} project managed by poststack"
        db_name = db_name or f"{project_name}_{env_name}"
        db_user = db_user or f"{project_name}_user"
        
        return {
            "environment": env_name,
            "project": {
                "name": project_name,
                "description": description
            },
            "environments": {
                env_name: {
                    "deployments": [
                        {
                            "pod": "containers/postgres/postgres-pod.yaml",
                            "name": "postgres",
                            "type": "postgres",
                            "variables": {
                                "DB_NAME": db_name,
                                "DB_PORT": str(db_port),
                                "DB_USER": db_user,
                                "DB_PASSWORD": "auto_generated"
                            }
                        }
                    ],
                    "variables": {
                        "LOG_LEVEL": "debug" if env_name == "dev" else "info",
                        "ENVIRONMENT": "development" if env_name == "dev" else env_name
                    },
                    "init": [],
                    "volumes": {}
                }
            }
        }
    
    def _write_config_file(self, config_data: Dict) -> None:
        """Write configuration to .poststack.yml with comments."""
        config_path = self.project_root / ".poststack.yml"
        
        # Generate YAML with comments
        yaml_content = f"""# Poststack project configuration
# Generated by: poststack init

environment: {config_data['environment']}  # Currently selected environment

project:
  name: {config_data['project']['name']}
  description: "{config_data['project']['description']}"

environments:
  {config_data['environment']}:
    # Deployment configuration
    deployments:
      # PostgreSQL deployment
      - pod: containers/postgres/postgres-pod.yaml
        name: postgres
        type: postgres
        variables:
          DB_NAME: {config_data['environments'][config_data['environment']]['deployments'][0]['variables']['DB_NAME']}
          DB_PORT: "{config_data['environments'][config_data['environment']]['deployments'][0]['variables']['DB_PORT']}"
          DB_USER: {config_data['environments'][config_data['environment']]['deployments'][0]['variables']['DB_USER']}
          DB_PASSWORD: auto_generated
      
      # Add your application deployment here
      # - pod: containers/app/app-pod.yaml
      #   name: app
      #   variables:
      #     APP_PORT: "8080"
    
    # Environment-wide variables
    variables:
      LOG_LEVEL: {config_data['environments'][config_data['environment']]['variables']['LOG_LEVEL']}
      ENVIRONMENT: {config_data['environments'][config_data['environment']]['variables']['ENVIRONMENT']}
    
    # Optional: Init containers (migrations, setup)
    init: []
    # Example:
    # - pod: containers/migrations/migrations-pod.yaml
    #   name: migrations
    
    # Volume configuration (if needed)
    volumes: {{}}
    # Example:
    # postgres-data:
    #   type: named
    #   size: "5Gi"
"""
        
        with open(config_path, 'w') as f:
            f.write(yaml_content)
        
        logger.info(f"Created .poststack.yml at {config_path}")