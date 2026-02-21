# venvy

Registry‑first virtual environment manager for Python.

Venvy tracks environments at activation so listing is instant and cleanup is safe. Scanning is optional and only used when you ask for it.

[![PyPI](https://img.shields.io/pypi/v/venvy.svg)](https://pypi.org/project/venvy/)
[![Python](https://img.shields.io/pypi/pyversions/venvy.svg)](https://pypi.org/project/venvy/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## What It Does
- Keeps a local registry (SQLite) of your venvs
- Auto‑registers on activation via shell hook
- Tracks last used, size, packages, and missing paths
- Provides cleanup suggestions with confidence
- Includes a local UI dashboard

## Install
```bash
pip install venvy
```

## Quick Start
```bash
# 1) Install shell hook (auto‑register on activation)
venvy shell-hook --shell powershell >> $PROFILE   # PowerShell
# or
venvy shell-hook >> ~/.bashrc                     # Bash/Zsh

# 2) Activate any venv (auto‑registers)
.\.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate      # macOS/Linux

# 3) View registry
venvy ls
```

## Core Commands
```bash
venvy ls                         # Fast registry list
venvy suggest                    # Fast (registry-based)
venvy suggest --scan             # Deep scan (slow)
venvy register /path/to/venv     # Manual register
venvy refresh --all              # Refresh sizes/packages
venvy cleanup-registry           # Remove missing entries
venvy doctor                     # Diagnose setup
```

## UI
```bash
venvy ui
# opens http://127.0.0.1:5173
```

## Notes
- First activation auto‑registers the venv.
- Every activation updates last‑used.
- If you never activate a venv, use `venvy register` or `venvy scan`.

## Development
```bash
git clone https://github.com/pranavkumaarofficial/venvy
cd venvy
pip install -e ".[dev]"
pytest
```

## License
MIT
