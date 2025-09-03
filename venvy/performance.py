"""
Performance optimizations for venvy
Fast scanning, caching, and parallel processing
"""
import os
import json
import threading
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import hashlib

from venvy.models import EnvironmentInfo
from venvy.utils import get_venvy_data_dir, create_directory_safely


class FastScanner:
    """Fast environment scanner with intelligent optimizations"""
    
    def __init__(self, max_depth: int = 4, timeout_per_location: int = 120):
        self.max_depth = max_depth
        self.timeout_per_location = timeout_per_location  # Increased to 2 minutes
        self.cache_file = get_venvy_data_dir() / "discovery_cache.json"
        self.cache_ttl_hours = 6  # Cache valid for 6 hours
        
    def fast_discover_venvs(self, base_path: Path, max_workers: int = 4) -> List[Path]:
        """Fast discovery of virtual environments with depth limiting"""
        venv_paths = []
        
        # Quick common location checks first
        common_venv_names = {'venv', '.venv', 'env', '.env', 'virtualenv'}
        for name in common_venv_names:
            candidate = base_path / name
            if self._is_venv_directory(candidate):
                venv_paths.append(candidate)
        
        # Parallel scanning with depth limit and timeout
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {}
            
            # Submit scanning tasks for subdirectories
            try:
                for item in base_path.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        future = executor.submit(self._scan_directory_for_venvs, item)
                        future_to_path[future] = item
                        
                # Collect results with timeout
                for future in as_completed(future_to_path, timeout=self.timeout_per_location):
                    try:
                        paths = future.result(timeout=30)  # 30 second timeout per directory
                        venv_paths.extend(paths)
                    except TimeoutError:
                        # Skip slow directories
                        continue
                    except Exception:
                        # Skip problematic directories
                        continue
                        
            except (PermissionError, OSError):
                pass
                
        return venv_paths
    
    def _scan_directory_for_venvs(self, directory: Path, current_depth: int = 0) -> List[Path]:
        """Scan a directory for venvs with depth limiting"""
        if current_depth >= self.max_depth:
            return []
            
        venv_paths = []
        
        try:
            # Check if this directory itself is a venv
            if self._is_venv_directory(directory):
                venv_paths.append(directory)
                return venv_paths  # Don't scan inside venvs
            
            # Quick check for common venv indicators without full recursion
            for item in directory.iterdir():
                if not item.is_dir():
                    continue
                    
                # Check common venv directory names
                if item.name in {'venv', '.venv', 'env', '.env', 'virtualenv'}:
                    if self._is_venv_directory(item):
                        venv_paths.append(item)
                        
                # Recursively scan non-venv directories (with depth limit)
                elif current_depth < self.max_depth - 1:
                    try:
                        sub_venvs = self._scan_directory_for_venvs(item, current_depth + 1)
                        venv_paths.extend(sub_venvs)
                    except (PermissionError, OSError):
                        continue
                        
        except (PermissionError, OSError):
            pass
            
        return venv_paths
    
    def _is_venv_directory(self, path: Path) -> bool:
        """Quick check if directory is a virtual environment"""
        if not path.exists() or not path.is_dir():
            return False
            
        # Check for pyvenv.cfg (fastest check)
        if (path / "pyvenv.cfg").exists():
            return True
            
        # Check for Scripts/bin directory structure
        has_scripts = (path / "Scripts").exists() or (path / "bin").exists()
        if not has_scripts:
            return False
            
        # Check for Python executable
        python_paths = [
            path / "Scripts" / "python.exe",
            path / "Scripts" / "python",
            path / "bin" / "python",
            path / "bin" / "python3"
        ]
        
        return any(p.exists() for p in python_paths)


class EnvironmentCache:
    """Caching system for environment analysis results"""
    
    def __init__(self):
        self.cache_dir = get_venvy_data_dir() / "cache"
        create_directory_safely(self.cache_dir)
        self.cache_file = self.cache_dir / "env_cache.json"
        self.size_cache_file = self.cache_dir / "size_cache.json"
        self.ttl_hours = 24  # Cache valid for 24 hours
        
    def get_cached_environments(self) -> Optional[List[Dict]]:
        """Get cached environment list if still valid"""
        if not self.cache_file.exists():
            return None
            
        try:
            with open(self.cache_file, 'r') as f:
                cache_data = json.load(f)
                
            # Check if cache is still valid
            cached_time = datetime.fromisoformat(cache_data.get('cached_at', ''))
            if datetime.now() - cached_time > timedelta(hours=self.ttl_hours):
                return None
                
            return cache_data.get('environments', [])
        except Exception:
            return None
    
    def cache_environments(self, environments: List[EnvironmentInfo]):
        """Cache environment analysis results"""
        try:
            cache_data = {
                'cached_at': datetime.now().isoformat(),
                'environments': [env.to_dict() for env in environments]
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception:
            pass  # Fail silently if caching fails
    
    def get_cached_size(self, path: Path) -> Optional[int]:
        """Get cached directory size"""
        if not self.size_cache_file.exists():
            return None
            
        try:
            path_hash = hashlib.md5(str(path).encode()).hexdigest()
            
            with open(self.size_cache_file, 'r') as f:
                cache_data = json.load(f)
            
            entry = cache_data.get(path_hash)
            if not entry:
                return None
                
            # Check if cache is still valid (based on directory modification time)
            cached_mtime = entry.get('mtime', 0)
            current_mtime = path.stat().st_mtime if path.exists() else 0
            
            if cached_mtime == current_mtime:
                return entry.get('size')
        except Exception:
            pass
            
        return None
    
    def cache_size(self, path: Path, size: int):
        """Cache directory size"""
        try:
            path_hash = hashlib.md5(str(path).encode()).hexdigest()
            
            # Load existing cache
            cache_data = {}
            if self.size_cache_file.exists():
                with open(self.size_cache_file, 'r') as f:
                    cache_data = json.load(f)
            
            # Add/update entry
            cache_data[path_hash] = {
                'size': size,
                'mtime': path.stat().st_mtime if path.exists() else 0,
                'path': str(path)  # For debugging
            }
            
            # Save cache
            with open(self.size_cache_file, 'w') as f:
                json.dump(cache_data, f)
                
        except Exception:
            pass  # Fail silently
    
    def clear_cache(self):
        """Clear all cached data"""
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
            if self.size_cache_file.exists():
                self.size_cache_file.unlink()
        except Exception:
            pass


class ParallelAnalyzer:
    """Parallel environment analysis for better performance"""
    
    def __init__(self, max_workers: int = None):
        # Use reasonable number of workers (not too many to avoid thrashing)
        self.max_workers = max_workers or min(4, (os.cpu_count() or 1))
    
    def analyze_environments_parallel(self, environments: List[EnvironmentInfo], 
                                    analysis_func, timeout_per_env: int = 60) -> List[EnvironmentInfo]:
        """Analyze environments in parallel with timeout"""
        analyzed_environments = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all analysis tasks
            future_to_env = {
                executor.submit(self._safe_analyze, env, analysis_func): env 
                for env in environments
            }
            
            # Collect results with timeout
            for future in as_completed(future_to_env, timeout=timeout_per_env * len(environments)):
                try:
                    result = future.result(timeout=timeout_per_env)
                    if result:
                        analyzed_environments.append(result)
                except TimeoutError:
                    # Skip environments that take too long
                    env = future_to_env[future]
                    print(f"Skipped slow environment: {env.name}")
                except Exception as e:
                    # Skip problematic environments
                    env = future_to_env[future]
                    print(f"Error analyzing {env.name}: {e}")
        
        return analyzed_environments
    
    def _safe_analyze(self, env: EnvironmentInfo, analysis_func) -> Optional[EnvironmentInfo]:
        """Safely analyze an environment with error handling"""
        try:
            return analysis_func(env)
        except Exception:
            # Return the original environment if analysis fails
            return env


class QuickCommands:
    """Optimized versions of common commands"""
    
    @staticmethod
    def quick_list(max_results: int = 50) -> List[EnvironmentInfo]:
        """Quick list command that shows only the most important environments"""
        from venvy.discovery import EnvironmentDiscovery
        
        # Use cache first
        cache = EnvironmentCache()
        cached = cache.get_cached_environments()
        if cached:
            return [EnvironmentInfo(**env_data) for env_data in cached[:max_results]]
        
        # Fast discovery with limits
        discovery = EnvironmentDiscovery()
        scanner = FastScanner(max_depth=3)  # Limit search depth
        
        # Search only common locations
        common_paths = [
            Path.home(),
            Path.home() / "venvs", 
            Path.home() / ".virtualenvs"
        ]
        
        environments = []
        for path in common_paths:
            if path.exists():
                venv_paths = scanner.fast_discover_venvs(path, max_workers=2)
                for venv_path in venv_paths[:max_results]:  # Limit results per location
                    env_info = discovery._analyze_single_environment(venv_path)
                    if env_info:
                        environments.append(env_info)
                        
        # Cache results
        cache.cache_environments(environments)
        return environments
    
    @staticmethod
    def quick_size() -> List[EnvironmentInfo]:
        """Quick size analysis focusing on largest environments"""
        environments = QuickCommands.quick_list()
        
        # Use cached sizes when available
        cache = EnvironmentCache() 
        
        for env in environments:
            cached_size = cache.get_cached_size(env.path)
            if cached_size is not None:
                env.size_bytes = cached_size
            else:
                # Calculate size for uncached environments
                from venvy.utils import get_directory_size
                size = get_directory_size(env.path)
                env.size_bytes = size
                cache.cache_size(env.path, size)
        
        # Return sorted by size
        return sorted(environments, key=lambda e: e.size_bytes or 0, reverse=True)