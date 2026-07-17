"""Tests for CLI --json output on key commands."""
import json
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from venvy.cli import main


@pytest.fixture
def runner():
    return CliRunner()


class TestJsonOutput:
    def test_stats_json(self, runner):
        mock_stats = {
            "total_venvs": 5,
            "missing_venvs": 0,
            "total_size_mb": 100.0,
            "total_packages": 50,
            "unused_30_days": 1,
            "unused_90_days": 0,
            "total_checkpoints": 2,
        }
        with patch("venvy.registry.VenvRegistry") as MockReg:
            MockReg.return_value.get_stats.return_value = mock_stats
            result = runner.invoke(main, ["--json", "stats"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["total_venvs"] == 5

    def test_current_json_no_venv(self, runner):
        with patch.dict("os.environ", {}, clear=True):
            # Remove VIRTUAL_ENV from env
            import os
            env = os.environ.copy()
            env.pop("VIRTUAL_ENV", None)
            with patch.dict("os.environ", env, clear=True):
                result = runner.invoke(main, ["--json", "current"])

        data = json.loads(result.output)
        assert data["active"] is False


class TestJsonFlagPosition:
    """Regression: `--json` must work AFTER the subcommand, not only before it.

    Commands without a local --json used to fail with "No such option: --json";
    the VenvyGroup now injects it into every command. This is the form users type
    and the form venvy's own generated CLAUDE.md emits.
    """

    def test_stats_json_after_form(self, runner):
        mock_stats = {
            "total_venvs": 3, "missing_venvs": 0, "total_size_mb": 10.0,
            "total_packages": 5, "unused_30_days": 0, "unused_90_days": 0,
            "total_checkpoints": 0,
        }
        with patch("venvy.registry.VenvRegistry") as MockReg:
            MockReg.return_value.get_stats.return_value = mock_stats
            result = runner.invoke(main, ["stats", "--json"])   # AFTER the subcommand
        assert result.exit_code == 0
        assert json.loads(result.output)["total_venvs"] == 3

    def test_current_json_after_form(self, runner):
        import os
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        with patch.dict("os.environ", env, clear=True):
            result = runner.invoke(main, ["current", "--json"])
        # Valid JSON output proves --json was accepted after the subcommand (before the
        # fix this was a "No such option" usage error). current with no active venv
        # legitimately exits 2 (ENV_NOT_FOUND), so we assert on the payload, not the code.
        assert json.loads(result.output)["active"] is False

    def test_both_forms_equivalent(self, runner):
        # `--json stats` and `stats --json` must produce the same shape.
        mock_stats = {
            "total_venvs": 1, "missing_venvs": 0, "total_size_mb": 1.0,
            "total_packages": 1, "unused_30_days": 0, "unused_90_days": 0,
            "total_checkpoints": 0,
        }
        with patch("venvy.registry.VenvRegistry") as MockReg:
            MockReg.return_value.get_stats.return_value = mock_stats
            before = runner.invoke(main, ["--json", "stats"])
            MockReg.return_value.get_stats.return_value = mock_stats
            after = runner.invoke(main, ["stats", "--json"])
        assert before.exit_code == after.exit_code == 0
        assert json.loads(before.output) == json.loads(after.output)


def test_version_matches_package_metadata():
    """Regression: `venvy --version` must not drift from the installed package."""
    import venvy
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            assert venvy.__version__ == version("venvy")
        except PackageNotFoundError:
            pytest.skip("venvy not installed as a distribution")
    except ImportError:
        pytest.skip("importlib.metadata unavailable")

    def test_cleanup_registry_json(self, runner):
        with patch("venvy.registry.VenvRegistry") as MockReg:
            MockReg.return_value.cleanup_missing.return_value = 3
            result = runner.invoke(main, ["--json", "cleanup-registry"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["removed"] == 3

    def test_doctor_json(self, runner):
        with patch("venvy.registry.VenvRegistry") as MockReg:
            mock_reg = MockReg.return_value
            mock_reg.db_path = MagicMock()
            mock_reg.db_path.exists.return_value = True
            mock_reg.get_stats.return_value = {
                "total_venvs": 2, "missing_venvs": 0,
                "total_size_mb": 50.0, "total_packages": 20,
                "unused_30_days": 0, "unused_90_days": 0,
                "total_checkpoints": 0,
            }
            with patch("venvy.shell_integration.get_shell_config_path", return_value=None):
                result = runner.invoke(main, ["--json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert "checks" in data

    def test_ls_json_empty(self, runner):
        with patch("venvy.registry.VenvRegistry") as MockReg:
            mock_reg = MockReg.return_value
            mock_reg.list_all.return_value = []
            mock_reg.get_stats.return_value = {
                "total_venvs": 0, "missing_venvs": 0,
                "total_size_mb": 0, "total_packages": 0,
                "unused_30_days": 0, "unused_90_days": 0,
                "total_checkpoints": 0,
            }
            result = runner.invoke(main, ["--json", "ls"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["count"] == 0

    def test_ensure_json(self, runner, tmp_path):
        with patch("venvy.env_manager.EnvironmentManager") as MockMgr:
            MockMgr.return_value.ensure_environment.return_value = {
                "status": "created",
                "path": str(tmp_path / ".venv"),
                "python_version": "3.11.0",
                "packages_installed": [],
                "_exit_code": 0,
            }
            result = runner.invoke(main, ["--json", "ensure", "--path", str(tmp_path)])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["status"] == "created"

    def test_checkpoint_json_no_env(self, runner):
        with patch("venvy.cli._auto_detect_env", return_value=None):
            result = runner.invoke(main, ["--json", "checkpoint"])

        data = json.loads(result.output)
        assert data["success"] is False
        assert data["exit_code"] == 2  # ENV_NOT_FOUND
