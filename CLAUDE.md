# venvy - Agent Instructions

This project uses **venvy** for Python virtual environment management.
venvy is an agent-safe environment layer with structured JSON output,
semantic exit codes, checkpoint/rollback, and offline supply-chain auditing.

## Rules

- NEVER use `python -m venv` or `virtualenv` directly.
- NEVER use raw `pip install` outside of venvy.
- ALWAYS use `venvy ensure` to create or verify environments.
- ALWAYS use `venvy safe-install` to install packages (auto-rollback on failure).
- ALWAYS use `--json` flag for structured output you can parse.
- Run `venvy audit --json` to check installed packages for known-vulnerable or malicious versions.
- Before risky changes, run `venvy checkpoint` to save environment state.

## Quick Reference

### Environment Setup (idempotent - safe to run multiple times)
```bash
venvy ensure --json
venvy ensure --python 3.11 --packages "requests flask" --json
venvy ensure --requirements requirements.txt --json
```

### Safe Package Installation (with auto-rollback on failure)
```bash
venvy safe-install requests flask --json
venvy safe-install -r requirements.txt --json
```

### Checkpoint and Rollback
```bash
venvy checkpoint --name "before-refactor" --json
venvy rollback --latest --json
venvy rollback --checkpoint "before-refactor" --json
```

### Query Environment State
```bash
venvy ls --json                    # List all registered environments
venvy current --json               # Show active environment
venvy stats --json                 # Show statistics
venvy doctor --json                # Diagnose issues
```

### Security Audit (known-vulnerable / malicious packages)
```bash
venvy audit --json                 # Scan all known environments
venvy audit --env .venv --json     # Scan a single environment
venvy audit --offline --json       # Never touch the network (deterministic CI)
venvy audit --refresh --json       # Update the advisory database, then scan
```
On the first run, `venvy audit` downloads a one-time advisory database (~30MB);
every scan after that is fully offline. Exit code precedence:
malicious (21) > vulnerable (20) > stale/partial (22).

## Exit Codes (parse these for error handling)

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Environment not found |
| 3 | Dependency conflict |
| 4 | Python version not found |
| 5 | Checkpoint not found |
| 7 | Permission denied |
| 20 | Audit: vulnerable package(s) found |
| 21 | Audit: malicious package(s) found |
| 22 | Audit: completed with caveats (stale DB or unknowns) |
| 23 | Audit: no advisory database (run `venvy audit --refresh`) |

## JSON Output Format

All commands with `--json` return:
```json
{
  "exit_code": 0,
  "success": true,
  ...command-specific fields...
}
```

## Common Workflows

### Setting up a new project
```bash
venvy ensure --python 3.11 --json
venvy safe-install requests flask sqlalchemy --json
venvy checkpoint --name "initial-setup" --json
```

### Installing a new dependency
```bash
venvy safe-install pandas --json
# If it fails, the environment is automatically rolled back
```

### Recovering from a broken environment
```bash
venvy rollback --latest --json
# Or rollback to a named checkpoint:
venvy rollback --checkpoint "initial-setup" --json
```

## venvy.json

If a `venvy.json` file exists in the project root, `venvy ensure` reads it automatically:
```json
{
  "python_version": "3.11",
  "packages": ["click>=8.0.0", "rich>=13.0.0"],
  "dev_packages": ["pytest>=7.0"],
  "scripts": {"test": "pytest tests/", "lint": "black --check ."}
}
```
