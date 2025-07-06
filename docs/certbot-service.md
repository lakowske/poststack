# Certificate Generation Service Specification

## Purpose

Define the requirements and implementation for automated certificate generation using Certbot.

## Scope

- Let's Encrypt certificate acquisition
- Self-signed certificate generation
- Certificate renewal automation
- ACME challenge handling
- Certificate storage management

## Requirements

### Functional Requirements

1. Generate Let's Encrypt certificates via HTTP-01 challenge
2. Create self-signed certificates for development
3. Store certificates with proper permissions
4. Support staging certificates for testing
5. Handle certificate renewal

### Non-Functional Requirements

1. Run as non-root user (certuser)
2. Minimal container size (< 100MB)
3. Quick certificate generation
4. Proper error handling and logging
5. Compatible with router port forwarding

## Design Decisions

### Certificate Storage Layout

```
/data/certificates/
├── domain.txt                    # Active domain tracking
├── lab.sethlakowske.com/         # Production certificates
│   ├── fullchain.pem            # Certificate + intermediates
│   ├── privkey.pem              # Private key
│   ├── cert.pem                 # Certificate only
│   └── chain.pem                # Intermediate chain
└── staging-lab.sethlakowske.com/ # Staging certificates
    └── ...
```

### User Permissions Model

- Run certbot as root (required for port binding)
- Change ownership to certuser:certgroup after generation
- Set appropriate file permissions (640 for keys, 644 for certs)

## Implementation

### Containerfile Structure

```dockerfile
FROM base-debian:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    certbot \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Create certificate directory
RUN mkdir -p /data/certificates && \
    chown certuser:certgroup /data/certificates

COPY entrypoint.sh /
# Copy supporting scripts here...
RUN chmod +x /entrypoint.sh
# chmod supporting scripts


EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
```

### Entrypoint Script example

```bash
#!/bin/bash
set -e

# Configuration
CERT_PATH="/data/certificates/${DOMAIN}"
STAGING_PREFIX=""

# Check certificate type
case "${CERT_TYPE}" in
    "letsencrypt")
        # Run generate-letsencrypt.sh

        ;;
    "self-signed")
        # Run generate-self-signed.sh

        ;;
    *)
        echo "Error: CERT_TYPE must be 'letsencrypt' or 'self-signed'"
        exit 1
        ;;
esac
```

### Generate Let's Encrypt script example

```bash
#!/bin/bash

echo "Generating Let's Encrypt certificate for ${DOMAIN}..."

# Validate required variables
if [ -z "$EMAIL" ]; then
    echo "Error: EMAIL is required for Let's Encrypt"
    exit 1
fi

# Check if staging
STAGING_FLAG=""
if [ "${STAGING}" = "true" ]; then
    STAGING_FLAG="--staging"
    STAGING_PREFIX="staging-"
    echo "Using Let's Encrypt staging environment"
fi

# Update certificate path for staging
CERT_PATH="/data/certificates/${STAGING_PREFIX}${DOMAIN}"

# Run certbot
certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    --domains "${DOMAIN}" \
    --cert-path "${CERT_PATH}/cert.pem" \
    --key-path "${CERT_PATH}/privkey.pem" \
    --fullchain-path "${CERT_PATH}/fullchain.pem" \
    --chain-path "${CERT_PATH}/chain.pem" \
    ${STAGING_FLAG}


# Run fix-permissions.sh
```

### Generate self signed certificates script example

```bash
#!/bin/bash

echo "Generating self-signed certificate for ${DOMAIN}..."

# Create directory
mkdir -p "${CERT_PATH}"

# Generate private key and certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "${CERT_PATH}/privkey.pem" \
    -out "${CERT_PATH}/fullchain.pem" \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=${DOMAIN}"

# Copy cert as cert.pem for compatibility
cp "${CERT_PATH}/fullchain.pem" "${CERT_PATH}/cert.pem"

# Create empty chain for compatibility
touch "${CERT_PATH}/chain.pem"

# Run fix-permissions.sh
```

### Fix permissions script

```bash
# Fix certificate permissions

echo "Setting certificate permissions..."

# Change ownership to certuser
chown -R certuser:certgroup "${CERT_PATH}"

# Set file permissions
chmod 644 "${CERT_PATH}/fullchain.pem" || true
chmod 644 "${CERT_PATH}/cert.pem" || true
chmod 644 "${CERT_PATH}/chain.pem" || true
chmod 640 "${CERT_PATH}/privkey.pem"

# Update domain.txt
echo "${DOMAIN}" > /data/certificates/domain.txt
chown certuser:certgroup /data/certificates/domain.txt
```

# Display certificate info script

```bash

echo ""
echo "Certificate generated successfully!"
echo "Domain: ${DOMAIN}"
    echo "Type: ${CERT_TYPE}"
    if [ "${STAGING}" = "true" ]; then
echo "Environment: STAGING"
fi
echo ""
echo "Certificate files:"
ls -la "${CERT_PATH}"
    echo ""
    echo "Certificate details:"
    openssl x509 -in "${CERT_PATH}/fullchain.pem" -text -noout | grep -E "Subject:|Not Before:|Not After:"

```

## ACME Challenge Handling

### HTTP-01 Challenge

```bash
# Certbot standalone mode binds to port 80
# With router forwarding: External:80 → Internal:8080
podman run --user root \
    -p 8080:80 \
    -v certs:/data/certificates \
    -e CERT_TYPE=letsencrypt \
    -e DOMAIN=example.com \
    -e EMAIL=admin@example.com \
    podplay-certbot-debian:latest
```

### DNS-01 Challenge (Future)

```bash
# For wildcard certificates
certbot certonly \
    --dns-cloudflare \
    --dns-cloudflare-credentials /etc/cloudflare.ini \
    --domains "*.example.com"
```

## Environment Variables

### Required Variables

- `CERT_TYPE`: "letsencrypt" or "self-signed"
- `DOMAIN`: Domain name for certificate

### Let's Encrypt Specific

- `EMAIL`: Contact email (required)
- `STAGING`: "true" for staging environment (optional)

### Optional Variables

- `RSA_KEY_SIZE`: Key size (default: 2048)
- `CERT_DAYS`: Days valid for self-signed (default: 365)

## Error Handling

### Common Errors

```bash
# Rate limit exceeded
if [[ $? -eq 1 ]] && grep -q "too many certificates" certbot.log; then
    echo "Error: Let's Encrypt rate limit exceeded"
    echo "Consider using STAGING=true for testing"
    exit 1
fi

# Connection refused (port 80 not accessible)
if [[ $? -eq 1 ]] && grep -q "Connection refused" certbot.log; then
    echo "Error: Cannot bind to port 80"
    echo "Ensure container is run with --user root and proper port mapping"
    exit 1
fi

# Invalid domain
if [[ $? -eq 1 ]] && grep -q "Invalid domain" certbot.log; then
    echo "Error: Domain validation failed"
    echo "Ensure DNS points to this server"
    exit 1
fi
```

## Testing Procedures

### Self-Signed Certificate Test

```bash
podman run --rm \
    -v test-certs:/data/certificates \
    -e CERT_TYPE=self-signed \
    -e DOMAIN=test.local \
    podplay-certbot-debian:latest
```

### Let's Encrypt Staging Test

```bash
podman run --rm --user root \
    -p 8080:80 \
    -v test-certs:/data/certificates \
    -e CERT_TYPE=letsencrypt \
    -e DOMAIN=test.example.com \
    -e EMAIL=test@example.com \
    -e STAGING=true \
    podplay-certbot-debian:latest
```

### Certificate Validation

```bash
# Check certificate details
openssl x509 -in /data/certificates/example.com/fullchain.pem -text -noout

# Verify certificate chain
openssl verify -CAfile /data/certificates/example.com/chain.pem \
    /data/certificates/example.com/cert.pem

# Test TLS connection
openssl s_client -connect example.com:443 \
    -servername example.com \
    -cert /data/certificates/example.com/fullchain.pem
```

## Security Considerations

### Container Execution

- Must run as root for port 80 binding
- Drop privileges after certificate generation
- Use separate container for renewal

### File Security

- Private keys: 640 permissions
- Certificates: 644 permissions
- Ownership: certuser:certgroup

### Network Security

- Only expose port 80 during generation
- Use firewall rules to restrict access
- Consider IP whitelisting for renewal

## Integration Examples

### One-Time Certificate Generation

```bash
# Create certificate volume
podman volume create certs

# Generate certificate
podman run --rm --user root \
    -p 8080:80 \
    -v certs:/data/certificates \
    -e CERT_TYPE=letsencrypt \
    -e DOMAIN=example.com \
    -e EMAIL=admin@example.com \
    podplay-certbot-debian:latest

# Use certificates in services
podman run -d \
    -v certs:/data/certificates:ro \
    podplay-apache-debian:latest
```

### Development Setup

```bash
# Generate self-signed certificate
podman run --rm \
    -v dev-certs:/data/certificates \
    -e CERT_TYPE=self-signed \
    -e DOMAIN=dev.local \
    podplay-certbot-debian:latest
```

## Future Enhancements

1. **Advanced ACME Features**

   - DNS-01 challenge support
   - Multiple domain certificates
   - Wildcard certificate support
   - Alternative ACME providers

2. **Automation**

   - Built-in renewal daemon
   - Webhook notifications
   - Service restart automation
   - Certificate expiry monitoring

3. **Management Interface**
   - Web UI for certificate status
   - API for certificate operations
   - Certificate history tracking
   - Automated backups
