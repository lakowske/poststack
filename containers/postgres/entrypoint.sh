#!/bin/bash
set -e

# PostgreSQL Entrypoint Script for Poststack
# Configures and starts PostgreSQL with environment-driven settings

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

# Function to initialize PostgreSQL database
init_database() {
    log "Initializing PostgreSQL database in $PGDATA"
    
    # Create data directory if it doesn't exist
    if [ ! -d "$PGDATA" ]; then
        mkdir -p "$PGDATA"
        chown postgres:postgres "$PGDATA"
        chmod 700 "$PGDATA"
    fi
    
    # Initialize database if not already done
    if [ ! -f "$PGDATA/PG_VERSION" ]; then
        log "Running initdb to create database cluster"
        initdb -D "$PGDATA" --auth-host=trust --auth-local=peer ${POSTGRES_INITDB_ARGS}
        
        # Set up initial database and user if specified
        if [ -n "$POSTGRES_DB" ] && [ "$POSTGRES_DB" != "postgres" ]; then
            log "Creating database: $POSTGRES_DB"
            pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w start
            createdb "$POSTGRES_DB"
            pg_ctl -D "$PGDATA" -m fast -w stop
        fi
        
        if [ -n "$POSTGRES_USER" ] && [ "$POSTGRES_USER" != "postgres" ]; then
            log "Creating user: $POSTGRES_USER"
            pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w start
            
            if [ -n "$POSTGRES_PASSWORD" ]; then
                createuser -s "$POSTGRES_USER"
                psql -v ON_ERROR_STOP=1 --username postgres <<-EOSQL
                    ALTER USER $POSTGRES_USER PASSWORD '$POSTGRES_PASSWORD';
EOSQL
            else
                createuser -s "$POSTGRES_USER"
            fi
            
            # Grant privileges on database if it exists
            if [ -n "$POSTGRES_DB" ] && [ "$POSTGRES_DB" != "postgres" ]; then
                psql -v ON_ERROR_STOP=1 --username postgres <<-EOSQL
                    GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB TO $POSTGRES_USER;
EOSQL
            fi
            
            pg_ctl -D "$PGDATA" -m fast -w stop
        fi
    fi
}

# Function to configure PostgreSQL
configure_postgresql() {
    log "Configuring PostgreSQL"
    
    # Create log directory if it doesn't exist
    mkdir -p /data/postgres/logs
    chown postgres:postgres /data/postgres/logs
    chmod 755 /data/postgres/logs
    
    # Process configuration templates
    substitute_template "/data/postgres/config/postgresql.conf.template" "$PGDATA/postgresql.conf"
    substitute_template "/data/postgres/config/pg_hba.conf.template" "$PGDATA/pg_hba.conf"
    
    # Create archive directory if archive mode is enabled
    if [ "${POSTGRES_ARCHIVE_MODE:-off}" = "on" ]; then
        mkdir -p /data/postgres/archive
        chown postgres:postgres /data/postgres/archive
        chmod 700 /data/postgres/archive
    fi
    
    # Check for SSL certificates and configure if available
    if [ -f "/data/certificates/server.crt" ] && [ -f "/data/certificates/server.key" ]; then
        log "SSL certificates found, enabling SSL"
        export POSTGRES_SSL=on
        export POSTGRES_SSL_ENABLED=1
        
        # Copy certificates to PostgreSQL data directory with proper permissions
        cp /data/certificates/server.crt "$PGDATA/"
        cp /data/certificates/server.key "$PGDATA/"
        [ -f "/data/certificates/ca.crt" ] && cp /data/certificates/ca.crt "$PGDATA/"
        
        chown postgres:postgres "$PGDATA"/*.crt "$PGDATA"/*.key 2>/dev/null || true
        chmod 600 "$PGDATA"/*.key 2>/dev/null || true
        chmod 644 "$PGDATA"/*.crt 2>/dev/null || true
    else
        log "No SSL certificates found, SSL disabled"
        export POSTGRES_SSL=off
        unset POSTGRES_SSL_ENABLED
    fi
    
    # Reprocess templates with updated SSL settings
    substitute_template "/data/postgres/config/postgresql.conf.template" "$PGDATA/postgresql.conf"
    substitute_template "/data/postgres/config/pg_hba.conf.template" "$PGDATA/pg_hba.conf"
}

# Function to start PostgreSQL
start_postgresql() {
    log "Starting PostgreSQL server"
    
    # Ensure we're running as postgres user
    if [ "$(id -u)" != "$(id -u postgres)" ]; then
        log "ERROR: Must run as postgres user"
        exit 1
    fi
    
    # Start PostgreSQL
    exec postgres -D "$PGDATA"
}

# Function to run custom SQL scripts
run_init_scripts() {
    if [ -d "/docker-entrypoint-initdb.d" ]; then
        log "Running initialization scripts"
        
        # Start PostgreSQL temporarily for init scripts
        pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w start
        
        for f in /docker-entrypoint-initdb.d/*; do
            case "$f" in
                *.sh)
                    log "Running $f"
                    bash "$f"
                    ;;
                *.sql)
                    log "Running $f"
                    psql -v ON_ERROR_STOP=1 --username postgres --dbname "$POSTGRES_DB" -f "$f"
                    ;;
                *.sql.gz)
                    log "Running $f"
                    gunzip -c "$f" | psql -v ON_ERROR_STOP=1 --username postgres --dbname "$POSTGRES_DB"
                    ;;
                *)
                    log "Ignoring $f"
                    ;;
            esac
        done
        
        pg_ctl -D "$PGDATA" -m fast -w stop
    fi
}

# Main execution
main() {
    log "Starting PostgreSQL container entrypoint"
    log "PostgreSQL version: $(postgres --version)"
    log "Data directory: $PGDATA"
    log "Database: ${POSTGRES_DB:-postgres}"
    log "User: ${POSTGRES_USER:-postgres}"
    
    # Validate environment
    if [ -z "$PGDATA" ]; then
        log "ERROR: PGDATA environment variable is required"
        exit 1
    fi
    
    # Set default values for template substitution
    export POSTGRES_MAX_CONNECTIONS="${POSTGRES_MAX_CONNECTIONS:-100}"
    export POSTGRES_SHARED_BUFFERS="${POSTGRES_SHARED_BUFFERS:-128MB}"
    export POSTGRES_EFFECTIVE_CACHE_SIZE="${POSTGRES_EFFECTIVE_CACHE_SIZE:-1GB}"
    export POSTGRES_LOG_MIN_DURATION="${POSTGRES_LOG_MIN_DURATION:-1000}"
    export POSTGRES_SSL_MODE="${POSTGRES_SSL_MODE:-off}"
    export POSTGRES_SSL_CERT_FILE="${POSTGRES_SSL_CERT_FILE:-}"
    export POSTGRES_SSL_KEY_FILE="${POSTGRES_SSL_KEY_FILE:-}"
    export POSTGRES_ARCHIVE_MODE="${POSTGRES_ARCHIVE_MODE:-off}"
    export POSTGRES_ARCHIVE_COMMAND="${POSTGRES_ARCHIVE_COMMAND:-test ! -f /data/postgres/archive/%f && cp %p /data/postgres/archive/%f}"
    export TZ="${TZ:-UTC}"
    export POSTGRES_LOCAL_AUTH_METHOD="${POSTGRES_LOCAL_AUTH_METHOD:-trust}"
    export POSTGRES_HOST_AUTH_METHOD="${POSTGRES_HOST_AUTH_METHOD:-trust}"
    export POSTGRES_CONTAINER_AUTH_METHOD="${POSTGRES_CONTAINER_AUTH_METHOD:-trust}"
    
    # Initialize database if needed
    init_database
    
    # Configure PostgreSQL
    configure_postgresql
    
    # Run initialization scripts
    run_init_scripts
    
    # Handle different commands
    case "${1:-postgres}" in
        postgres)
            start_postgresql
            ;;
        psql)
            exec psql "$@"
            ;;
        pg_dump)
            exec pg_dump "$@"
            ;;
        pg_restore)
            exec pg_restore "$@"
            ;;
        *)
            # Run arbitrary command
            exec "$@"
            ;;
    esac
}

# Run main function
main "$@"