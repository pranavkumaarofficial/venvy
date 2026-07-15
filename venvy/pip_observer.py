"""
Pip event observer for venvy's active observability layer.

Called by the shell pip wrapper hook. Must be fast (<500ms for typical operations).
"""
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from venvy.registry import VenvRegistry
from venvy.utils import get_platform_info


class PipObserver:
    """Observes pip install/uninstall events and logs them to the registry."""

    ALERT_SIZE_MB = 500
    ALERT_PACKAGE_COUNT = 20
    ALERT_TOTAL_SIZE_MB = 2000

    def __init__(self):
        self.registry = VenvRegistry()

    def before_event(self, env_path: Path, action: str, packages_str: str) -> Dict:
        """Snapshot state before pip runs. Returns context dict."""
        env_path = Path(env_path).resolve()
        context = {
            "start_time": time.time(),
            "action": action,
            "packages_str": packages_str,
        }

        # Capture pip freeze
        freeze = self._get_pip_freeze(env_path)
        context["before_freeze"] = freeze

        # Use cached size from registry (fast, no disk walk)
        record = self.registry.get(str(env_path))
        context["size_before_mb"] = record.size_mb if record and record.size_mb else None

        return context

    def after_event(self, env_path: Path, context: Dict, exit_code: int,
                    action: str, packages_str: str) -> Dict:
        """Diff state after pip runs. Log event. Check alerts. Returns event summary."""
        env_path = Path(env_path).resolve()
        start_time = context.get("start_time", time.time())
        duration = time.time() - start_time

        # Capture current freeze
        after_freeze = self._get_pip_freeze(env_path)
        before_freeze = context.get("before_freeze", [])

        # Compute diff
        before_set = set(before_freeze)
        after_set = set(after_freeze)
        packages_added = sorted(after_set - before_set)
        packages_removed = sorted(before_set - after_set)

        # Parse package names from args
        packages = [p for p in packages_str.split() if p and not p.startswith("-")]

        # Size estimation: use cached before, don't walk disk
        size_before_mb = context.get("size_before_mb")
        size_after_mb = None
        size_delta_mb = None

        # Rough estimate: ~5MB per new package average
        if packages_added:
            estimated_delta = len(packages_added) * 5.0
            size_delta_mb = estimated_delta
            if size_before_mb is not None:
                size_after_mb = size_before_mb + estimated_delta

        # Determine action for logging
        if exit_code != 0 and action == "install":
            log_action = "install-failed"
        else:
            log_action = action

        # Check alert thresholds
        total_env_size = size_after_mb or size_before_mb or 0
        alert_level, alert_message = self._check_alerts(
            packages_added, size_delta_mb, total_env_size, exit_code
        )

        # Log to registry
        event_id = self.registry.log_pip_event(
            env_path=env_path,
            action=log_action,
            packages=packages if packages else None,
            pip_args=packages_str,
            exit_code=exit_code,
            before_freeze=before_freeze if before_freeze else None,
            after_freeze=after_freeze if after_freeze else None,
            packages_added=packages_added if packages_added else None,
            packages_removed=packages_removed if packages_removed else None,
            size_before_mb=size_before_mb,
            size_after_mb=size_after_mb,
            size_delta_mb=size_delta_mb,
            duration_seconds=round(duration, 2),
            alert_level=alert_level,
            alert_message=alert_message,
        )

        # Refresh registry metadata (lightweight: just package count)
        try:
            self.registry.refresh_metadata(env_path)
        except Exception:
            pass

        return {
            "event_id": event_id,
            "action": log_action,
            "packages_added": packages_added,
            "packages_removed": packages_removed,
            "size_delta_mb": size_delta_mb,
            "duration_seconds": round(duration, 2),
            "alert_level": alert_level,
            "alert_message": alert_message,
        }

    def get_status_report(self, env_path: Optional[Path] = None) -> Dict:
        """Health report for agents. Called by `venvy status`."""
        report = {
            "health": "good",
            "alerts": [],
            "recent_events": [],
            "event_summary": {},
        }

        if env_path:
            env_path = Path(env_path).resolve()

            # Env info from registry
            record = self.registry.get(str(env_path))
            if record:
                report["env_path"] = record.path
                report["python_version"] = record.python_version
                report["total_size_mb"] = record.size_mb
                report["package_count"] = record.package_count

            # Recent events
            events = self.registry.get_recent_events(env_path, limit=10)
            report["recent_events"] = [
                {
                    "action": e.action,
                    "packages": e.packages,
                    "packages_added_count": len(e.packages_added) if e.packages_added else 0,
                    "size_delta_mb": e.size_delta_mb,
                    "exit_code": e.exit_code,
                    "alert_level": e.alert_level,
                    "created_at": e.created_at,
                }
                for e in events
            ]

            # Event summary
            report["event_summary"] = self.registry.get_event_summary(env_path)

            # Alerts
            alerts = self.registry.get_alerts(env_path, limit=5)
            report["alerts"] = [
                {
                    "level": a.alert_level,
                    "message": a.alert_message,
                    "action": a.action,
                    "created_at": a.created_at,
                }
                for a in alerts
            ]

            # Latest checkpoint info
            latest_cp = self.registry.get_latest_checkpoint(env_path)
            if latest_cp:
                report["last_checkpoint"] = latest_cp.name
                report["last_checkpoint_at"] = latest_cp.created_at
                # Count events since checkpoint
                all_events = self.registry.get_recent_events(env_path, limit=100)
                events_since = sum(
                    1 for e in all_events
                    if e.created_at and latest_cp.created_at and e.created_at > latest_cp.created_at
                )
                report["events_since_checkpoint"] = events_since

            # Determine health
            if any(a.alert_level == "critical" for a in alerts):
                report["health"] = "critical"
            elif any(a.alert_level == "warn" for a in alerts):
                report["health"] = "warn"

        else:
            # Global status across all environments
            all_events = self.registry.get_all_events(limit=10)
            report["recent_events"] = [
                {
                    "env_path": e.env_path,
                    "action": e.action,
                    "packages": e.packages,
                    "alert_level": e.alert_level,
                    "created_at": e.created_at,
                }
                for e in all_events
            ]

            alerts = self.registry.get_alerts(limit=5)
            report["alerts"] = [
                {
                    "level": a.alert_level,
                    "message": a.alert_message,
                    "env_path": a.env_path,
                    "created_at": a.created_at,
                }
                for a in alerts
            ]

            if any(a.alert_level == "critical" for a in alerts):
                report["health"] = "critical"
            elif any(a.alert_level == "warn" for a in alerts):
                report["health"] = "warn"

        return report

    def _check_alerts(self, packages_added: List[str],
                      size_delta_mb: Optional[float],
                      total_env_size_mb: float,
                      exit_code: int) -> Tuple[Optional[str], Optional[str]]:
        """Rule-based alert thresholds. Returns (level, message) or (None, None)."""
        if exit_code != 0:
            return ("warn", f"pip exited with code {exit_code}")

        if size_delta_mb and size_delta_mb > self.ALERT_SIZE_MB:
            return ("warn", f"Large install: estimated +{size_delta_mb:.0f}MB")

        if len(packages_added) > self.ALERT_PACKAGE_COUNT:
            return ("warn", f"Many packages added: {len(packages_added)} new dependencies")

        if total_env_size_mb > self.ALERT_TOTAL_SIZE_MB:
            return ("info", f"Environment is large: {total_env_size_mb:.0f}MB total")

        return (None, None)

    def _get_pip_freeze(self, env_path: Path) -> List[str]:
        """Run pip list --format=freeze. Reuses the same pattern as env_manager."""
        pip_exe = self._find_pip(env_path)
        if not pip_exe:
            return []

        try:
            result = subprocess.run(
                [str(pip_exe), "list", "--format=freeze"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return []

    def _find_pip(self, env_path: Path) -> Optional[Path]:
        """Find pip executable in an environment."""
        platform_info = get_platform_info()
        if platform_info["is_windows"]:
            candidates = [env_path / "Scripts" / "pip.exe", env_path / "Scripts" / "pip3.exe"]
        else:
            candidates = [env_path / "bin" / "pip", env_path / "bin" / "pip3"]

        for c in candidates:
            if c.exists():
                return c
        return None
