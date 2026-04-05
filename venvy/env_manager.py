"""
Environment creation, package installation, and checkpoint/rollback operations.

This module provides the actual logic for agent-safe environment management.
CLI commands in cli.py are thin wrappers around these methods.
All public methods return plain dicts, making them directly serializable to JSON.
"""
import subprocess
import sys
import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from venvy.registry import VenvRegistry
from venvy.utils import find_python_executable, get_python_version, get_platform_info
from venvy.exit_codes import ExitCode


class EnvironmentManager:
    """Manages environment lifecycle: creation, installation, checkpoints, rollback."""

    def __init__(self):
        self.registry = VenvRegistry()

    def ensure_environment(
        self,
        path: Optional[Path] = None,
        name: Optional[str] = None,
        python_version: Optional[str] = None,
        packages: Optional[List[str]] = None,
        requirements: Optional[Path] = None,
        project_path: Optional[Path] = None,
    ) -> Dict:
        """
        Idempotent environment setup. Creates if missing, verifies if exists.

        Returns dict with: status, path, python_version, packages_installed, _exit_code
        """
        project_path = project_path or Path.cwd()

        # Load venvy.json defaults from project root
        venvy_config = self._load_venvy_json(project_path)
        if venvy_config:
            if python_version is None:
                python_version = venvy_config.get("python_version")
            if packages is None and not requirements:
                packages = venvy_config.get("packages")

        # Resolve environment path
        if path is None:
            if name:
                path = project_path / name
            else:
                path = project_path / ".venv"

        path = Path(path).resolve()

        # Check if environment already exists
        if path.exists() and self._is_valid_venv(path):
            return self._verify_existing_env(path, python_version, packages, requirements, project_path)

        # Create new environment
        return self._create_new_env(path, name, python_version, packages, requirements, project_path)

    def safe_install(
        self,
        env_path: Path,
        packages: Optional[List[str]] = None,
        requirements: Optional[Path] = None,
        checkpoint_name: Optional[str] = None,
    ) -> Dict:
        """
        Install packages with auto-checkpoint and rollback on failure.

        Returns dict with: status, installed, errors, checkpoint_name, rollback_performed, _exit_code
        """
        env_path = Path(env_path).resolve()

        if not env_path.exists() or not self._is_valid_venv(env_path):
            return {"status": "failed", "error": "Environment not found or invalid",
                    "_exit_code": ExitCode.ENV_NOT_FOUND}

        if not packages and not requirements:
            return {"status": "failed", "error": "No packages or requirements specified",
                    "_exit_code": ExitCode.GENERAL_ERROR}

        # Create auto-checkpoint before installing
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        cp_name = checkpoint_name or f"pre-install-{ts}"
        cp_result = self.create_checkpoint(env_path=env_path, name=cp_name)

        if cp_result.get("_exit_code", 0) != 0:
            return {"status": "failed", "error": "Failed to create checkpoint",
                    "_exit_code": ExitCode.GENERAL_ERROR}

        # Attempt installation
        if packages:
            success, output = self._install_packages(env_path, packages)
        else:
            success, output = self._install_requirements(env_path, requirements)

        if success:
            # Refresh registry metadata
            self.registry.refresh_metadata(env_path)

            installed = packages or [f"-r {requirements}"]
            return {
                "status": "success",
                "installed": installed,
                "checkpoint_name": cp_name,
                "checkpoint_id": cp_result.get("checkpoint_id"),
                "rollback_performed": False,
                "_exit_code": ExitCode.SUCCESS,
            }
        else:
            # Auto-rollback
            rollback_result = self.rollback_to_checkpoint(
                env_path=env_path,
                checkpoint_name=cp_name,
            )

            rollback_ok = rollback_result.get("_exit_code", 0) == 0

            return {
                "status": "rolled_back" if rollback_ok else "failed",
                "installed": [],
                "error": output,
                "checkpoint_name": cp_name,
                "rollback_performed": rollback_ok,
                "_exit_code": ExitCode.DEPENDENCY_CONFLICT if rollback_ok else ExitCode.GENERAL_ERROR,
            }

    def create_checkpoint(
        self,
        env_path: Path,
        name: Optional[str] = None,
    ) -> Dict:
        """
        Snapshot current environment state.

        Returns dict with: checkpoint_id, name, package_count, python_version, _exit_code
        """
        env_path = Path(env_path).resolve()

        if not env_path.exists() or not self._is_valid_venv(env_path):
            return {"error": "Environment not found or invalid",
                    "_exit_code": ExitCode.ENV_NOT_FOUND}

        # Get current pip freeze
        pip_freeze = self._get_pip_freeze(env_path)

        # Get Python version
        python_exe = self._get_env_python(env_path)
        py_version = get_python_version(python_exe) if python_exe else None

        # Generate name if not provided
        if not name:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"checkpoint-{ts}"

        # Store in registry
        checkpoint_id = self.registry.create_checkpoint(
            env_path=env_path,
            name=name,
            pip_freeze=pip_freeze,
            python_version=py_version,
        )

        if checkpoint_id is None:
            return {"error": "Failed to create checkpoint",
                    "_exit_code": ExitCode.GENERAL_ERROR}

        return {
            "checkpoint_id": checkpoint_id,
            "name": name,
            "package_count": len(pip_freeze),
            "python_version": py_version,
            "packages": pip_freeze,
            "_exit_code": ExitCode.SUCCESS,
        }

    def rollback_to_checkpoint(
        self,
        env_path: Path,
        checkpoint_name: Optional[str] = None,
        checkpoint_id: Optional[int] = None,
        use_latest: bool = False,
    ) -> Dict:
        """
        Restore environment to a checkpoint state.

        Returns dict with: status, checkpoint_used, packages_added, packages_removed, _exit_code
        """
        env_path = Path(env_path).resolve()

        if not env_path.exists() or not self._is_valid_venv(env_path):
            return {"status": "failed", "error": "Environment not found or invalid",
                    "_exit_code": ExitCode.ENV_NOT_FOUND}

        # Resolve which checkpoint to use
        cp = None
        if checkpoint_id:
            cp = self.registry.get_checkpoint(checkpoint_id)
        elif checkpoint_name:
            cp = self.registry.get_checkpoint_by_name(env_path, checkpoint_name)
        elif use_latest:
            cp = self.registry.get_latest_checkpoint(env_path)

        if cp is None:
            return {"status": "failed", "error": "Checkpoint not found",
                    "_exit_code": ExitCode.CHECKPOINT_NOT_FOUND}

        checkpoint_packages = set(cp.pip_freeze or [])

        # Get current state
        current_packages = set(self._get_pip_freeze(env_path))

        # Compute diff
        to_add = checkpoint_packages - current_packages
        to_remove = current_packages - checkpoint_packages

        pip_exe = self._get_env_pip(env_path)
        if not pip_exe:
            return {"status": "failed", "error": "pip not found in environment",
                    "_exit_code": ExitCode.GENERAL_ERROR}

        # Uninstall packages not in checkpoint
        if to_remove:
            pkg_names = [p.split("==")[0] for p in to_remove]
            try:
                subprocess.run(
                    [str(pip_exe), "uninstall", "-y"] + pkg_names,
                    capture_output=True, text=True, timeout=300
                )
            except Exception:
                pass  # best-effort removal

        # Install packages from checkpoint at exact versions
        if to_add:
            try:
                subprocess.run(
                    [str(pip_exe), "install"] + list(to_add),
                    capture_output=True, text=True, timeout=600
                )
            except Exception:
                return {"status": "failed", "error": "Failed to install checkpoint packages",
                        "_exit_code": ExitCode.GENERAL_ERROR}

        # Refresh registry
        self.registry.refresh_metadata(env_path)

        return {
            "status": "success",
            "checkpoint_used": cp.name,
            "checkpoint_id": cp.id,
            "packages_added": sorted(to_add),
            "packages_removed": sorted(to_remove),
            "_exit_code": ExitCode.SUCCESS,
        }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _is_valid_venv(self, path: Path) -> bool:
        """Check if a path is a valid Python virtual environment."""
        return (path / "pyvenv.cfg").exists() or (path / "conda-meta").exists()

    def _load_venvy_json(self, project_path: Path) -> Optional[Dict]:
        """Load venvy.json from project root if it exists."""
        venvy_json = project_path / "venvy.json"
        if venvy_json.exists():
            try:
                return json.loads(venvy_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def _verify_existing_env(self, path: Path, python_version: Optional[str],
                             packages: Optional[List[str]], requirements: Optional[Path],
                             project_path: Path) -> Dict:
        """Verify an existing environment and update if needed."""
        python_exe = self._get_env_python(path)
        current_version = get_python_version(python_exe) if python_exe else None

        # Check Python version match
        if python_version and current_version:
            if not current_version.startswith(python_version):
                return {
                    "status": "error",
                    "error": f"Python version mismatch: wanted {python_version}, got {current_version}",
                    "path": str(path),
                    "python_version": current_version,
                    "_exit_code": ExitCode.PYTHON_VERSION_NOT_FOUND,
                }

        # Install missing packages if specified
        packages_installed = []
        if packages:
            missing = self._find_missing_packages(path, packages)
            if missing:
                success, output = self._install_packages(path, missing)
                if success:
                    packages_installed = missing
                else:
                    return {
                        "status": "error",
                        "error": f"Failed to install packages: {output}",
                        "path": str(path),
                        "_exit_code": ExitCode.DEPENDENCY_CONFLICT,
                    }
        elif requirements:
            success, output = self._install_requirements(path, requirements)
            if not success:
                return {
                    "status": "error",
                    "error": f"Failed to install requirements: {output}",
                    "path": str(path),
                    "_exit_code": ExitCode.DEPENDENCY_CONFLICT,
                }
            packages_installed = [f"-r {requirements}"]

        # Register/update in registry
        self.registry.register(path, project_path)

        status = "updated" if packages_installed else "verified"
        return {
            "status": status,
            "path": str(path),
            "python_version": current_version,
            "packages_installed": packages_installed,
            "_exit_code": ExitCode.SUCCESS,
        }

    def _create_new_env(self, path: Path, name: Optional[str],
                        python_version: Optional[str], packages: Optional[List[str]],
                        requirements: Optional[Path], project_path: Path) -> Dict:
        """Create a brand new virtual environment."""
        # Find Python executable
        python_exe = self._find_python_for_version(python_version)
        if not python_exe:
            detail = f" {python_version}" if python_version else ""
            return {
                "status": "error",
                "error": f"Python{detail} not found on system",
                "_exit_code": ExitCode.PYTHON_VERSION_NOT_FOUND,
            }

        # Create the venv
        success = self._create_venv(path, python_exe)
        if not success:
            return {
                "status": "error",
                "error": f"Failed to create virtual environment at {path}",
                "_exit_code": ExitCode.GENERAL_ERROR,
            }

        # Get actual Python version in the new env
        env_python = self._get_env_python(path)
        actual_version = get_python_version(env_python) if env_python else None

        # Install packages
        packages_installed = []
        if packages:
            success, output = self._install_packages(path, packages)
            if success:
                packages_installed = packages
            else:
                return {
                    "status": "error",
                    "error": f"Environment created but package install failed: {output}",
                    "path": str(path),
                    "python_version": actual_version,
                    "_exit_code": ExitCode.DEPENDENCY_CONFLICT,
                }
        elif requirements:
            success, output = self._install_requirements(path, requirements)
            if success:
                packages_installed = [f"-r {requirements}"]
            else:
                return {
                    "status": "error",
                    "error": f"Environment created but requirements install failed: {output}",
                    "path": str(path),
                    "python_version": actual_version,
                    "_exit_code": ExitCode.DEPENDENCY_CONFLICT,
                }

        # Register in the registry
        self.registry.register(path, project_path, name)

        return {
            "status": "created",
            "path": str(path),
            "python_version": actual_version,
            "packages_installed": packages_installed,
            "_exit_code": ExitCode.SUCCESS,
        }

    def _find_python_for_version(self, version: Optional[str]) -> Optional[Path]:
        """Find a Python executable matching the requested version."""
        platform_info = get_platform_info()

        if version is None:
            # Use current Python
            return Path(sys.executable)

        candidates = []

        if platform_info["is_windows"]:
            # Windows Python Launcher
            candidates.append(["py", f"-{version}"])
            candidates.append([f"python{version}"])
            candidates.append(["python"])
        else:
            candidates.append([f"python{version}"])
            candidates.append([f"python{version.replace('.', '')}"])
            candidates.append(["python3"])
            candidates.append(["python"])

        for cmd in candidates:
            try:
                result = subprocess.run(
                    cmd + ["--version"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    output = (result.stdout + result.stderr).strip()
                    if version in output:
                        # Return the first element of the command as the executable
                        if len(cmd) > 1 and cmd[0] == "py":
                            # For py launcher, return the full command info
                            return Path(cmd[0])
                        return Path(cmd[0])
            except (subprocess.SubprocessError, FileNotFoundError):
                continue

        return None

    def _create_venv(self, path: Path, python_exe: Path) -> bool:
        """Create a venv using the venv module."""
        try:
            cmd = [str(python_exe), "-m", "venv", str(path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _get_pip_freeze(self, env_path: Path) -> List[str]:
        """Run pip list --format=freeze in the environment and return package list."""
        pip_exe = self._get_env_pip(env_path)
        if not pip_exe:
            return []

        try:
            result = subprocess.run(
                [str(pip_exe), "list", "--format=freeze"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return []

    def _install_packages(self, env_path: Path, packages: List[str]) -> Tuple[bool, str]:
        """Run pip install and return (success, output)."""
        pip_exe = self._get_env_pip(env_path)
        if not pip_exe:
            return False, "pip not found in environment"

        try:
            result = subprocess.run(
                [str(pip_exe), "install"] + packages,
                capture_output=True, text=True, timeout=600
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Installation timed out (10 min limit)"
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return False, str(e)

    def _install_requirements(self, env_path: Path, req_file: Path) -> Tuple[bool, str]:
        """Run pip install -r and return (success, output)."""
        pip_exe = self._get_env_pip(env_path)
        if not pip_exe:
            return False, "pip not found in environment"

        try:
            result = subprocess.run(
                [str(pip_exe), "install", "-r", str(req_file)],
                capture_output=True, text=True, timeout=600
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Installation timed out (10 min limit)"
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return False, str(e)

    def _find_missing_packages(self, env_path: Path, packages: List[str]) -> List[str]:
        """Find which packages from the list are not installed."""
        installed = set()
        for line in self._get_pip_freeze(env_path):
            pkg_name = line.split("==")[0].lower().replace("-", "_")
            installed.add(pkg_name)

        missing = []
        for pkg in packages:
            # Normalize: "requests>=2.0" -> "requests"
            pkg_name = pkg.split(">=")[0].split("<=")[0].split("==")[0].split("!=")[0].split("[")[0]
            pkg_name = pkg_name.lower().replace("-", "_").strip()
            if pkg_name not in installed:
                missing.append(pkg)

        return missing

    def _get_env_pip(self, env_path: Path) -> Optional[Path]:
        """Find pip executable in environment."""
        platform_info = get_platform_info()

        if platform_info["is_windows"]:
            candidates = [
                env_path / "Scripts" / "pip.exe",
                env_path / "Scripts" / "pip3.exe",
            ]
        else:
            candidates = [
                env_path / "bin" / "pip",
                env_path / "bin" / "pip3",
            ]

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _get_env_python(self, env_path: Path) -> Optional[Path]:
        """Find python executable in environment."""
        return find_python_executable(env_path)
