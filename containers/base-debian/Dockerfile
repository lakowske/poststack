# Base Debian container for Poststack services
# Provides common tooling, Python environment, and certificate management setup
FROM debian:bookworm-slim

# Metadata
LABEL maintainer="Poststack Contributors"
LABEL version="1.0.0"
LABEL description="Base Debian container with Python, debugging tools, and certificate management"

# Install essential packages for all services
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core system utilities
    bash \
    curl \
    wget \
    ca-certificates \
    gnupg \
    lsb-release \
    # Python and development tools
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    # Debugging and troubleshooting tools
    procps \
    htop \
    net-tools \
    dnsutils \
    telnet \
    tcpdump \
    strace \
    vim-tiny \
    less \
    # Certificate and crypto tools
    openssl \
    # JSON processing
    jq \
    # Template processing (for envsubst)
    gettext-base \
    # Build tools (may be needed for some Python packages)
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create certificate management users and groups
# certgroup (GID 9999) - shared group for certificate access
# certuser (UID 9999) - owner of certificates, member of certgroup
RUN groupadd -g 9999 certgroup && \
    useradd -u 9999 -g certgroup -m -s /bin/bash certuser

# Create standard directories with proper permissions
RUN mkdir -p /data/certificates /data/logs /data/config && \
    chown -R certuser:certgroup /data && \
    chmod 755 /data && \
    chmod 750 /data/certificates && \
    chmod 755 /data/logs /data/config

# Set up Python virtual environment in /data/.venv
RUN python3 -m venv /data/.venv && \
    chown -R certuser:certgroup /data/.venv

# Update PATH to include virtual environment
ENV PATH="/data/.venv/bin:$PATH"
ENV PYTHONPATH="/data/.venv/lib/python3.11/site-packages"

# Install common Python packages that services might need
RUN /data/.venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /data/.venv/bin/pip install --no-cache-dir \
    requests \
    pyyaml \
    jinja2 \
    cryptography \
    python-dateutil

# Standard environment variables for Poststack services
ENV POSTSTACK_BASE_DIR="/data"
ENV POSTSTACK_CERT_PATH="/data/certificates"
ENV POSTSTACK_LOG_DIR="/data/logs"
ENV POSTSTACK_CONFIG_DIR="/data/config"

# Set timezone to UTC by default
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Create a health check script
RUN echo '#!/bin/bash\n\
# Basic health check for base container\n\
set -e\n\
\n\
# Check Python is available\n\
python3 --version\n\
\n\
# Check virtual environment\n\
[ -d "/data/.venv" ] || exit 1\n\
\n\
# Check certificate directory permissions\n\
[ -d "/data/certificates" ] || exit 1\n\
\n\
# Check certgroup/certuser exist\n\
id certuser || exit 1\n\
getent group certgroup || exit 1\n\
\n\
echo "Base container health check passed"\n\
' > /usr/local/bin/health-check.sh && \
    chmod +x /usr/local/bin/health-check.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["/usr/local/bin/health-check.sh"]

# Default working directory
WORKDIR /data

# Default to bash for interactive use
CMD ["/bin/bash"]