"""
venvy - Fast Virtual Environment Manager

A cross-platform tool for tracking and managing Python virtual environments
using registry-based lookups instead of slow filesystem scanning.
"""

__version__ = "0.2.0"
__author__ = "Pranav Kumaar"

from venvy.discovery import EnvironmentDiscovery
from venvy.analysis import EnvironmentAnalysis
from venvy.registry import VenvRegistry

__all__ = ["EnvironmentDiscovery", "EnvironmentAnalysis", "VenvRegistry"]