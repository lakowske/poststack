# PostgreSQL container for Poststack
# Based on base-debian with PostgreSQL server and client tools
FROM poststack/base-debian:latest

# Metadata
LABEL maintainer="Poststack Contributors"
LABEL version="1.0.0"
LABEL description="PostgreSQL server container with debugging tools and certificate access"

# Install PostgreSQL and related packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL server and client
    postgresql-15 \
    postgresql-client-15 \
    postgresql-contrib-15 \
    # Additional database tools
    postgresql-15-postgis-3 \
    postgresql-15-postgis-3-scripts \
    # Backup and restore tools
    postgresql-client-common \
    # Performance monitoring tools
    postgresql-15-pg-stat-kcache \
    # Development and debugging
    postgresql-server-dev-15 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Add postgres user to certgroup for certificate access
RUN usermod -a -G certgroup postgres

# Create PostgreSQL data directory with proper ownership
RUN mkdir -p /data/postgres/data /data/postgres/logs /data/postgres/config && \
    chown -R postgres:postgres /data/postgres && \
    chmod 700 /data/postgres/data

# Install Python packages for PostgreSQL management
RUN /data/.venv/bin/pip install --no-cache-dir \
    psycopg2-binary \
    sqlparse \
    pg_activity

# Copy configuration templates
COPY containers/postgres/postgresql.conf.template /data/postgres/config/
COPY containers/postgres/pg_hba.conf.template /data/postgres/config/

# Copy entrypoint script
COPY containers/postgres/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Add PostgreSQL binaries to PATH
ENV PATH="/usr/lib/postgresql/15/bin:$PATH"

# PostgreSQL specific environment variables
ENV POSTGRES_VERSION=15
ENV PGDATA=/data/postgres/data
ENV POSTGRES_DB=poststack
ENV POSTGRES_USER=poststack
ENV POSTGRES_PASSWORD=
ENV POSTGRES_HOST_AUTH_METHOD=trust
ENV POSTGRES_INITDB_ARGS=""

# Expose PostgreSQL port
EXPOSE 5432

# Create health check script for PostgreSQL
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Run base health check\n\
/usr/local/bin/health-check.sh\n\
\n\
# Check PostgreSQL service\n\
if [ -f "$PGDATA/postmaster.pid" ]; then\n\
    # PostgreSQL is running, check if we can connect\n\
    su - postgres -c "pg_isready -h localhost -p 5432" || exit 1\n\
    echo "PostgreSQL health check passed"\n\
else\n\
    echo "PostgreSQL not running"\n\
    exit 1\n\
fi\n\
' > /usr/local/bin/postgres-health-check.sh && \
    chmod +x /usr/local/bin/postgres-health-check.sh

# Health check for PostgreSQL
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["/usr/local/bin/postgres-health-check.sh"]

# Use postgres user by default
USER postgres

# Set working directory
WORKDIR /data/postgres

# Default entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command
CMD ["postgres"]