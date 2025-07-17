"""
Command-line interface for Poststack (Database-Focused)

Provides database operations, schema management, and migrations.
Orchestration is now handled by Docker Compose.
"""

import sys
from pathlib import Path
from typing import Optional

import click

from .config import PoststackConfig, load_config
from .database import database
from .volumes import volumes
from .logging_config import setup_logging

# Global configuration object
config: Optional[PoststackConfig] = None


@click.group()
@click.option(
    "--config-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    help="Set logging level",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.option(
    "--log-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for log files",
)
@click.version_option()
@click.pass_context
def cli(
    ctx: click.Context,
    config_file: Optional[Path],
    log_level: str,
    verbose: bool,
    log_dir: Optional[Path],
) -> None:
    """
    Poststack: PostgreSQL database and schema migration management

    Focused on database operations and schema migrations.
    For container orchestration, use Docker Compose.
    """
    global config

    # Load configuration with defaults
    config = load_config(
        config_file=str(config_file) if config_file else None,
        cli_overrides={
            k: v for k, v in {
                "log_level": log_level.upper(),
                "verbose": verbose,
                "log_dir": str(log_dir) if log_dir else None,
            }.items() if v is not None
        },
    )

    # Setup logging based on loaded configuration
    setup_logging(
        log_dir=config.log_dir,
        verbose=config.verbose,
        log_level=config.log_level,
    )

    # Store config in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


# Completion support
@cli.group()
def completion() -> None:
    """Shell completion management."""
    pass


@completion.command("install")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"], case_sensitive=False),
    help="Shell type (auto-detected if not specified)",
)
@click.option(
    "--path", 
    type=click.Path(path_type=Path),
    help="Custom installation path for completion script",
)
def install_completion(shell: Optional[str], path: Optional[Path]) -> None:
    """Install shell completion for poststack."""
    import os
    import shutil
    from pathlib import Path
    
    # Auto-detect shell if not specified
    if not shell:
        shell_env = os.environ.get("SHELL", "").lower()
        if "bash" in shell_env:
            shell = "bash"
        elif "zsh" in shell_env:
            shell = "zsh"
        elif "fish" in shell_env:
            shell = "fish"
        else:
            click.echo("❌ Could not auto-detect shell. Please specify with --shell", err=True)
            return
    
    shell = shell.lower()
    
    # Generate completion script
    completion_script = get_completion_script(shell)
    if not completion_script:
        click.echo(f"❌ Completion not supported for {shell}", err=True)
        return
    
    # Determine installation path
    if path:
        install_path = path
    else:
        install_path = get_default_completion_path(shell)
        if not install_path:
            click.echo(f"❌ Could not determine completion path for {shell}", err=True)
            return
    
    # Create directory if it doesn't exist
    install_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write completion script
    try:
        install_path.write_text(completion_script)
        click.echo(f"✅ Completion script installed to: {install_path}")
        
        # Provide reload instructions
        if shell == "bash":
            click.echo("💡 Run 'source ~/.bashrc' or restart your shell to enable completion")
        elif shell == "zsh":
            click.echo("💡 Run 'source ~/.zshrc' or restart your shell to enable completion")
        elif shell == "fish":
            click.echo("💡 Restart your shell or run 'fish' to enable completion")
            
    except Exception as e:
        click.echo(f"❌ Failed to install completion: {e}", err=True)


@completion.command("show")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"], case_sensitive=False),
    default="bash",
    help="Shell type to show completion script for",
)
def show_completion(shell: str) -> None:
    """Show the completion script for manual installation."""
    completion_script = get_completion_script(shell.lower())
    if completion_script:
        click.echo(completion_script)
    else:
        click.echo(f"❌ Completion not supported for {shell}", err=True)


def get_completion_script(shell: str) -> Optional[str]:
    """Generate completion script for the specified shell."""
    if shell == "bash":
        return """
# Poststack bash completion
_poststack_completion() {
    local IFS=$'\\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD _POSTSTACK_COMPLETE=bash_complete $1)

    for completion in $response; do
        IFS=',' read type value <<< "$completion"

        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=($value)
        fi
    done

    return 0
}

complete -o nosort -F _poststack_completion poststack
"""
    elif shell == "zsh":
        return """
# Poststack zsh completion
#compdef poststack

_poststack_completion() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[poststack] )) && return 1

    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) _POSTSTACK_COMPLETE=zsh_complete poststack)}")

    for type_and_line in $response; do
        if [[ "$type_and_line" =~ '^([^,]*),(.*)$' ]]; then
            local type=$match[1]
            local line=$match[2]

            if [[ "$type" == "plain" ]]; then
                if [[ "$line" =~ '^([^\t]*)\t?(.*)$' ]]; then
                    local value=$match[1]
                    local description=$match[2]
                    completions_with_descriptions+=("$value:$description")
                else
                    completions+=("$line")
                fi
            elif [[ "$type" == "dir" ]]; then
                _path_files -/
            elif [[ "$type" == "file" ]]; then
                _path_files -f
            fi
        fi
    done

    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi

    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}

compdef _poststack_completion poststack
"""
    elif shell == "fish":
        return """
# Poststack fish completion
function __fish_poststack_complete
    set -l response (env _POSTSTACK_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) poststack)

    for completion in $response
        set -l metadata (string split "," $completion)

        if test $metadata[1] = "dir"
            __fish_complete_directories $metadata[2]
        else if test $metadata[1] = "file"
            __fish_complete_path $metadata[2]
        else if test $metadata[1] = "plain"
            echo $metadata[2]
        end
    end
end

complete --no-files --command poststack --arguments "(__fish_poststack_complete)"
"""
    return None


def get_default_completion_path(shell: str) -> Optional[Path]:
    """Get the default completion installation path for the specified shell."""
    home = Path.home()
    
    if shell == "bash":
        # Try bash completion directories in order of preference
        bash_completion_dirs = [
            home / ".local/share/bash-completion/completions",
            home / ".bash_completion.d",
            Path("/usr/local/etc/bash_completion.d"),
            Path("/etc/bash_completion.d"),
        ]
        
        for comp_dir in bash_completion_dirs:
            if comp_dir.parent.exists() or comp_dir == bash_completion_dirs[0]:
                return comp_dir / "poststack"
        
    elif shell == "zsh":
        # Try zsh completion directories
        zsh_completion_dirs = [
            home / ".local/share/zsh/site-functions",
            home / ".zsh/completions",
        ]
        
        for comp_dir in zsh_completion_dirs:
            if comp_dir.parent.exists() or comp_dir == zsh_completion_dirs[0]:
                return comp_dir / "_poststack"
                
    elif shell == "fish":
        # Fish completion directory
        fish_dir = home / ".config/fish/completions"
        return fish_dir / "poststack.fish"
    
    return None


# Database operations (core functionality)
cli.add_command(database, name="db")
cli.add_command(volumes, name="volumes")
cli.add_command(completion)


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()