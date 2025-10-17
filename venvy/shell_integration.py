"""
Shell integration for automatic venv tracking

Hooks into shell activation to register venvs automatically
"""
from pathlib import Path
from typing import Optional


def generate_bash_hook() -> str:
    """Generate bash/zsh hook to track venv usage"""
    return '''
# venvy auto-tracking hook
# Add this to your ~/.bashrc or ~/.zshrc

# Track venv activation
venvy_track_activation() {
    if [ -n "$VIRTUAL_ENV" ]; then
        venvy track "$VIRTUAL_ENV" 2>/dev/null || true
    fi
}

# Hook into prompt to track active venv
if [ -n "$BASH_VERSION" ]; then
    PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }venvy_track_activation"
elif [ -n "$ZSH_VERSION" ]; then
    precmd_functions+=(venvy_track_activation)
fi

# Enhanced activate function that auto-registers
venvy_activate() {
    if [ -f "$1/bin/activate" ]; then
        source "$1/bin/activate"
        venvy register "$1" --project "$PWD" 2>/dev/null || true
    else
        echo "Error: $1 is not a valid venv"
        return 1
    fi
}

# Alias for convenience
alias vactivate='venvy_activate'
'''


def generate_fish_hook() -> str:
    """Generate fish shell hook"""
    return '''
# venvy auto-tracking hook for fish
# Add this to your ~/.config/fish/config.fish

function venvy_track_activation --on-variable VIRTUAL_ENV
    if test -n "$VIRTUAL_ENV"
        venvy track "$VIRTUAL_ENV" 2>/dev/null
    end
end

function venvy_activate --description "Activate venv and register it"
    if test -f "$argv[1]/bin/activate.fish"
        source "$argv[1]/bin/activate.fish"
        venvy register "$argv[1]" --project (pwd) 2>/dev/null
    else
        echo "Error: $argv[1] is not a valid venv"
        return 1
    end
end

alias vactivate='venvy_activate'
'''


def generate_powershell_hook() -> str:
    """Generate PowerShell hook for Windows"""
    return '''
# venvy auto-tracking hook for PowerShell
# Add this to your $PROFILE

function Venvy-Track-Activation {
    if ($env:VIRTUAL_ENV) {
        venvy track $env:VIRTUAL_ENV 2>$null
    }
}

# Add to prompt
$global:PromptHooks = @()
$global:PromptHooks += { Venvy-Track-Activation }

function prompt {
    foreach ($hook in $global:PromptHooks) {
        & $hook
    }
    # ... rest of your prompt
}

function Venvy-Activate {
    param([string]$VenvPath)

    $ActivateScript = Join-Path $VenvPath "Scripts\\Activate.ps1"
    if (Test-Path $ActivateScript) {
        & $ActivateScript
        venvy register $VenvPath --project $PWD 2>$null
    } else {
        Write-Error "$VenvPath is not a valid venv"
    }
}

Set-Alias vactivate Venvy-Activate
'''


def get_shell_config_path() -> Optional[Path]:
    """Detect shell config file path"""
    home = Path.home()

    # Try common shell configs
    configs = [
        home / ".bashrc",
        home / ".zshrc",
        home / ".config" / "fish" / "config.fish",
        home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]

    for config in configs:
        if config.exists():
            return config

    return None


def install_shell_hook(shell_type: str = 'bash') -> str:
    """
    Generate shell hook content

    Args:
        shell_type: bash, zsh, fish, or powershell

    Returns:
        Hook content to add to shell config
    """
    if shell_type in ('bash', 'zsh'):
        return generate_bash_hook()
    elif shell_type == 'fish':
        return generate_fish_hook()
    elif shell_type == 'powershell':
        return generate_powershell_hook()
    else:
        raise ValueError(f"Unknown shell type: {shell_type}")
