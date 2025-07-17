# Shell Completion for Poststack

Poststack supports shell completion for bash, zsh, and fish shells. This enables tab-completion for commands, subcommands, options, and arguments.

## Features

- **Command completion**: Tab-complete main commands (`db`, `volumes`, `completion`)
- **Subcommand completion**: Tab-complete subcommands (e.g., `db migrate`, `volumes list`)
- **Option completion**: Tab-complete command options (e.g., `--force`, `--timeout`)
- **File path completion**: Smart completion for file and directory arguments
- **Cross-shell support**: Works with bash, zsh, and fish

## Quick Installation

### Method 1: Using the CLI (Recommended)

If you have poststack installed:

```bash
# Auto-detect shell and install completion
poststack completion install

# Install for specific shell
poststack completion install --shell bash
poststack completion install --shell zsh
poststack completion install --shell fish

# Show completion script without installing
poststack completion show --shell bash
```

### Method 2: Using the Standalone Script

If you want to install completion before installing poststack:

```bash
# From the poststack source directory
./scripts/install_completion.sh

# Or specify shell
./scripts/install_completion.sh bash
./scripts/install_completion.sh zsh
./scripts/install_completion.sh fish

# Show script without installing
python3 scripts/install_completion.py --show --shell bash
```

## Manual Installation

### Bash

1. Generate the completion script:
   ```bash
   poststack completion show --shell bash > ~/.local/share/bash-completion/completions/poststack
   ```

2. Reload your shell or run:
   ```bash
   source ~/.bashrc
   ```

### Zsh

1. Generate the completion script:
   ```bash
   mkdir -p ~/.local/share/zsh/site-functions
   poststack completion show --shell zsh > ~/.local/share/zsh/site-functions/_poststack
   ```

2. Make sure your `.zshrc` includes the completion directory:
   ```bash
   # Add to ~/.zshrc if not already present
   fpath=(~/.local/share/zsh/site-functions $fpath)
   autoload -U compinit && compinit
   ```

3. Reload your shell or run:
   ```bash
   source ~/.zshrc
   ```

### Fish

1. Generate the completion script:
   ```bash
   mkdir -p ~/.config/fish/completions
   poststack completion show --shell fish > ~/.config/fish/completions/poststack.fish
   ```

2. Restart your fish shell or run:
   ```bash
   fish
   ```

## Usage Examples

After installation, you can use tab completion:

```bash
# Complete main commands
poststack <TAB>
# Shows: completion db volumes --help --version

# Complete database subcommands
poststack db <TAB>
# Shows: backup create-schema drop-schema migrate migration-status rollback shell test-connection

# Complete options
poststack db migrate --<TAB>
# Shows: --help --target

# Complete file paths
poststack db migrate --migrations-path <TAB>
# Shows available directories and files
```

## Troubleshooting

### Completion Not Working

1. **Check if poststack is in PATH**:
   ```bash
   which poststack
   ```

2. **Verify completion is installed**:
   ```bash
   # For bash
   ls ~/.local/share/bash-completion/completions/poststack
   
   # For zsh
   ls ~/.local/share/zsh/site-functions/_poststack
   
   # For fish
   ls ~/.config/fish/completions/poststack.fish
   ```

3. **Test completion manually**:
   ```bash
   # For bash
   env _POSTSTACK_COMPLETE=bash_complete poststack db
   
   # For zsh
   env _POSTSTACK_COMPLETE=zsh_complete poststack db
   
   # For fish
   env _POSTSTACK_COMPLETE=fish_complete poststack db
   ```

### Permission Issues

If you get permission errors during installation:

```bash
# Install to user directory (recommended)
poststack completion install --path ~/.bash_completion

# Or use the standalone script
python3 scripts/install_completion.py --path ~/.bash_completion
```

### Shell Not Auto-Detected

If shell auto-detection fails:

```bash
# Check your SHELL environment variable
echo $SHELL

# Explicitly specify shell
poststack completion install --shell bash
```

## Advanced Configuration

### Custom Installation Paths

You can install completion scripts to custom locations:

```bash
# Install to custom path
poststack completion install --path /path/to/custom/completion

# For system-wide installation (requires sudo)
sudo poststack completion install --path /etc/bash_completion.d/poststack
```

### Integration with Package Managers

If you're packaging poststack, you can include completion scripts:

```bash
# Generate completion scripts during build
poststack completion show --shell bash > completions/poststack.bash
poststack completion show --shell zsh > completions/_poststack
poststack completion show --shell fish > completions/poststack.fish
```

## Technical Details

Poststack uses Click's built-in completion system, which:

- Supports dynamic completion based on current context
- Handles file and directory completion automatically
- Works across different shell environments
- Provides consistent completion behavior

The completion system integrates with poststack's command structure to provide:

- Command and subcommand completion
- Option name completion
- Context-aware argument completion
- File path completion for appropriate arguments