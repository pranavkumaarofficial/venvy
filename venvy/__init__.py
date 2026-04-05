"""
venvy - Agent-Safe Python Virtual Environment Manager

A cross-platform tool for tracking, creating, and managing Python virtual
environments. Designed as the environment layer for AI coding agents with
structured JSON output, checkpoint/rollback, and local AI error analysis.
"""

__version__ = "0.4.0"
__author__ = "Pranav Kumaar"

from venvy.discovery import EnvironmentDiscovery
from venvy.analysis import EnvironmentAnalysis
from venvy.registry import VenvRegistry
from venvy.env_manager import EnvironmentManager

__all__ = ["EnvironmentDiscovery", "EnvironmentAnalysis", "VenvRegistry", "EnvironmentManager"]
