"""
venvy - Intelligent Python Virtual Environment Manager

A cross-platform tool for discovering, analyzing, and managing Python virtual environments
with intelligence and style.
"""

__version__ = "0.1.1"
__author__ = "Pranav Kumaar"

from venvy.discovery import EnvironmentDiscovery
from venvy.analysis import EnvironmentAnalysis

__all__ = ["EnvironmentDiscovery", "EnvironmentAnalysis"]