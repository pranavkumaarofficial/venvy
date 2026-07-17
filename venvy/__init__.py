"""
venvy - Offline Python supply-chain security audit + agent-safe environment manager.

Scan every virtual environment for known-vulnerable and malicious packages, fully
offline, with structured JSON output and semantic exit codes for CI and AI agents.
Also provides a lightweight environment registry with checkpoint/rollback.
"""

# Single source of truth for the version is the installed package metadata, so
# `venvy --version` can never drift from what pip installed. The fallback is only
# used when running from a source tree that has not been pip-installed.
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    try:
        __version__ = _pkg_version("venvy")
    except PackageNotFoundError:
        __version__ = "0.5.1"
except ImportError:  # pragma: no cover - importlib.metadata is stdlib on 3.8+
    __version__ = "0.5.1"

__author__ = "Pranav Kumaar"

from venvy.discovery import EnvironmentDiscovery
from venvy.analysis import EnvironmentAnalysis
from venvy.registry import VenvRegistry
from venvy.env_manager import EnvironmentManager

__all__ = ["EnvironmentDiscovery", "EnvironmentAnalysis", "VenvRegistry", "EnvironmentManager"]
