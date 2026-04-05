"""
Template-based CLAUDE.md generator for venvy init.

Generates agent instructions tailored to a specific project's environment.
"""
from pathlib import Path
from typing import Dict, Optional


CLAUDE_MD_TEMPLATE = """# {project_name} - Agent Instructions

This project uses **venvy** for Python virtual environment management.
venvy actively monitors pip installs, tracks disk usage, and provides
structured JSON output for agent-friendly workflows.

## Rules

- NEVER use `python -m venv` or `virtualenv` directly.
- NEVER use raw `pip install` outside of venvy.
- ALWAYS use `venvy ensure` to create or verify environments.
- ALWAYS use `venvy safe-install` to install packages (auto-rollback on failure).
- ALWAYS use `--json` flag for structured output you can parse.
- PERIODICALLY run `venvy status --json` to check environment health.
- If a `pip install` fails, run `venvy analyze-error` to get fix suggestions.
- Before risky changes, run `venvy checkpoint` to save environment state.

## Environment Info

- Python: {python_version}
- Environment: {env_path}
- Packages: {package_count}

## Quick Reference

### Check Environment Health (do this regularly)
```bash
venvy status --json
```

### Environment Setup (idempotent - safe to run multiple times)
```bash
venvy ensure --json
venvy ensure --python {python_version_short} --packages "requests flask" --json
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
venvy ls --json
venvy current --json
venvy stats --json
venvy doctor --json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Environment not found |
| 3 | Dependency conflict |
| 4 | Python version not found |
| 5 | Checkpoint not found |
| 6 | Gemma AI not available |
| 7 | Permission denied |

## JSON Output

All commands with `--json` return:
```json
{{
  "exit_code": 0,
  "success": true,
  ...command-specific fields...
}}
```

## Observability

venvy monitors every `pip install` and `pip uninstall` in this project.
Run `venvy status --json` to see recent activity, disk usage, and alerts.
If venvy flags bloat or issues, they appear in the status output.

## venvy.json

If a `venvy.json` exists in the project root, `venvy ensure` reads it automatically:
```json
{{
  "python_version": "{python_version_short}",
  "packages": ["dep1", "dep2"],
  "dev_packages": ["pytest"]
}}
```
"""


class ClaudeInstructionGenerator:
    """Generates CLAUDE.md files tailored to a project's venvy configuration."""

    def generate(self, project_path: Path, env_info: Dict) -> str:
        """Return CLAUDE.md content tailored to this project."""
        project_name = project_path.name
        python_version = env_info.get("python_version", "3.11")
        env_path = env_info.get("path", str(project_path / ".venv"))
        package_count = env_info.get("package_count", 0)

        # Extract short version like "3.11" from "3.11.5"
        python_version_short = python_version
        parts = python_version.split(".")
        if len(parts) >= 2:
            python_version_short = f"{parts[0]}.{parts[1]}"

        return CLAUDE_MD_TEMPLATE.format(
            project_name=project_name,
            python_version=python_version,
            python_version_short=python_version_short,
            env_path=env_path,
            package_count=package_count,
        ).strip() + "\n"
