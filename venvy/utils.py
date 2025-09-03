"""
Cross-platform utilities for venvy
"""
import os
import sys
import platform
from pathlib import Path
from typing import List, Optional, Iterator
import subprocess
import json
from datetime import datetime


def get_platform_info() -> dict:
    """Get platform-specific information"""
    return {
        "system": platform.system(),
        "platform": sys.platform,
        "architecture": platform.architecture()[0],
        "python_version": platform.python_version(),
        "is_windows": sys.platform.startswith("win"),
        "is_macos": sys.platform == "darwin",
        "is_linux": sys.platform.startswith("linux"),
    }


def get_home_directory() -> Path:
    """Get user's home directory in a cross-platform way"""
    return Path.home()


def get_common_venv_locations() -> List[Path]:
    """Get common locations where virtual environments are typically stored"""
    home = get_home_directory()
    locations = [
        home,  # Many people put venvs in home directory
        home / "venvs",  # Common venv storage location
        home / ".virtualenvs",  # virtualenvwrapper default
        home / "envs",  # Alternative common name
        home / "projects",  # Project-based environments
    ]
    
    # Add conda locations
    conda_locations = get_conda_locations()
    locations.extend(conda_locations)
    
    # Add system-specific locations
    platform_info = get_platform_info()
    if platform_info["is_windows"]:
        # Windows-specific locations
        locations.extend([
            Path("C:\\ProgramData\\Miniconda3\\envs"),
            Path("C:\\ProgramData\\Anaconda3\\envs"),
        ])
    elif platform_info["is_macos"]:
        # macOS-specific locations
        locations.extend([
            Path("/opt/miniconda3/envs"),
            Path("/opt/anaconda3/envs"),
            home / "miniconda3" / "envs",
            home / "anaconda3" / "envs",
        ])
    elif platform_info["is_linux"]:
        # Linux-specific locations
        locations.extend([
            Path("/opt/miniconda3/envs"),
            Path("/opt/anaconda3/envs"),
            home / "miniconda3" / "envs",
            home / "anaconda3" / "envs",
        ])
    
    # Filter to only existing directories
    return [loc for loc in locations if loc.exists() and loc.is_dir()]


def get_conda_locations() -> List[Path]:
    """Get conda environment locations"""
    locations = []
    home = get_home_directory()
    
    # Try to get conda info
    try:
        result = subprocess.run(
            ["conda", "info", "--json"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        if result.returncode == 0:
            conda_info = json.loads(result.stdout)
            # Add envs_dirs from conda info
            for env_dir in conda_info.get("envs_dirs", []):
                locations.append(Path(env_dir))
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        # Conda not available or command failed, use common locations
        pass
    
    # Add common conda locations as fallback
    common_conda_locations = [
        home / "miniconda3" / "envs",
        home / "anaconda3" / "envs", 
        home / "miniforge3" / "envs",
        home / "mambaforge" / "envs",
    ]
    
    locations.extend(common_conda_locations)
    return [loc for loc in locations if loc.exists() and loc.is_dir()]


def get_directory_size(path: Path) -> int:
    """
    Calculate total size of directory in bytes
    Handles permission errors gracefully
    """
    total_size = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total_size += item.stat().st_size
            except (OSError, PermissionError):
                # Skip files we can't access
                continue
    except (OSError, PermissionError):
        # Skip directories we can't access
        pass
    return total_size


def safe_read_file(file_path: Path, encoding: str = "utf-8") -> Optional[str]:
    """Safely read a file, returning None if it fails"""
    try:
        return file_path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError, PermissionError):
        return None


def safe_run_command(command: List[str], timeout: int = 10) -> Optional[str]:
    """Safely run a command and return stdout, None if it fails"""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False  # Don't raise exception on non-zero exit
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def get_file_timestamps(path: Path) -> dict:
    """Get file/directory timestamps safely"""
    try:
        stat = path.stat()
        return {
            "created": datetime.fromtimestamp(stat.st_ctime),
            "modified": datetime.fromtimestamp(stat.st_mtime),
            "accessed": datetime.fromtimestamp(stat.st_atime),
        }
    except (OSError, PermissionError):
        return {}


def is_python_executable(path: Path) -> bool:
    """Check if a path points to a Python executable"""
    if not path.exists() or not path.is_file():
        return False
    
    # Check by name
    name = path.name.lower()
    if name in ("python", "python.exe", "python3", "python3.exe"):
        return True
    
    # Check if it's executable and responds to --version
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "python" in result.stdout.lower() or "python" in result.stderr.lower()
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def find_python_executable(env_path: Path) -> Optional[Path]:
    """Find the Python executable in an environment"""
    platform_info = get_platform_info()
    
    # Determine the bin/Scripts directory
    if platform_info["is_windows"]:
        bin_dirs = ["Scripts", "."]
        python_names = ["python.exe", "python3.exe"]
    else:
        bin_dirs = ["bin", "."]
        python_names = ["python", "python3"]
    
    for bin_dir in bin_dirs:
        bin_path = env_path / bin_dir
        if bin_path.exists():
            for python_name in python_names:
                python_path = bin_path / python_name
                if is_python_executable(python_path):
                    return python_path
    
    return None


def get_python_version(python_executable: Path) -> Optional[str]:
    """Get Python version from executable"""
    try:
        result = subprocess.run(
            [str(python_executable), "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Output usually like "Python 3.9.7"
            version_line = result.stdout.strip() or result.stderr.strip()
            if "python" in version_line.lower():
                return version_line.split()[-1]  # Get just the version number
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def normalize_path(path: Path) -> Path:
    """Normalize a path for consistent comparison"""
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        # resolve() can fail on broken symlinks
        return path.absolute()


def is_environment_active(env_path: Path) -> bool:
    """Check if an environment appears to be currently active"""
    # This is a simple heuristic - check if the environment's python
    # is the same as the currently running python
    try:
        current_python = Path(sys.executable).resolve()
        env_python = find_python_executable(env_path)
        if env_python:
            return current_python == env_python.resolve()
    except (OSError, RuntimeError):
        pass
    return False


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size string"""
    if size_bytes == 0:
        return "0 B"
    
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            if unit == 'B':
                return f"{int(size)} {unit}"
            else:
                return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def days_since_timestamp(timestamp: datetime) -> int:
    """Calculate days since a timestamp"""
    return (datetime.now() - timestamp).days


def create_directory_safely(path: Path) -> bool:
    """Create a directory safely, returning True if successful"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except (OSError, PermissionError):
        return False


def get_venvy_data_dir() -> Path:
    """Get venvy's data directory for storing cache and config"""
    platform_info = get_platform_info()
    home = get_home_directory()
    
    if platform_info["is_windows"]:
        # Use AppData on Windows
        data_dir = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "venvy"
    elif platform_info["is_macos"]:
        # Use ~/Library/Application Support on macOS
        data_dir = home / "Library" / "Application Support" / "venvy"
    else:
        # Use ~/.config on Linux/Unix
        config_home = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
        data_dir = Path(config_home) / "venvy"
    
    # Create directory if it doesn't exist
    create_directory_safely(data_dir)
    return data_dir