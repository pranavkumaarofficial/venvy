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
    return r'''
# venvy auto-tracking hook for PowerShell
# Add this to your $PROFILE

function Venvy-Track-Activation {
    if ($env:VIRTUAL_ENV) {
        venvy track $env:VIRTUAL_ENV 2>$null
    }
}

# Add to prompt without clobbering the existing prompt
$global:PromptHooks = @()
$global:PromptHooks += { Venvy-Track-Activation }

if (Test-Path function:\prompt) {
    $global:__VenvyOriginalPrompt = (Get-Item function:\prompt).ScriptBlock
} else {
    $global:__VenvyOriginalPrompt = { "PS $($executionContext.SessionState.Path.CurrentLocation)> " }
}

function prompt {
    foreach ($hook in $global:PromptHooks) {
        & $hook
    }
    & $global:__VenvyOriginalPrompt
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


def generate_powershell_pip_wrapper() -> str:
    """Generate PowerShell function that wraps pip for observability."""
    return '''
# venvy pip observer - START
function pip {
    $realPip = (Get-Command pip.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (-not $realPip) { Write-Error "pip.exe not found on PATH"; return 1 }

    $isInstall = ($args.Count -gt 0) -and (($args[0] -eq "install") -or ($args[0] -eq "uninstall"))
    $action = "install"
    if ($args.Count -gt 0 -and $args[0] -eq "uninstall") { $action = "uninstall" }
    $pkgStr = ($args | Select-Object -Skip 1) -join " "

    if ($isInstall -and $env:VIRTUAL_ENV) {
        try { venvy _pip-event --before --action $action --packages "$pkgStr" --json 2>$null | Out-Null } catch {}
    }

    & $realPip @args
    $pipExit = $LASTEXITCODE

    if ($isInstall -and $env:VIRTUAL_ENV) {
        try { venvy _pip-event --after --action $action --exit-code $pipExit --packages "$pkgStr" --json 2>$null | Out-Null } catch {}
    }

    $global:LASTEXITCODE = $pipExit
}
# venvy pip observer - END
'''


def generate_bash_pip_wrapper() -> str:
    """Generate bash/zsh function that wraps pip for observability."""
    return '''
# venvy pip observer - START
pip() {
    local real_pip
    real_pip=$(command -v pip3 2>/dev/null || command -v pip 2>/dev/null)
    if [ -z "$real_pip" ]; then echo "pip not found on PATH" >&2; return 1; fi

    local is_install=0 action="install"
    case "$1" in
        install)   is_install=1; action="install" ;;
        uninstall) is_install=1; action="uninstall" ;;
    esac
    local pkg_str="${@:2}"

    if [ "$is_install" -eq 1 ] && [ -n "$VIRTUAL_ENV" ]; then
        venvy _pip-event --before --action "$action" --packages "$pkg_str" --json 2>/dev/null || true
    fi

    command "$real_pip" "$@"
    local pip_exit=$?

    if [ "$is_install" -eq 1 ] && [ -n "$VIRTUAL_ENV" ]; then
        venvy _pip-event --after --action "$action" --exit-code "$pip_exit" --packages "$pkg_str" --json 2>/dev/null || true
    fi

    return $pip_exit
}
# venvy pip observer - END
'''


def generate_pip_wrapper(shell_type: str = 'powershell') -> str:
    """Generate pip wrapper for the given shell type."""
    if shell_type == 'powershell':
        return generate_powershell_pip_wrapper()
    elif shell_type in ('bash', 'zsh'):
        return generate_bash_pip_wrapper()
    else:
        raise ValueError(f"Unsupported shell type for pip wrapper: {shell_type}")


def get_pip_config_path() -> 'Optional[Path]':
    """Get the user-level pip config file path."""
    import os
    home = Path.home()

    if os.name == 'nt':
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        return Path(appdata) / "pip" / "pip.ini"
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
        return Path(config_home) / "pip" / "pip.conf"


def configure_pip_require_virtualenv() -> dict:
    """Set require-virtualenv = true in pip config. Returns status dict."""
    config_path = get_pip_config_path()
    if not config_path:
        return {"status": "skipped", "detail": "Could not determine pip config path"}

    content = ""
    if config_path.exists():
        content = config_path.read_text(encoding="utf-8", errors="ignore")

    if "require-virtualenv" in content:
        return {"status": "skipped", "detail": "require-virtualenv already set"}

    config_path.parent.mkdir(parents=True, exist_ok=True)

    if "[global]" in content:
        content = content.replace("[global]", "[global]\nrequire-virtualenv = true", 1)
    else:
        content = content + "\n[global]\nrequire-virtualenv = true\n"

    config_path.write_text(content, encoding="utf-8")
    return {"status": "created", "detail": str(config_path)}


def get_shell_config_path() -> Optional[Path]:
    """Detect shell config file path"""
    home = Path.home()

    # Try common shell configs
    configs = [
        home / ".bashrc",
        home / ".zshrc",
        home / ".config" / "fish" / "config.fish",
        home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
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
