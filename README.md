# venvy - Virtual Environment Manager

**Track and manage Python virtual environments without the slow scanning**

[![PyPI](https://img.shields.io/pypi/v/venvy.svg)](https://pypi.org/project/venvy/)
[![Python](https://img.shields.io/pypi/pyversions/venvy.svg)](https://pypi.org/project/venvy/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## The Problem

**Venvs are scattered everywhere** - in project folders, home directory, nested in subdirectories. You create them, forget about them, and they eat up GBs of disk space.

**Finding them is painfully slow** - Scanning your filesystem to find all venvs takes minutes.

**No central tracking** - You have no idea how many venvs you have, which ones are old, or which projects they belong to.

## The Solution

**venvy uses a registry database** - Track venvs when they're created/used instead of scanning the filesystem every time.

- ✅ **INSTANT lookups** - Query SQLite database instead of scanning directories
- ✅ **Auto-tracking** - Shell integration automatically registers venvs when activated
- ✅ **Smart cleanup** - Know which venvs are safe to delete
- ✅ **Project linking** - See which venv belongs to which project

## Installation

```bash
pip install venvy
```

## Quick Start

```bash
# Register your current venv
venvy register .venv

# List all registered venvs (INSTANT - no scanning!)
venvy ls

# Show statistics
venvy stats

# See currently active venv
venvy current

# Find and register all venvs (one-time scan)
venvy scan --path ~/projects

# Clean up old venvs
venvy cleanup --days 90
```

## Why venvy?

### Before venvy:
```bash
# Find all venvs: scan entire filesystem (2-5 minutes)
find ~ -name "pyvenv.cfg" -type f  # painful...

# No idea which venvs are safe to delete
# No tracking of when venvs were last used
# Can't link venvs to projects
```

### With venvy:
```bash
# List all venvs: query database (instant)
venvy ls

# See last used dates, sizes, project links
# Auto-track usage with shell integration
# Smart cleanup suggestions
```

## Core Concepts

### Registry-Based Tracking

Instead of scanning directories (slow), venvy maintains a SQLite registry of your venvs:

```
~/.venvy/venv_registry.db
├─ venv paths
├─ project associations
├─ last used timestamps
├─ Python versions
└─ sizes & package counts
```

### Two-Phase Approach

1. **Register** (one-time or auto): Add venvs to registry
2. **Query** (instant): List/manage from database

## Commands

### `venvy ls` - List Registered Venvs

**FAST** - Reads from database, no filesystem scanning.

```bash
venvy ls                    # Show all registered venvs
venvy ls --sort recent      # Sort by last used
venvy ls --sort size        # Sort by size
venvy ls --format json      # JSON output
```

Example output:
```
         Registered Virtual Environments (5 total)
+-----------+--------+----------+--------+-----------+-----------------+
| Name      | Python | Packages | Size   | Last Used | Project         |
|-----------+--------+----------+--------+-----------+-----------------|
| myproject | 3.11.2 |       45 | 123.4MB| 2d ago    | ~/code/myproject|
| backend   | 3.9.7  |       67 | 234.5MB| 5d ago    | ~/work/backend  |
| old-proj  | 3.8.0  |       12 |  45.2MB| 120d ago  | ~/old/project   |
+-----------+--------+----------+--------+-----------+-----------------+

Total: 5 venvs, 403.1MB, 124 packages
```

### `venvy register` - Register a Venv

Add a venv to the registry:

```bash
venvy register .venv                           # Register current dir's venv
venvy register /path/to/venv                   # Register specific venv
venvy register .venv --project ~/myproject     # Link to project
venvy register .venv --name myapp              # Custom name
```

**Auto-register**: Install shell hook to auto-register on activation (see below).

### `venvy scan` - Find & Register Existing Venvs

**SLOW** - Only run once or when needed:

```bash
venvy scan                  # Scan current directory
venvy scan --path ~/projects# Scan specific path
venvy scan --home           # Scan home directory (slow!)
venvy scan --depth 5        # Max depth to search
```

After scanning once, use `venvy ls` for instant results.

### `venvy current` - Show Active Venv

```bash
venvy current
# Output:
# Active venv: /home/user/myproject/.venv
#   Name: myproject
#   Python: 3.11.2
#   Project: /home/user/myproject
```

### `venvy stats` - Show Statistics

```bash
venvy stats
# Output:
# Virtual Environment Statistics
#
# Total Environments: 12
# Total Disk Space:   1.2 GB
# Total Packages:     456
#
# Unused 30+ days:    3
# Unused 90+ days:    7
```

### `venvy cleanup` - Remove Old Venvs

```bash
venvy cleanup                   # Remove venvs unused for 90+ days
venvy cleanup --days 30         # Unused for 30+ days
venvy cleanup --dry-run         # See what would be removed
```

Example:
```bash
$ venvy cleanup --days 90

Found 3 venv(s) unused for 90+ days:

  old-project - last used 120 days ago (45.2MB)
  test-env - last used 150 days ago (23.1MB)
  abandoned - last used 200 days ago (67.8MB)

Total space: 136.1MB

Remove 3 venv(s)? [y/N]: y

  + Removed old-project
  + Removed test-env
  + Removed abandoned

Removed 3/3 venvs (136.1MB freed)
```

### `venvy shell-hook` - Auto-Tracking

Generate shell integration for automatic tracking:

```bash
# Bash/Zsh
venvy shell-hook >> ~/.bashrc
source ~/.bashrc

# Fish
venvy shell-hook --shell fish >> ~/.config/fish/config.fish

# PowerShell
venvy shell-hook --shell powershell >> $PROFILE
```

After installing, venvs are automatically registered when you activate them!

## Workflow Examples

### New Project Setup

```bash
# Create project and venv
mkdir myproject && cd myproject
python -m venv .venv
source .venv/bin/activate

# If shell hook installed, it's auto-registered!
# Otherwise:
venvy register .venv
```

### Spring Cleaning

```bash
# See all venvs
venvy ls --sort size

# Check statistics
venvy stats

# Remove old/unused venvs
venvy cleanup --days 60 --dry-run  # Preview
venvy cleanup --days 60            # Actually remove
```

### Project Migration

```bash
# Find venv for old project
venvy ls | grep oldproject

# See details
venvy current  # if activated

# Link to new location
venvy register .venv --project ~/new/location
```

## Technical Details

### Registry Database

Location: `~/.venvy/venv_registry.db` (SQLite)

Schema:
```sql
CREATE TABLE venvs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT UNIQUE NOT NULL,
    project_path TEXT,
    python_version TEXT,
    created_at TEXT,
    last_used_at TEXT,
    size_mb REAL,
    package_count INTEGER,
    notes TEXT
);
```

### Performance

| Operation | Time |
|-----------|------|
| `venvy ls` | < 10ms |
| `venvy register` | ~ 100ms |
| `venvy scan ~/projects` | Varies (filesystem-dependent) |
| `venvy stats` | < 10ms |

### Cross-Platform

- ✅ Linux
- ✅ macOS
- ✅ Windows

Handles platform-specific venv structures automatically.

## Comparison with Other Tools

| Tool | Tracks Venvs | Fast Lookups | Auto-Register | Cleanup |
|------|--------------|--------------|---------------|---------|
| **venvy** | ✅ | ✅ (database) | ✅ (shell hook) | ✅ |
| virtualenvwrapper | ✅ | ✅ | ❌ | ❌ |
| pyenv | ❌ | N/A | ❌ | ❌ |
| conda | ✅ (conda only) | ✅ | ❌ | ❌ |

**venvy advantage**: Works with ANY venv (venv, virtualenv, conda) and provides centralized tracking + cleanup.

## FAQ

**Q: Does this replace virtualenv/venv?**
A: No! venvy works WITH your existing venv tools. It just tracks and manages them better.

**Q: Will it slow down my shell?**
A: No. The shell hook only runs when you activate a venv, and registration takes ~100ms.

**Q: What if I delete a venv manually?**
A: Run `venvy ls` and the entry will show the path no longer exists. Or use `venvy cleanup-registry` to remove dead entries.

**Q: Can I use this with conda environments?**
A: Yes! venvy detects and tracks conda envs too.

**Q: Does it work with nested venvs?**
A: Yes, though it's recommended to avoid nested venvs in general.

## Development

```bash
git clone https://github.com/pranavkumaarofficial/venvy
cd venvy
pip install -e ".[dev]"
pytest
```

## Contributing

Issues and PRs welcome!

- Bug Reports: [GitHub Issues](https://github.com/pranavkumaarofficial/venvy/issues)
- Feature Requests: [Discussions](https://github.com/pranavkumaarofficial/venvy/discussions)

## License

MIT - see [LICENSE](LICENSE)

---

**Made by [Pranav Kumaar](https://github.com/pranavkumaarofficial)**

*venvy - Virtual environment management without the pain*
