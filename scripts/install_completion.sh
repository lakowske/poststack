#!/bin/bash
# Quick completion installer for poststack
#
# Usage:
#   ./install_completion.sh         # Auto-detect shell
#   ./install_completion.sh bash    # Install for bash
#   ./install_completion.sh zsh     # Install for zsh
#   ./install_completion.sh fish    # Install for fish

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_INSTALLER="$SCRIPT_DIR/install_completion.py"

# Check if Python installer exists
if [[ ! -f "$PYTHON_INSTALLER" ]]; then
    echo "❌ Python installer not found at: $PYTHON_INSTALLER"
    exit 1
fi

# Pass all arguments to the Python installer
python3 "$PYTHON_INSTALLER" "$@"