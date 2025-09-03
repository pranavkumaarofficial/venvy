"""
Environment discovery engine for venvy
Detects venv, conda, pyenv, and other Python environments across platforms
"""
import re
import json
from pathlib import Path
from typing import List, Iterator, Optional, Dict, Set
from datetime import datetime

from venvy.models import EnvironmentInfo, EnvironmentType
from venvy.utils import (
    get_common_venv_locations,
    get_conda_locations, 
    safe_read_file,
    safe_run_command,
    get_file_timestamps,
    find_python_executable,
    get_python_version,
    normalize_path,
    get_directory_size,
)


class EnvironmentDiscovery:
    """Discovers Python virtual environments across the system"""
    
    def __init__(self, custom_search_paths: Optional[List[Path]] = None):
        self.custom_search_paths = custom_search_paths or []
        self._discovered_environments: Dict[str, EnvironmentInfo] = {}
        self._search_cache: Set[str] = set()
    
    def discover_all(self, search_paths: Optional[List[Path]] = None, use_fast_scan: bool = True) -> List[EnvironmentInfo]:
        """
        Discover all Python environments on the system
        
        Args:
            search_paths: Additional paths to search (optional)
            use_fast_scan: Use optimized scanning (default: True)
            
        Returns:
            List of discovered environments
        """
        # Try cache first for performance
        if use_fast_scan and not search_paths:
            from venvy.performance import EnvironmentCache
            cache = EnvironmentCache()
            cached_envs = cache.get_cached_environments()
            if cached_envs:
                return [self._env_from_dict(env_data) for env_data in cached_envs]
        
        environments = []
        
        # Determine search locations
        if search_paths:
            locations = search_paths
        else:
            locations = self._get_search_locations()
        
        # Use fast scanner if enabled
        if use_fast_scan:
            from venvy.performance import FastScanner
            scanner = FastScanner(max_depth=4, timeout_per_location=120)
            
            for location in locations[:3]:  # Limit to first 3 locations for speed
                if not location.exists() or not location.is_dir():
                    continue
                    
                try:
                    # Fast venv discovery
                    venv_paths = scanner.fast_discover_venvs(location, max_workers=3)
                    for venv_path in venv_paths:
                        env_info = self._analyze_single_environment(venv_path)
                        if env_info:
                            environments.append(env_info)
                    
                    # Quick conda discovery
                    environments.extend(self._discover_conda_environments(location))
                except (PermissionError, OSError, TimeoutError):
                    continue
        else:
            # Original thorough scanning
            for location in locations:
                if not location.exists() or not location.is_dir():
                    continue
                    
                try:
                    environments.extend(self._discover_venv_environments(location))
                    environments.extend(self._discover_conda_environments(location))
                    environments.extend(self._discover_pyenv_environments(location))
                except (PermissionError, OSError):
                    continue
        
        # Remove duplicates
        unique_environments = self._deduplicate_environments(environments)
        
        # Cache results for fast scanning
        if use_fast_scan and unique_environments:
            from venvy.performance import EnvironmentCache
            cache = EnvironmentCache()
            cache.cache_environments(unique_environments)
        
        # Cache in memory
        for env in unique_environments:
            self._discovered_environments[str(env.path)] = env
            
        return unique_environments
    
    def _env_from_dict(self, env_data: Dict) -> EnvironmentInfo:
        """Reconstruct EnvironmentInfo from cached dictionary data"""
        try:
            from venvy.models import EnvironmentType, HealthStatus
            env_type = EnvironmentType(env_data.get('type', 'unknown'))
            health_status = HealthStatus(env_data.get('health_status', 'unknown'))
            
            return EnvironmentInfo(
                name=env_data['name'],
                path=Path(env_data['path']),
                type=env_type,
                python_version=env_data.get('python_version'),
                python_executable=Path(env_data['python_executable']) if env_data.get('python_executable') else None,
                size_bytes=env_data.get('size_bytes'),
                created_date=datetime.fromisoformat(env_data['created_date']) if env_data.get('created_date') else None,
                last_accessed=datetime.fromisoformat(env_data['last_accessed']) if env_data.get('last_accessed') else None,
                last_modified=datetime.fromisoformat(env_data['last_modified']) if env_data.get('last_modified') else None,
                package_count=env_data.get('package_count'),
                packages=env_data.get('packages'),
                pip_version=env_data.get('pip_version'),
                health_status=health_status,
                health_issues=env_data.get('health_issues'),
                activation_count=env_data.get('activation_count'),
                days_since_used=env_data.get('days_since_used'),
                linked_projects=[Path(p) for p in env_data['linked_projects']] if env_data.get('linked_projects') else None,
                is_orphaned=env_data.get('is_orphaned', False),
                conda_env_name=env_data.get('conda_env_name'),
                requirements_files=[Path(f) for f in env_data['requirements_files']] if env_data.get('requirements_files') else None,
            )
        except Exception:
            # Fallback to basic environment info if reconstruction fails
            return EnvironmentInfo(
                name=env_data.get('name', 'unknown'),
                path=Path(env_data.get('path', '/')),
                type=EnvironmentType.UNKNOWN
            )
    
    def discover_by_type(self, env_type: EnvironmentType, search_paths: Optional[List[Path]] = None) -> List[EnvironmentInfo]:
        """Discover environments of a specific type"""
        all_environments = self.discover_all(search_paths)
        return [env for env in all_environments if env.type == env_type]
    
    def find_environment(self, name_or_path: str) -> Optional[EnvironmentInfo]:
        """Find a specific environment by name or path"""
        # Try direct path lookup first
        path = Path(name_or_path)
        if path.exists():
            return self._analyze_single_environment(path)
        
        # Search by name in discovered environments
        all_envs = self.discover_all()
        for env in all_envs:
            if env.name == name_or_path:
                return env
                
        return None
    
    def _get_search_locations(self) -> List[Path]:
        """Get all locations to search for environments"""
        locations = []
        
        # Add common locations
        locations.extend(get_common_venv_locations())
        
        # Add custom search paths
        locations.extend(self.custom_search_paths)
        
        # Remove duplicates and non-existent paths
        unique_locations = []
        seen_paths = set()
        
        for location in locations:
            normalized = normalize_path(location)
            path_str = str(normalized)
            if path_str not in seen_paths and normalized.exists() and normalized.is_dir():
                unique_locations.append(normalized)
                seen_paths.add(path_str)
        
        return unique_locations
    
    def _discover_venv_environments(self, base_path: Path) -> List[EnvironmentInfo]:
        """Discover venv/virtualenv environments by looking for pyvenv.cfg"""
        environments = []
        
        try:
            # Look for pyvenv.cfg files (venv signature)
            for pyvenv_cfg in base_path.rglob("pyvenv.cfg"):
                try:
                    env_path = pyvenv_cfg.parent
                    if self._is_valid_environment_path(env_path):
                        env_info = self._create_venv_info(env_path, pyvenv_cfg)
                        if env_info:
                            environments.append(env_info)
                except (OSError, PermissionError):
                    continue
                    
            # Also check for virtualenv environments (older style)
            environments.extend(self._discover_virtualenv_environments(base_path))
            
        except (OSError, PermissionError):
            pass
            
        return environments
    
    def _discover_virtualenv_environments(self, base_path: Path) -> List[EnvironmentInfo]:
        """Discover older virtualenv environments"""
        environments = []
        
        try:
            for path in base_path.iterdir():
                if not path.is_dir():
                    continue
                    
                # Look for virtualenv signatures
                if self._looks_like_virtualenv(path):
                    env_info = self._create_virtualenv_info(path)
                    if env_info:
                        environments.append(env_info)
                        
        except (OSError, PermissionError):
            pass
            
        return environments
    
    def _discover_conda_environments(self, base_path: Path) -> List[EnvironmentInfo]:
        """Discover conda environments"""
        environments = []
        
        # Method 1: Look for conda-meta directories
        try:
            for conda_meta in base_path.rglob("conda-meta"):
                if conda_meta.is_dir():
                    env_path = conda_meta.parent
                    if self._is_valid_environment_path(env_path):
                        env_info = self._create_conda_info(env_path)
                        if env_info:
                            environments.append(env_info)
        except (OSError, PermissionError):
            pass
        
        # Method 2: Use conda command to list environments
        conda_envs = self._get_conda_environments_from_command()
        environments.extend(conda_envs)
        
        return environments
    
    def _discover_pyenv_environments(self, base_path: Path) -> List[EnvironmentInfo]:
        """Discover pyenv environments"""
        environments = []
        
        # Look for pyenv version files and installations
        try:
            # Check if this looks like a pyenv directory structure
            if (base_path / "versions").exists():
                versions_dir = base_path / "versions"
                for version_path in versions_dir.iterdir():
                    if version_path.is_dir() and self._looks_like_pyenv_version(version_path):
                        env_info = self._create_pyenv_info(version_path)
                        if env_info:
                            environments.append(env_info)
        except (OSError, PermissionError):
            pass
            
        return environments
    
    def _create_venv_info(self, env_path: Path, pyvenv_cfg: Path) -> Optional[EnvironmentInfo]:
        """Create EnvironmentInfo for a venv environment"""
        try:
            # Parse pyvenv.cfg for information
            cfg_content = safe_read_file(pyvenv_cfg)
            python_version = None
            
            if cfg_content:
                # Look for version information
                for line in cfg_content.split('\n'):
                    line = line.strip()
                    if line.startswith('version'):
                        python_version = line.split('=', 1)[1].strip()
                        break
            
            return self._create_environment_info(
                env_path=env_path,
                env_type=EnvironmentType.VENV,
                python_version=python_version
            )
        except Exception:
            return None
    
    def _create_virtualenv_info(self, env_path: Path) -> Optional[EnvironmentInfo]:
        """Create EnvironmentInfo for a virtualenv environment"""
        return self._create_environment_info(
            env_path=env_path,
            env_type=EnvironmentType.VIRTUALENV
        )
    
    def _create_conda_info(self, env_path: Path) -> Optional[EnvironmentInfo]:
        """Create EnvironmentInfo for a conda environment"""
        try:
            # Try to get conda environment name
            conda_env_name = None
            
            # Look for conda-meta/history file which contains env name
            history_file = env_path / "conda-meta" / "history"
            if history_file.exists():
                history_content = safe_read_file(history_file)
                if history_content:
                    # Parse first line which often contains creation info
                    first_line = history_content.split('\n')[0]
                    if 'create' in first_line:
                        # Extract environment name if available
                        match = re.search(r'--name\s+(\S+)', first_line)
                        if match:
                            conda_env_name = match.group(1)
            
            env_info = self._create_environment_info(
                env_path=env_path,
                env_type=EnvironmentType.CONDA
            )
            
            if env_info:
                env_info.conda_env_name = conda_env_name
                
            return env_info
        except Exception:
            return None
    
    def _create_pyenv_info(self, env_path: Path) -> Optional[EnvironmentInfo]:
        """Create EnvironmentInfo for a pyenv environment"""
        return self._create_environment_info(
            env_path=env_path,
            env_type=EnvironmentType.PYENV
        )
    
    def _create_environment_info(self, env_path: Path, env_type: EnvironmentType, python_version: Optional[str] = None) -> Optional[EnvironmentInfo]:
        """Create a complete EnvironmentInfo object"""
        try:
            # Basic information
            name = env_path.name
            
            # Find Python executable
            python_executable = find_python_executable(env_path)
            
            # Get Python version if not provided
            if not python_version and python_executable:
                python_version = get_python_version(python_executable)
            
            # Get timestamps
            timestamps = get_file_timestamps(env_path)
            
            # Create the environment info
            env_info = EnvironmentInfo(
                name=name,
                path=env_path,
                type=env_type,
                python_version=python_version,
                python_executable=python_executable,
                created_date=timestamps.get("created"),
                last_accessed=timestamps.get("accessed"),
                last_modified=timestamps.get("modified"),
            )
            
            return env_info
            
        except Exception:
            return None
    
    def _analyze_single_environment(self, env_path: Path) -> Optional[EnvironmentInfo]:
        """Analyze a single environment path and determine its type"""
        if not env_path.exists() or not env_path.is_dir():
            return None
        
        # Check for venv (pyvenv.cfg)
        pyvenv_cfg = env_path / "pyvenv.cfg"
        if pyvenv_cfg.exists():
            return self._create_venv_info(env_path, pyvenv_cfg)
        
        # Check for conda (conda-meta directory)
        if (env_path / "conda-meta").exists():
            return self._create_conda_info(env_path)
        
        # Check for virtualenv
        if self._looks_like_virtualenv(env_path):
            return self._create_virtualenv_info(env_path)
        
        # Check for pyenv
        if self._looks_like_pyenv_version(env_path):
            return self._create_pyenv_info(env_path)
        
        # Default to unknown type if it has a Python executable
        python_executable = find_python_executable(env_path)
        if python_executable:
            return self._create_environment_info(env_path, EnvironmentType.UNKNOWN)
        
        return None
    
    def _looks_like_virtualenv(self, path: Path) -> bool:
        """Check if a path looks like a virtualenv environment"""
        # Look for typical virtualenv structure
        bin_or_scripts = path / "bin" if (path / "bin").exists() else path / "Scripts"
        
        if not bin_or_scripts.exists():
            return False
        
        # Must have activate script
        activate_files = ["activate", "activate.bat", "activate.ps1"]
        has_activate = any((bin_or_scripts / activate).exists() for activate in activate_files)
        
        # Must have Python executable
        has_python = find_python_executable(path) is not None
        
        return has_activate and has_python
    
    def _looks_like_pyenv_version(self, path: Path) -> bool:
        """Check if a path looks like a pyenv Python version"""
        # Should have bin directory with Python
        bin_dir = path / "bin"
        if not bin_dir.exists():
            return False
        
        # Should have Python executable
        python_executable = find_python_executable(path)
        return python_executable is not None
    
    def _is_valid_environment_path(self, env_path: Path) -> bool:
        """Check if a path is a valid environment (not system Python, etc.)"""
        # Skip system Python locations
        system_paths = {
            "/usr/bin",
            "/usr/local/bin", 
            "/System/Library/Frameworks/Python.framework",
            "C:\\Windows\\System32",
            "C:\\Program Files",
        }
        
        path_str = str(env_path).lower()
        for system_path in system_paths:
            if system_path.lower() in path_str:
                return False
        
        # Skip if path is too deep (probably not an environment root)
        if len(env_path.parts) > 10:  # Reasonable depth limit
            return False
            
        return True
    
    def _get_conda_environments_from_command(self) -> List[EnvironmentInfo]:
        """Get conda environments using conda command"""
        environments = []
        
        try:
            # Try conda env list --json
            output = safe_run_command(["conda", "env", "list", "--json"])
            if output:
                conda_data = json.loads(output)
                for env_path_str in conda_data.get("envs", []):
                    env_path = Path(env_path_str)
                    if env_path.exists() and self._is_valid_environment_path(env_path):
                        env_info = self._create_conda_info(env_path)
                        if env_info:
                            environments.append(env_info)
        except (json.JSONDecodeError, Exception):
            pass
        
        return environments
    
    def _deduplicate_environments(self, environments: List[EnvironmentInfo]) -> List[EnvironmentInfo]:
        """Remove duplicate environments based on normalized paths"""
        seen_paths = set()
        unique_environments = []
        
        for env in environments:
            normalized_path = str(normalize_path(env.path))
            if normalized_path not in seen_paths:
                seen_paths.add(normalized_path)
                unique_environments.append(env)
        
        return unique_environments