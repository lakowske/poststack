#!/bin/bash
set -e

# Liquibase Entrypoint Script for Poststack
# Configures and runs Liquibase operations for schema management

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Function to substitute environment variables in template files
substitute_template() {
    local template_file="$1"
    local output_file="$2"
    
    if [ ! -f "$template_file" ]; then
        log "ERROR: Template file $template_file not found"
        exit 1
    fi
    
    log "Processing template $template_file -> $output_file"
    envsubst < "$template_file" > "$output_file"
}

# Function to validate database connection
validate_database_connection() {
    log "Validating database connection"
    
    if [ -z "$DATABASE_URL" ] && [ -z "$DATABASE_HOST" ]; then
        log "ERROR: DATABASE_URL or DATABASE_HOST must be set"
        exit 1
    fi
    
    # Build connection string if not provided
    if [ -z "$DATABASE_URL" ]; then
        DATABASE_URL="jdbc:postgresql://${DATABASE_HOST}:${DATABASE_PORT:-5432}/${DATABASE_NAME:-poststack}"
        export DATABASE_URL
    fi
    
    # Test connection using psql
    local psql_url
    psql_url=$(echo "$DATABASE_URL" | sed 's/^jdbc:postgresql:\/\//postgresql:\/\//')
    
    if [ -n "$DATABASE_USER" ] && [ -n "$DATABASE_PASSWORD" ]; then
        psql_url="postgresql://${DATABASE_USER}:${DATABASE_PASSWORD}@$(echo "$psql_url" | cut -d'@' -f2)"
    elif [ -n "$DATABASE_USER" ]; then
        psql_url="postgresql://${DATABASE_USER}@$(echo "$psql_url" | cut -d'@' -f2)"
    fi
    
    log "Testing database connection to: $(echo "$psql_url" | sed 's/:.*@/:***@/')"
    
    # Try to connect with a simple query
    if ! psql "$psql_url" -c "SELECT 1;" >/dev/null 2>&1; then
        log "WARNING: Could not connect to database. Proceeding anyway..."
        return 1
    fi
    
    log "Database connection successful"
    return 0
}

# Function to configure Liquibase
configure_liquibase() {
    log "Configuring Liquibase"
    
    # Create logs directory
    mkdir -p /data/liquibase/logs
    
    # Process configuration template
    substitute_template "/data/liquibase/liquibase.properties.template" "/data/liquibase/liquibase.properties"
    
    # Set Liquibase configuration file
    export LIQUIBASE_CONFIG_FILE="/data/liquibase/liquibase.properties"
    
    log "Liquibase configuration complete"
}

# Function to run Liquibase commands
run_liquibase() {
    local command="$1"
    shift
    
    log "Running Liquibase command: $command"
    
    # Ensure configuration is up to date
    configure_liquibase
    
    # Common Liquibase arguments
    local liquibase_args=(
        "--defaults-file=$LIQUIBASE_CONFIG_FILE"
        "--log-level=${LIQUIBASE_LOG_LEVEL:-INFO}"
    )
    
    # Add changelog file if not specified in properties
    if [ -n "$LIQUIBASE_CHANGELOG_FILE" ]; then
        liquibase_args+=("--changelog-file=$LIQUIBASE_CHANGELOG_FILE")
    fi
    
    # Add contexts if specified
    if [ -n "$LIQUIBASE_CONTEXTS" ]; then
        liquibase_args+=("--contexts=$LIQUIBASE_CONTEXTS")
    fi
    
    # Add labels if specified
    if [ -n "$LIQUIBASE_LABELS" ]; then
        liquibase_args+=("--labels=$LIQUIBASE_LABELS")
    fi
    
    # Execute Liquibase command
    case "$command" in
        "update")
            liquibase "${liquibase_args[@]}" update "$@"
            ;;
        "validate")
            liquibase "${liquibase_args[@]}" validate "$@"
            ;;
        "status")
            liquibase "${liquibase_args[@]}" status "$@"
            ;;
        "history")
            liquibase "${liquibase_args[@]}" history "$@"
            ;;
        "rollback")
            if [ $# -eq 0 ]; then
                log "ERROR: rollback requires a tag or count"
                exit 1
            fi
            liquibase "${liquibase_args[@]}" rollback "$@"
            ;;
        "rollback-count")
            if [ $# -eq 0 ]; then
                log "ERROR: rollback-count requires a count"
                exit 1
            fi
            liquibase "${liquibase_args[@]}" rollback-count "$@"
            ;;
        "tag")
            if [ $# -eq 0 ]; then
                log "ERROR: tag requires a tag name"
                exit 1
            fi
            liquibase "${liquibase_args[@]}" tag "$@"
            ;;
        "diff")
            liquibase "${liquibase_args[@]}" diff "$@"
            ;;
        "generate-changelog")
            liquibase "${liquibase_args[@]}" generate-changelog "$@"
            ;;
        "snapshot")
            liquibase "${liquibase_args[@]}" snapshot "$@"
            ;;
        *)
            # Pass through any other Liquibase command
            liquibase "${liquibase_args[@]}" "$command" "$@"
            ;;
    esac
}

# Function to wait for database
wait_for_database() {
    local max_attempts="${DATABASE_WAIT_TIMEOUT:-60}"
    local attempt=1
    
    log "Waiting for database to be ready (max ${max_attempts}s)"
    
    while [ $attempt -le $max_attempts ]; do
        if validate_database_connection; then
            return 0
        fi
        
        log "Database not ready (attempt $attempt/$max_attempts), waiting..."
        sleep 1
        attempt=$((attempt + 1))
    done
    
    log "ERROR: Database not ready after ${max_attempts}s"
    return 1
}

# Function to show help
show_help() {
    cat << EOF
Liquibase Container for Poststack Schema Management

Usage: $0 [COMMAND] [OPTIONS]

Commands:
  update              Apply all pending changes to the database
  validate            Validate the changelog
  status              Show status of database changes
  history             Show change history
  rollback <tag>      Rollback to a specific tag
  rollback-count <n>  Rollback the last n changes
  tag <name>          Tag the current database state
  diff                Show differences between database and changelog
  generate-changelog  Generate changelog from existing database
  snapshot            Create a snapshot of the current database
  wait-and-update     Wait for database then run update
  help                Show this help message

Environment Variables:
  DATABASE_URL        Full JDBC connection string
  DATABASE_HOST       Database hostname (alternative to DATABASE_URL)
  DATABASE_PORT       Database port (default: 5432)
  DATABASE_NAME       Database name (default: poststack)
  DATABASE_USER       Database username
  DATABASE_PASSWORD   Database password
  LIQUIBASE_CONTEXTS  Comma-separated list of contexts
  LIQUIBASE_LABELS    Comma-separated list of labels
  LIQUIBASE_LOG_LEVEL Log level (default: INFO)

Examples:
  # Show current status
  $0 status --verbose
  
  # Apply all changes
  $0 update
  
  # Rollback last 2 changes
  $0 rollback-count 2
  
  # Apply changes for specific context
  LIQUIBASE_CONTEXTS=development $0 update

EOF
}

# Main execution
main() {
    log "Starting Liquibase container entrypoint"
    log "Liquibase version: $(liquibase --version)"
    log "Working directory: $(pwd)"
    
    # Handle different commands
    case "${1:-status}" in
        "help"|"--help"|"-h")
            show_help
            exit 0
            ;;
        "wait-and-update")
            wait_for_database
            run_liquibase "update" "${@:2}"
            ;;
        "bash"|"sh")
            # Interactive shell
            exec "$@"
            ;;
        "psql")
            # Direct PostgreSQL client access
            validate_database_connection
            local psql_url
            psql_url=$(echo "$DATABASE_URL" | sed 's/^jdbc:postgresql:\/\//postgresql:\/\//')
            if [ -n "$DATABASE_USER" ] && [ -n "$DATABASE_PASSWORD" ]; then
                psql_url="postgresql://${DATABASE_USER}:${DATABASE_PASSWORD}@$(echo "$psql_url" | cut -d'@' -f2)"
            elif [ -n "$DATABASE_USER" ]; then
                psql_url="postgresql://${DATABASE_USER}@$(echo "$psql_url" | cut -d'@' -f2)"
            fi
            exec psql "$psql_url" "${@:2}"
            ;;
        *)
            # Liquibase command
            if [ "${DATABASE_WAIT:-false}" = "true" ]; then
                wait_for_database
            else
                validate_database_connection || true
            fi
            run_liquibase "$@"
            ;;
    esac
}

# Run main function
main "$@"