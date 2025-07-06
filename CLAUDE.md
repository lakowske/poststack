# Poststack Project Guidelines

## Container Management

**Important**: Always use `poststack` CLI commands for managing containers, databases, and other resources within the poststack project. Avoid direct `podman`, `docker`, or other low-level commands unless specifically debugging or diagnosing issues.

### Preferred Approach

```bash
# Use poststack commands for all operations
poststack database create
poststack database start
poststack database stop
poststack container list
poststack schema init
```

### Debugging Only

```bash
# Only use direct podman/docker commands for debugging
podman ps -a
podman logs container-name
podman inspect container-name
```

### Missing Functionality

If you need to perform an operation that doesn't have a corresponding `poststack` command:

1. **First**: Check if there's an existing command that covers the use case
2. **If missing**: Suggest adding the functionality to the poststack CLI
3. **Document**: Note the gap and propose the command structure

## Missing Functionality Identified

The following commands should be added to provide complete resource management:

```bash
# Volume management (currently missing)
poststack volumes list              # List all poststack-related volumes
poststack volumes cleanup           # Remove unused poststack volumes
poststack volumes prune             # Remove all orphaned volumes

# Enhanced cleanup
poststack cleanup --all             # Full cleanup of containers, volumes, temp files
poststack cleanup --temp-files      # Clean temporary files (like /tmp/poststack_*)

# Database volume management
poststack database cleanup-volumes  # Remove database volumes
poststack database reset            # Full database reset with volume cleanup
```

This approach ensures:

- Consistent user experience
- Proper integration with poststack's configuration and state management
- Better error handling and logging
- Centralized resource management