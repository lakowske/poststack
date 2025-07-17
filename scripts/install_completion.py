#!/usr/bin/env python3
"""
Standalone script to install poststack shell completion.

This script can be used to install shell completion for poststack
without requiring the full poststack package to be installed.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


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


def main():
    """Main entry point for the completion installer."""
    parser = argparse.ArgumentParser(
        description="Install shell completion for poststack",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Auto-detect shell and install
  %(prog)s --shell bash       # Install bash completion
  %(prog)s --shell zsh        # Install zsh completion
  %(prog)s --show             # Show completion script without installing
  %(prog)s --path ~/.bashrc   # Install to custom path
        """
    )
    
    parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish"],
        help="Shell type (auto-detected if not specified)"
    )
    
    parser.add_argument(
        "--path",
        type=Path,
        help="Custom installation path for completion script"
    )
    
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show completion script without installing"
    )
    
    args = parser.parse_args()
    
    # Auto-detect shell if not specified
    shell = args.shell
    if not shell:
        shell_env = os.environ.get("SHELL", "").lower()
        if "bash" in shell_env:
            shell = "bash"
        elif "zsh" in shell_env:
            shell = "zsh"
        elif "fish" in shell_env:
            shell = "fish"
        else:
            print("❌ Could not auto-detect shell. Please specify with --shell", file=sys.stderr)
            return 1
    
    shell = shell.lower()
    
    # Generate completion script
    completion_script = get_completion_script(shell)
    if not completion_script:
        print(f"❌ Completion not supported for {shell}", file=sys.stderr)
        return 1
    
    # Show script if requested
    if args.show:
        print(completion_script)
        return 0
    
    # Determine installation path
    if args.path:
        install_path = args.path
    else:
        install_path = get_default_completion_path(shell)
        if not install_path:
            print(f"❌ Could not determine completion path for {shell}", file=sys.stderr)
            return 1
    
    # Create directory if it doesn't exist
    install_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write completion script
    try:
        install_path.write_text(completion_script)
        print(f"✅ Completion script installed to: {install_path}")
        
        # Provide reload instructions
        if shell == "bash":
            print("💡 Run 'source ~/.bashrc' or restart your shell to enable completion")
        elif shell == "zsh":
            print("💡 Run 'source ~/.zshrc' or restart your shell to enable completion")
        elif shell == "fish":
            print("💡 Restart your shell or run 'fish' to enable completion")
            
    except Exception as e:
        print(f"❌ Failed to install completion: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())