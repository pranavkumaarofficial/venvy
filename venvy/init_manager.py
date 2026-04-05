"""
InitManager: orchestrates the one-time `venvy init` project setup.

Steps:
1. Ensure .venv exists
2. Install pip wrapper hook in shell profile
3. Configure pip.ini (require-virtualenv)
4. Generate CLAUDE.md
5. Create venvy.json
6. Register project + create initial checkpoint
"""
import json
import os
from pathlib import Path
from typing import Optional, Dict

from venvy.exit_codes import ExitCode


class InitManager:
    """Orchestrates all init steps. Each step is idempotent."""

    def initialize_project(
        self,
        project_path: Path,
        python_version: Optional[str] = None,
        install_hook: bool = True,
        generate_claude: bool = True,
        configure_pip: bool = True,
        force: bool = False,
    ) -> Dict:
        """Full project initialization. Returns status of each step."""
        project_path = Path(project_path).resolve()
        steps = {}

        # Step 1: Ensure environment
        steps["ensure"] = self._ensure_environment(project_path, python_version)
        env_info = steps["ensure"]

        # Step 2: Install pip hook
        if install_hook:
            steps["pip_hook"] = self._install_pip_hook()
        else:
            steps["pip_hook"] = {"status": "skipped", "detail": "Disabled via --no-hook"}

        # Step 3: Configure pip.ini
        if configure_pip:
            steps["pip_config"] = self._configure_pip()
        else:
            steps["pip_config"] = {"status": "skipped", "detail": "Disabled via --no-pip-config"}

        # Step 4: Generate CLAUDE.md
        if generate_claude:
            steps["claude_md"] = self._generate_claude_md(project_path, env_info, force)
        else:
            steps["claude_md"] = {"status": "skipped", "detail": "Disabled via --no-claude-md"}

        # Step 5: Create venvy.json
        steps["venvy_json"] = self._create_venvy_json(project_path, env_info, force)

        # Step 6: Initial checkpoint
        steps["checkpoint"] = self._initial_checkpoint(project_path, env_info)

        return {"steps": steps, "_exit_code": ExitCode.SUCCESS}

    def _ensure_environment(self, project_path: Path, python_version: Optional[str]) -> Dict:
        """Step 1: Create or verify .venv."""
        from venvy.env_manager import EnvironmentManager

        mgr = EnvironmentManager()
        result = mgr.ensure_environment(
            project_path=project_path,
            python_version=python_version,
        )
        return result

    def _install_pip_hook(self) -> Dict:
        """Step 2: Append pip wrapper to shell profile."""
        from venvy.shell_integration import (
            get_shell_config_path,
            generate_powershell_pip_wrapper,
            generate_bash_pip_wrapper,
        )

        config_path = get_shell_config_path()
        if not config_path:
            return {"status": "skipped", "detail": "No shell config file found"}

        # Read existing content
        content = ""
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8", errors="ignore")

        # Check if already installed
        if "venvy pip observer" in content:
            return {"status": "skipped", "detail": f"Pip hook already in {config_path}"}

        # Determine shell type from config path
        config_name = config_path.name.lower()
        if "powershell" in config_name or config_name.endswith(".ps1"):
            wrapper = generate_powershell_pip_wrapper()
        else:
            wrapper = generate_bash_pip_wrapper()

        # Append to profile
        with open(config_path, "a", encoding="utf-8") as f:
            f.write("\n" + wrapper)

        return {"status": "created", "detail": f"Pip hook added to {config_path}"}

    def _configure_pip(self) -> Dict:
        """Step 3: Set require-virtualenv in pip config."""
        from venvy.shell_integration import configure_pip_require_virtualenv

        return configure_pip_require_virtualenv()

    def _generate_claude_md(self, project_path: Path, env_info: Dict, force: bool) -> Dict:
        """Step 4: Generate CLAUDE.md from template."""
        from venvy.claude_generator import ClaudeInstructionGenerator

        claude_md_path = project_path / "CLAUDE.md"

        if claude_md_path.exists() and not force:
            return {"status": "skipped", "detail": "CLAUDE.md already exists (use --force to overwrite)"}

        generator = ClaudeInstructionGenerator()
        content = generator.generate(project_path, env_info)

        claude_md_path.write_text(content, encoding="utf-8")
        return {"status": "created", "detail": str(claude_md_path)}

    def _create_venvy_json(self, project_path: Path, env_info: Dict, force: bool) -> Dict:
        """Step 5: Create venvy.json if not exists."""
        venvy_json_path = project_path / "venvy.json"

        if venvy_json_path.exists() and not force:
            return {"status": "skipped", "detail": "venvy.json already exists (use --force to overwrite)"}

        python_version = env_info.get("python_version", "3.11")
        parts = python_version.split(".")
        if len(parts) >= 2:
            python_version = f"{parts[0]}.{parts[1]}"

        # Scan for existing deps
        packages = []
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            try:
                for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        packages.append(line)
            except Exception:
                pass

        config = {
            "python_version": python_version,
            "packages": packages,
            "dev_packages": [],
            "scripts": {},
        }

        venvy_json_path.write_text(
            json.dumps(config, indent=2) + "\n",
            encoding="utf-8"
        )
        return {"status": "created", "detail": str(venvy_json_path)}

    def _initial_checkpoint(self, project_path: Path, env_info: Dict) -> Dict:
        """Step 6: Register and create initial checkpoint."""
        from venvy.env_manager import EnvironmentManager

        env_path = env_info.get("path")
        if not env_path:
            return {"status": "skipped", "detail": "No environment path available"}

        mgr = EnvironmentManager()
        try:
            result = mgr.create_checkpoint(
                env_path=Path(env_path),
                name="venvy-init",
            )
            return {"status": "created", "detail": result.get("name", "venvy-init")}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
