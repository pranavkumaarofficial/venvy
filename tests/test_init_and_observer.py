"""Tests for venvy init, pip observer, event logging, and CLAUDE.md generation."""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from venvy.cli import main


@pytest.fixture
def runner():
    return CliRunner()


# ========================================================================
# PIP EVENT CRUD (registry)
# ========================================================================

class TestPipEventsCRUD:
    def test_log_and_retrieve_event(self, tmp_path):
        from venvy.registry import VenvRegistry

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            reg = VenvRegistry()
            event_id = reg.log_pip_event(
                env_path=tmp_path / ".venv",
                action="install",
                packages=["requests", "flask"],
                exit_code=0,
                packages_added=["requests==2.31.0", "flask==3.0.0"],
                size_delta_mb=15.2,
            )

        assert event_id is not None
        events = reg.get_recent_events(tmp_path / ".venv", limit=5)
        assert len(events) == 1
        assert events[0].action == "install"
        assert events[0].packages == ["requests", "flask"]
        assert events[0].packages_added == ["requests==2.31.0", "flask==3.0.0"]
        assert events[0].size_delta_mb == 15.2

    def test_get_recent_events_ordered(self, tmp_path):
        from venvy.registry import VenvRegistry

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            reg = VenvRegistry()
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", packages=["first"])
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", packages=["second"])
            reg.log_pip_event(env_path=tmp_path / ".venv", action="uninstall", packages=["third"])

        events = reg.get_recent_events(tmp_path / ".venv", limit=10)
        assert len(events) == 3
        # Newest first (ORDER BY id DESC)
        assert events[0].packages == ["third"]
        assert events[1].packages == ["second"]
        assert events[2].packages == ["first"]

    def test_get_event_summary(self, tmp_path):
        from venvy.registry import VenvRegistry

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            reg = VenvRegistry()
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", exit_code=0, size_delta_mb=10.0)
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", exit_code=1, size_delta_mb=0.0)
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", exit_code=0, size_delta_mb=20.0)

        summary = reg.get_event_summary(tmp_path / ".venv")
        assert summary["total_events"] == 3
        assert summary["total_installs"] == 3
        assert summary["total_failures"] == 1
        assert summary["total_size_delta_mb"] == 30.0

    def test_get_alerts(self, tmp_path):
        from venvy.registry import VenvRegistry

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            reg = VenvRegistry()
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", alert_level=None)
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install",
                              alert_level="warn", alert_message="Large install")
            reg.log_pip_event(env_path=tmp_path / ".venv", action="install", alert_level=None)

        alerts = reg.get_alerts(tmp_path / ".venv")
        assert len(alerts) == 1
        assert alerts[0].alert_level == "warn"
        assert alerts[0].alert_message == "Large install"

    def test_get_all_events_across_envs(self, tmp_path):
        from venvy.registry import VenvRegistry

        # Patch at venvy.registry since it uses `from venvy.utils import get_venvy_data_dir`
        isolated_dir = tmp_path / "isolated_db"
        isolated_dir.mkdir()
        with patch("venvy.registry.get_venvy_data_dir", return_value=isolated_dir):
            reg = VenvRegistry()
            reg.log_pip_event(env_path=tmp_path / "env1", action="install", packages=["pkg1"])
            reg.log_pip_event(env_path=tmp_path / "env2", action="install", packages=["pkg2"])

            all_events = reg.get_all_events(limit=10)
            assert len(all_events) == 2


# ========================================================================
# PIP OBSERVER
# ========================================================================

class TestPipObserver:
    def test_before_event_returns_snapshot(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        with patch.object(observer, "_get_pip_freeze", return_value=["requests==2.31.0"]):
            with patch.object(observer.registry, "get", return_value=MagicMock(size_mb=100.0)):
                ctx = observer.before_event(tmp_path / ".venv", "install", "flask")

        assert "before_freeze" in ctx
        assert ctx["before_freeze"] == ["requests==2.31.0"]
        assert ctx["size_before_mb"] == 100.0
        assert "start_time" in ctx

    def test_after_event_logs_to_registry(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        context = {
            "start_time": time.time() - 5,
            "before_freeze": ["requests==2.31.0"],
            "size_before_mb": 100.0,
        }

        with patch.object(observer, "_get_pip_freeze", return_value=["requests==2.31.0", "flask==3.0.0"]):
            with patch.object(observer.registry, "refresh_metadata", return_value=True):
                result = observer.after_event(
                    tmp_path / ".venv", context, exit_code=0,
                    action="install", packages_str="flask"
                )

        assert result["event_id"] is not None
        assert "flask==3.0.0" in result["packages_added"]
        assert result["action"] == "install"

    def test_after_event_computes_diff(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        context = {
            "start_time": time.time(),
            "before_freeze": ["requests==2.31.0", "old-pkg==1.0"],
            "size_before_mb": 50.0,
        }

        with patch.object(observer, "_get_pip_freeze", return_value=["requests==2.31.0", "flask==3.0.0"]):
            with patch.object(observer.registry, "refresh_metadata", return_value=True):
                result = observer.after_event(
                    tmp_path / ".venv", context, exit_code=0,
                    action="install", packages_str="flask"
                )

        assert "flask==3.0.0" in result["packages_added"]
        assert "old-pkg==1.0" in result["packages_removed"]

    def test_alert_on_many_packages(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        # 25 packages added
        before = []
        after = [f"pkg{i}==1.0" for i in range(25)]

        context = {"start_time": time.time(), "before_freeze": before, "size_before_mb": 100.0}

        with patch.object(observer, "_get_pip_freeze", return_value=after):
            with patch.object(observer.registry, "refresh_metadata", return_value=True):
                result = observer.after_event(
                    tmp_path / ".venv", context, exit_code=0,
                    action="install", packages_str="big-framework"
                )

        assert result["alert_level"] == "warn"
        assert "25" in result["alert_message"]

    def test_no_alert_normal_install(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        context = {"start_time": time.time(), "before_freeze": [], "size_before_mb": 50.0}

        with patch.object(observer, "_get_pip_freeze", return_value=["flask==3.0.0", "jinja2==3.1.0"]):
            with patch.object(observer.registry, "refresh_metadata", return_value=True):
                result = observer.after_event(
                    tmp_path / ".venv", context, exit_code=0,
                    action="install", packages_str="flask"
                )

        assert result["alert_level"] is None

    def test_alert_on_failed_install(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        context = {"start_time": time.time(), "before_freeze": [], "size_before_mb": 50.0}

        with patch.object(observer, "_get_pip_freeze", return_value=[]):
            with patch.object(observer.registry, "refresh_metadata", return_value=True):
                result = observer.after_event(
                    tmp_path / ".venv", context, exit_code=1,
                    action="install", packages_str="broken-pkg"
                )

        assert result["alert_level"] == "warn"
        assert result["action"] == "install-failed"

    def test_status_report_structure(self, tmp_path):
        from venvy.pip_observer import PipObserver

        with patch("venvy.registry.get_venvy_data_dir", return_value=tmp_path):
            observer = PipObserver()

        report = observer.get_status_report(tmp_path / ".venv")
        assert "health" in report
        assert "alerts" in report
        assert "recent_events" in report
        assert report["health"] in ("good", "warn", "critical")


# ========================================================================
# CLAUDE.md GENERATOR
# ========================================================================

class TestClaudeGenerator:
    def test_template_renders(self, tmp_path):
        from venvy.claude_generator import ClaudeInstructionGenerator

        gen = ClaudeInstructionGenerator()
        content = gen.generate(tmp_path, {
            "python_version": "3.11.5",
            "path": str(tmp_path / ".venv"),
            "package_count": 42,
        })

        assert "Agent Instructions" in content
        assert "venvy" in content
        assert "3.11" in content

    def test_contains_project_info(self, tmp_path):
        from venvy.claude_generator import ClaudeInstructionGenerator

        gen = ClaudeInstructionGenerator()
        content = gen.generate(tmp_path, {
            "python_version": "3.10.12",
            "path": str(tmp_path / ".venv"),
            "package_count": 15,
        })

        assert "3.10" in content
        assert "15" in content
        assert "venvy status --json" in content
        assert "venvy safe-install" in content

    def test_exit_codes_documented(self, tmp_path):
        from venvy.claude_generator import ClaudeInstructionGenerator

        gen = ClaudeInstructionGenerator()
        content = gen.generate(tmp_path, {"python_version": "3.11", "path": ".", "package_count": 0})

        assert "Exit Codes" in content
        assert "| 0 | Success |" in content


# ========================================================================
# INIT MANAGER
# ========================================================================

class TestInitManager:
    def test_init_generates_claude_md(self, tmp_path):
        from venvy.init_manager import InitManager

        mgr = InitManager()

        # Mock ensure to return env info
        env_info = {"status": "created", "path": str(tmp_path / ".venv"), "python_version": "3.11.0", "package_count": 0, "_exit_code": 0}

        with patch.object(mgr, "_ensure_environment", return_value=env_info):
            with patch.object(mgr, "_install_pip_hook", return_value={"status": "skipped", "detail": "test"}):
                with patch.object(mgr, "_configure_pip", return_value={"status": "skipped", "detail": "test"}):
                    with patch.object(mgr, "_initial_checkpoint", return_value={"status": "skipped", "detail": "test"}):
                        result = mgr.initialize_project(tmp_path, install_hook=False, configure_pip=False)

        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "venvy" in content
        assert "3.11" in content

    def test_init_creates_venvy_json(self, tmp_path):
        from venvy.init_manager import InitManager

        mgr = InitManager()
        env_info = {"status": "created", "path": str(tmp_path / ".venv"), "python_version": "3.11.0", "package_count": 0, "_exit_code": 0}

        with patch.object(mgr, "_ensure_environment", return_value=env_info):
            with patch.object(mgr, "_install_pip_hook", return_value={"status": "skipped", "detail": "test"}):
                with patch.object(mgr, "_configure_pip", return_value={"status": "skipped", "detail": "test"}):
                    with patch.object(mgr, "_initial_checkpoint", return_value={"status": "skipped", "detail": "test"}):
                        result = mgr.initialize_project(tmp_path, install_hook=False, configure_pip=False)

        venvy_json = tmp_path / "venvy.json"
        assert venvy_json.exists()
        data = json.loads(venvy_json.read_text())
        assert "python_version" in data
        assert "packages" in data

    def test_init_no_overwrite_without_force(self, tmp_path):
        from venvy.init_manager import InitManager

        # Pre-create CLAUDE.md with custom content
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("my custom instructions")

        mgr = InitManager()
        env_info = {"status": "created", "path": str(tmp_path / ".venv"), "python_version": "3.11.0", "package_count": 0, "_exit_code": 0}

        with patch.object(mgr, "_ensure_environment", return_value=env_info):
            with patch.object(mgr, "_install_pip_hook", return_value={"status": "skipped", "detail": "test"}):
                with patch.object(mgr, "_configure_pip", return_value={"status": "skipped", "detail": "test"}):
                    with patch.object(mgr, "_initial_checkpoint", return_value={"status": "skipped", "detail": "test"}):
                        result = mgr.initialize_project(tmp_path, install_hook=False, configure_pip=False, force=False)

        # Should NOT be overwritten
        assert claude_md.read_text() == "my custom instructions"
        assert result["steps"]["claude_md"]["status"] == "skipped"

    def test_init_force_overwrites(self, tmp_path):
        from venvy.init_manager import InitManager

        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("old content")

        mgr = InitManager()
        env_info = {"status": "created", "path": str(tmp_path / ".venv"), "python_version": "3.11.0", "package_count": 0, "_exit_code": 0}

        with patch.object(mgr, "_ensure_environment", return_value=env_info):
            with patch.object(mgr, "_install_pip_hook", return_value={"status": "skipped", "detail": "test"}):
                with patch.object(mgr, "_configure_pip", return_value={"status": "skipped", "detail": "test"}):
                    with patch.object(mgr, "_initial_checkpoint", return_value={"status": "skipped", "detail": "test"}):
                        result = mgr.initialize_project(tmp_path, install_hook=False, configure_pip=False, force=True)

        assert claude_md.read_text() != "old content"
        assert "venvy" in claude_md.read_text()
        assert result["steps"]["claude_md"]["status"] == "created"


# ========================================================================
# CLI COMMANDS
# ========================================================================

class TestInitCLI:
    def test_init_json_output(self, runner, tmp_path):
        with patch("venvy.init_manager.InitManager.initialize_project") as mock_init:
            mock_init.return_value = {
                "steps": {
                    "ensure": {"status": "created", "path": str(tmp_path / ".venv")},
                    "pip_hook": {"status": "skipped", "detail": "test"},
                    "claude_md": {"status": "created", "detail": "CLAUDE.md"},
                },
                "_exit_code": 0,
            }
            result = runner.invoke(main, ["--json", "init"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert "ensure" in data

    def test_status_json_output(self, runner, tmp_path):
        with patch("venvy.pip_observer.PipObserver.get_status_report") as mock_status:
            mock_status.return_value = {
                "health": "good",
                "alerts": [],
                "recent_events": [],
                "event_summary": {},
            }
            with patch("venvy.cli._auto_detect_env", return_value=tmp_path / ".venv"):
                result = runner.invoke(main, ["--json", "status"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["health"] == "good"

    def test_pip_event_no_venv(self, runner):
        with patch.dict("os.environ", {}, clear=True):
            import os
            env = os.environ.copy()
            env.pop("VIRTUAL_ENV", None)
            with patch.dict("os.environ", env, clear=True):
                result = runner.invoke(main, ["--json", "_pip-event", "--before"])

        data = json.loads(result.output)
        assert data.get("skipped") is True


# ========================================================================
# SHELL INTEGRATION
# ========================================================================

class TestShellIntegration:
    def test_powershell_pip_wrapper_contains_markers(self):
        from venvy.shell_integration import generate_powershell_pip_wrapper
        wrapper = generate_powershell_pip_wrapper()
        assert "venvy pip observer - START" in wrapper
        assert "venvy pip observer - END" in wrapper
        assert "venvy _pip-event" in wrapper
        assert "pip.exe" in wrapper

    def test_bash_pip_wrapper_contains_markers(self):
        from venvy.shell_integration import generate_bash_pip_wrapper
        wrapper = generate_bash_pip_wrapper()
        assert "venvy pip observer - START" in wrapper
        assert "venvy pip observer - END" in wrapper
        assert "venvy _pip-event" in wrapper

    def test_pip_wrapper_dispatch(self):
        from venvy.shell_integration import generate_pip_wrapper
        ps_wrapper = generate_pip_wrapper("powershell")
        assert "pip.exe" in ps_wrapper

        bash_wrapper = generate_pip_wrapper("bash")
        assert "command" in bash_wrapper

    def test_pip_config_path_returns_path(self):
        from venvy.shell_integration import get_pip_config_path
        path = get_pip_config_path()
        assert path is not None
        assert "pip" in str(path).lower()
