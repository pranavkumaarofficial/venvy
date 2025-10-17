# Changelog

## [0.2.0] - 2025-01-XX

### Major Changes - Registry-Based Tracking

**This is a fundamental redesign** - venvy now uses a SQLite registry to track virtual environments instead of slow filesystem scanning.

### Added

**Core Registry System:**
- SQLite database for instant venv lookups (`~/.venvy/venv_registry.db`)
- `venvy register` - Register venvs for tracking
- `venvy ls` - List all registered venvs (INSTANT - no scanning!)
- `venvy scan` - One-time scan to find and register existing venvs
- `venvy current` - Show currently active venv
- `venvy stats` - Statistics about registered venvs
- `venvy cleanup` - Remove venvs unused for N days
- `venvy shell-hook` - Generate shell integration for auto-tracking

**Features:**
- Tracks last-used timestamps automatically
- Links venvs to their project directories
- Shows Python version, package count, and disk usage
- Fast queries (< 10ms) vs slow scanning (minutes)
- Cross-platform support (Linux, macOS, Windows)

**Shell Integration:**
- Auto-register venvs when activated (optional)
- Bash/Zsh/Fish/PowerShell support
- Automatic last-used tracking

### Changed

**Breaking Changes:**
- `venvy list` is now slow (scans filesystem) - use `venvy ls` instead
- Focus shifted from discovery to management
- Registry must be populated before instant lookups work

**Philosophy:**
- **Before**: Scan filesystem every time (slow, inefficient)
- **After**: Track once, query instantly (fast, efficient)

### Performance

| Command | v0.1.1 | v0.2.0 |
|---------|--------|--------|
| List venvs | 2-5 min (scan) | < 10ms (registry) |
| Show stats | N/A | < 10ms |
| Cleanup old | N/A | < 100ms |

### Migration from 0.1.x

If upgrading from 0.1.x:

```bash
# One-time scan to populate registry
venvy scan --path ~/projects

# Or register manually
venvy register /path/to/venv

# Install shell hook for auto-tracking
venvy shell-hook >> ~/.bashrc
```

## [0.1.1] - 2024-09-04

### Changed
- Updated to handle multithreading
- README updates

## [0.1.0] - 2024-09-03

### Initial Release
- Environment discovery (venv, conda, pyenv, virtualenv)
- Health checks
- Size analysis
- Cleanup operations
- Filesystem scanning
