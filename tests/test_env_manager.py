"""Tests for environment creation, checkpoint, and rollback."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from venvy.env_manager import EnvironmentManager
from venvy.exit_codes import ExitCode


@pytest.fixture
def manager(tmp_path):
    """Create an EnvironmentManager with a temp registry."""
    with patch("venvy.env_manager.VenvRegistry") as MockRegistry:
        mock_reg = MagicMock()
        MockRegistry.return_value = mock_reg
        mock_reg.register.return_value = True
        mock_reg.refresh_metadata.return_value = True
        mgr = EnvironmentManager()
        mgr.registry = mock_reg
        mgr._tmp = tmp_path
        yield mgr


class TestEnsureEnvironment:
    def test_ensure_creates_new_venv(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        with patch.object(manager, "_find_python_for_version", return_value=Path("python")), \
             patch.object(manager, "_create_venv", return_value=True), \
             patch.object(manager, "_get_env_python", return_value=Path("python")), \
             patch("venvy.env_manager.get_python_version", return_value="3.11.0"):
            result = manager.ensure_environment(
                path=env_path, project_path=tmp_path
            )

        assert result["status"] == "created"
        assert result["_exit_code"] == ExitCode.SUCCESS
        assert result["python_version"] == "3.11.0"

    def test_ensure_verifies_existing_venv(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        with patch.object(manager, "_get_env_python", return_value=Path("python")), \
             patch("venvy.env_manager.get_python_version", return_value="3.11.0"), \
             patch.object(manager, "_get_pip_freeze", return_value=["requests==2.31.0"]):
            result = manager.ensure_environment(
                path=env_path, project_path=tmp_path
            )

        assert result["status"] == "verified"
        assert result["_exit_code"] == ExitCode.SUCCESS

    def test_ensure_with_python_version_mismatch(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        with patch.object(manager, "_get_env_python", return_value=Path("python")), \
             patch("venvy.env_manager.get_python_version", return_value="3.10.0"):
            result = manager.ensure_environment(
                path=env_path, python_version="3.11",
                project_path=tmp_path
            )

        assert result["status"] == "error"
        assert result["_exit_code"] == ExitCode.PYTHON_VERSION_NOT_FOUND

    def test_ensure_reads_venvy_json(self, manager, tmp_path):
        venvy_json = tmp_path / "venvy.json"
        venvy_json.write_text(json.dumps({
            "python_version": "3.11",
            "packages": ["requests", "flask"]
        }))

        env_path = tmp_path / ".venv"

        with patch.object(manager, "_find_python_for_version", return_value=Path("python")), \
             patch.object(manager, "_create_venv", return_value=True), \
             patch.object(manager, "_get_env_python", return_value=Path("python")), \
             patch("venvy.env_manager.get_python_version", return_value="3.11.0"), \
             patch.object(manager, "_install_packages", return_value=(True, "")):
            result = manager.ensure_environment(project_path=tmp_path)

        assert result["status"] == "created"
        assert result["packages_installed"] == ["requests", "flask"]

    def test_ensure_python_not_found(self, manager, tmp_path):
        with patch.object(manager, "_find_python_for_version", return_value=None):
            result = manager.ensure_environment(
                path=tmp_path / ".venv",
                python_version="3.99",
                project_path=tmp_path,
            )

        assert result["_exit_code"] == ExitCode.PYTHON_VERSION_NOT_FOUND


class TestSafeInstall:
    def test_safe_install_creates_checkpoint(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        with patch.object(manager, "create_checkpoint", return_value={
                "checkpoint_id": 1, "name": "pre-install", "_exit_code": 0}), \
             patch.object(manager, "_install_packages", return_value=(True, "")), \
             patch.object(manager, "_get_env_pip", return_value=Path("pip")):
            result = manager.safe_install(env_path=env_path, packages=["requests"])

        assert result["status"] == "success"
        assert result["rollback_performed"] is False

    def test_safe_install_rollback_on_failure(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        with patch.object(manager, "create_checkpoint", return_value={
                "checkpoint_id": 1, "name": "pre-install", "_exit_code": 0}), \
             patch.object(manager, "_install_packages", return_value=(False, "ERROR: conflict")), \
             patch.object(manager, "rollback_to_checkpoint", return_value={
                "status": "success", "_exit_code": 0}):
            result = manager.safe_install(env_path=env_path, packages=["broken-pkg"])

        assert result["status"] == "rolled_back"
        assert result["rollback_performed"] is True
        assert "ERROR: conflict" in result["error"]

    def test_safe_install_env_not_found(self, manager, tmp_path):
        result = manager.safe_install(
            env_path=tmp_path / "nonexistent",
            packages=["requests"]
        )
        assert result["_exit_code"] == ExitCode.ENV_NOT_FOUND


class TestCheckpoint:
    def test_create_checkpoint(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        manager.registry.create_checkpoint.return_value = 42

        with patch.object(manager, "_get_pip_freeze", return_value=["requests==2.31.0"]), \
             patch.object(manager, "_get_env_python", return_value=Path("python")), \
             patch("venvy.env_manager.get_python_version", return_value="3.11.0"):
            result = manager.create_checkpoint(env_path=env_path, name="test-cp")

        assert result["checkpoint_id"] == 42
        assert result["name"] == "test-cp"
        assert result["package_count"] == 1
        assert result["_exit_code"] == ExitCode.SUCCESS

    def test_checkpoint_auto_name(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        manager.registry.create_checkpoint.return_value = 1

        with patch.object(manager, "_get_pip_freeze", return_value=[]), \
             patch.object(manager, "_get_env_python", return_value=Path("python")), \
             patch("venvy.env_manager.get_python_version", return_value="3.11.0"):
            result = manager.create_checkpoint(env_path=env_path)

        assert result["name"].startswith("checkpoint-")

    def test_checkpoint_env_not_found(self, manager, tmp_path):
        result = manager.create_checkpoint(env_path=tmp_path / "nonexistent")
        assert result["_exit_code"] == ExitCode.ENV_NOT_FOUND


class TestRollback:
    def test_rollback_not_found(self, manager, tmp_path):
        env_path = tmp_path / ".venv"
        env_path.mkdir()
        (env_path / "pyvenv.cfg").write_text("home = /usr/bin")

        manager.registry.get_latest_checkpoint.return_value = None

        result = manager.rollback_to_checkpoint(env_path=env_path, use_latest=True)
        assert result["_exit_code"] == ExitCode.CHECKPOINT_NOT_FOUND

    def test_rollback_env_not_found(self, manager, tmp_path):
        result = manager.rollback_to_checkpoint(
            env_path=tmp_path / "nonexistent",
            use_latest=True,
        )
        assert result["_exit_code"] == ExitCode.ENV_NOT_FOUND
