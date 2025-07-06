# Liquibase container for Poststack schema management
# Based on base-debian with Liquibase and PostgreSQL client tools
FROM poststack/base-debian:latest

# Metadata
LABEL maintainer="Poststack Contributors"
LABEL version="1.0.0"
LABEL description="Liquibase schema management container with PostgreSQL support"

# Liquibase version
ENV LIQUIBASE_VERSION=4.24.0

# Install Java (required for Liquibase) and additional tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Java runtime for Liquibase
    openjdk-17-jre-headless \
    # PostgreSQL client tools
    postgresql-client-15 \
    postgresql-client-common \
    # Additional database utilities
    sqlite3 \
    # XML processing tools (for Liquibase changesets)
    xmlstarlet \
    # JSON processing
    jq \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Download and install Liquibase
RUN curl -L "https://github.com/liquibase/liquibase/releases/download/v${LIQUIBASE_VERSION}/liquibase-${LIQUIBASE_VERSION}.tar.gz" \
    -o liquibase.tar.gz && \
    mkdir -p /opt/liquibase && \
    tar -xzf liquibase.tar.gz -C /opt/liquibase && \
    rm liquibase.tar.gz && \
    chmod +x /opt/liquibase/liquibase

# Add liquibase to PATH
ENV PATH="/opt/liquibase:$PATH"

# Install Python packages for database operations
RUN /data/.venv/bin/pip install --no-cache-dir \
    psycopg2-binary \
    sqlalchemy \
    alembic \
    pyyaml \
    jinja2

# Create directories for Liquibase operations
RUN mkdir -p /data/liquibase/changelogs /data/liquibase/scripts /data/liquibase/logs && \
    chown -R certuser:certgroup /data/liquibase

# Copy Liquibase configuration templates and scripts
COPY liquibase.properties.template /data/liquibase/
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Copy sample changelog files
COPY changelogs/ /data/liquibase/changelogs/

# Environment variables for Liquibase
ENV LIQUIBASE_HOME=/opt/liquibase
ENV LIQUIBASE_CHANGELOG_FILE=/data/liquibase/changelogs/master.xml
ENV LIQUIBASE_CONFIG_FILE=/data/liquibase/liquibase.properties

# Database connection environment variables
ENV DATABASE_URL=""
ENV DATABASE_HOST=""
ENV DATABASE_PORT=5432
ENV DATABASE_NAME=""
ENV DATABASE_USER=""
ENV DATABASE_PASSWORD=""

# Liquibase specific settings
ENV LIQUIBASE_CONTEXTS=""
ENV LIQUIBASE_LABELS=""
ENV LIQUIBASE_LOG_LEVEL=INFO

# Create health check script for Liquibase
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Run base health check\n\
/usr/local/bin/health-check.sh\n\
\n\
# Check Java is available\n\
java -version 2>&1 | grep -i "openjdk" || exit 1\n\
\n\
# Check Liquibase is available\n\
liquibase --version || exit 1\n\
\n\
# Check PostgreSQL client is available\n\
psql --version || exit 1\n\
\n\
echo "Liquibase health check passed"\n\
' > /usr/local/bin/liquibase-health-check.sh && \
    chmod +x /usr/local/bin/liquibase-health-check.sh

# Health check for Liquibase
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["/usr/local/bin/liquibase-health-check.sh"]

# Use certuser by default (can be overridden)
USER certuser

# Set working directory
WORKDIR /data/liquibase

# Default entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command - show status
CMD ["status", "--verbose"]