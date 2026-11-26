# Changelog

## [1.2.0] - unreleased

### Added
- **Tests for the scan's three promises** (`tests/test_audit_invariants.py`): no code from
  a scanned environment runs (planted package, `.pth` and `sitecustomize.py` traps), no
  subprocess is spawned, and no socket is opened when a usable database exists.
- **Self-audit before publish.** The release workflow installs the built wheel into a
  clean venv on Python 3.10 and 3.13, checks `venvy --version` matches the tag, and blocks
  the release if `venvy audit` finds a vulnerable or malicious package in it.
- `SECURITY.md` and `docs/THREAT_MODEL.md`.
- `scripts/bench.py`: reproducible benchmark of `audit` and `dedup` at 10/50/100 envs.

### Removed
- **`venvy ui`.** It looked for `ui/serve.py` in the source tree, which is not part of the
  published package, so it failed on every PyPI install (and exited 0 when it did).
- **`psutil` dependency.** Nothing in venvy imported it.

### Fixed
- `db.advisory_count` and `db.malicious_count` in `venvy audit --json` are now integers.
  They were emitted as strings because the database stores metadata as text. Consumers
  that compared them as strings need updating.

### Changed
- **`venvy dedup` dry runs are about 7x faster.** On 20 environments (855 MB, 13,825
  files, warm cache) the scan went from 15.8 s to 2.1 s with identical results; at 100
  environments (4.3 GB, `scripts/bench.py`) from 98.8 s to 13.0 s. Two
  changes: the file walk uses `os.scandir`, so type and size come from the directory
  listing instead of three `stat` calls per file; and a file's SHA-256 is taken from the
  `RECORD` file pip wrote at install time when the recorded size matches the size on
  disk, so most files are never read. Files without a usable `RECORD` entry are hashed
  as before. `--apply` still re-hashes every file before linking, so a stale or forged
  `RECORD` can only cause a skipped file, never a bad link. `--verify` hashes everything
  in the dry run too. JSON output gains `hashed_files` and `record_hashed_files`.
- Development status classifier moved from Alpha to Beta.
- README rewritten around the audit, with a Design notes section.

## [1.1.1] - 2026-09-30

### Fixed
- **venvy no longer reports its own dependency.** `click>=8.0.0` resolved to 8.1.8, which
  carries CVE-2026-7246, so a fresh `pip install venvy` followed by `venvy audit` reported
  a HIGH finding against venvy's own dependency. The floor is now `click>=8.3.3` on Python
  3.10 and above. Python 3.8 and 3.9 stay on the 8.1 line, because 8.3.3 requires 3.10, and
  the finding is still reported there rather than suppressed. venvy does not call the
  affected API (`click.edit()`).

## [1.1.0] - 2026-07-30

### Added
- **Install date on every finding.** Each finding now carries `installed_at`, the local
  date the package landed on disk (from the `.dist-info` directory mtime), shown as a
  `landed` column in the human report and an `installed_at` field in JSON. This turns a
  stale finding from "uninstall it" into "this arrived on <date> — scope what was exposed
  in that window."

## [1.0.0] - 2026-07-21

First stable release. venvy is now an **offline, machine-wide Python supply-chain
security audit** — for humans and AI agents — with a lightweight virtual-environment
manager alongside it.

### Added — supply-chain audit (`venvy audit`)
- Scan every environment on the machine for **known-vulnerable AND malicious** packages,
  fully **offline**, against a local advisory database compiled from OSV plus the DataDog
  malicious-package and typosquat feeds.
- Deterministic PEP 440 range matching with a **fail-closed** policy: anything that cannot
  be evaluated with confidence is reported `UNKNOWN`, never silently cleared.
- Text-only inventory: reads `*.dist-info`/`*.egg-info` metadata only — never imports or
  executes code from a scanned environment, and opens no sockets during a scan.
- **First-run auto-fetch** of the advisory DB (one-time, ~30MB); every scan after is
  offline. `--offline` for deterministic CI/agent use; `--refresh` to update.
- Semantic exit codes for CI/agents: `0` clean, `20` vulnerable, `21` malicious,
  `22` stale/partial, `23` no database (precedence: malicious > vulnerable > stale).
- Stable, versioned `--json` output; `--include-toolchain` to gate on pip/setuptools/wheel.
- DB-usability validation on open (corrupt/empty databases fail closed to exit 23 instead
  of crashing or reporting a false all-clear).

### Added — environment management
- `venvy dedup` — reclaim disk space by hardlinking identical files across environments
  (nothing deleted; duplicates become shared inodes).

### Changed
- `--json` is now position-independent — works before or after any subcommand.
- `venvy --version` is derived from installed package metadata, so it can never drift.
- Removed the on-device LLM error-analysis path (a deterministic security tool must not
  depend on a model).

### Quality
- Full test suite runs on **Windows, macOS, and Linux** across Python 3.8–3.13 in CI on
  every push and PR.

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
