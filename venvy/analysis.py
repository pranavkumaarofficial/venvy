"""
Environment analysis engine for venvy
Analyzes size, usage patterns, health, and provides intelligent insights
"""
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import Counter

from venvy.models import (
    EnvironmentInfo, 
    HealthStatus, 
    CleanupSuggestion, 
    SystemSummary,
    EnvironmentType
)
from venvy.utils import (
    get_directory_size,
    safe_read_file,
    safe_run_command,
    find_python_executable,
    get_python_version,
    human_readable_size,
    days_since_timestamp,
    get_venvy_data_dir,
)


class EnvironmentAnalysis:
    """Analyzes Python virtual environments for insights and recommendations"""
    
    def __init__(self):
        self.usage_data_file = get_venvy_data_dir() / "usage_data.json"
        self._usage_data = self._load_usage_data()
    
    def analyze_environment(self, env_info: EnvironmentInfo) -> EnvironmentInfo:
        """
        Perform comprehensive analysis of a single environment
        
        Args:
            env_info: Basic environment information
            
        Returns:
            Enhanced environment info with analysis results
        """
        # Calculate size if not already done
        if env_info.size_bytes is None:
            env_info.size_bytes = get_directory_size(env_info.path)
        
        # Analyze packages
        env_info.packages, env_info.package_count = self._analyze_packages(env_info)
        
        # Get pip version
        env_info.pip_version = self._get_pip_version(env_info)
        
        # Analyze health
        env_info.health_status, env_info.health_issues = self._analyze_health(env_info)
        
        # Analyze usage patterns
        env_info.activation_count = self._get_activation_count(env_info)
        env_info.days_since_used = self._get_days_since_used(env_info)
        
        # Detect project associations
        env_info.linked_projects = self._detect_linked_projects(env_info)
        env_info.is_orphaned = len(env_info.linked_projects or []) == 0
        
        # Find requirements files
        env_info.requirements_files = self._find_requirements_files(env_info)
        
        return env_info
    
    def analyze_all_environments(self, environments: List[EnvironmentInfo]) -> List[EnvironmentInfo]:
        """Analyze all environments and return enhanced information"""
        analyzed_environments = []
        
        for env_info in environments:
            analyzed_env = self.analyze_environment(env_info)
            analyzed_environments.append(analyzed_env)
        
        return analyzed_environments
    
    def get_system_summary(self, environments: List[EnvironmentInfo]) -> SystemSummary:
        """Generate system-wide summary statistics"""
        if not environments:
            return SystemSummary(
                total_environments=0,
                total_size_bytes=0,
                environment_types={},
                health_distribution={}
            )
        
        # Calculate totals
        total_environments = len(environments)
        total_size_bytes = sum(env.size_bytes or 0 for env in environments)
        
        # Environment type distribution
        type_counter = Counter(env.type.value for env in environments)
        environment_types = dict(type_counter)
        
        # Health distribution
        health_counter = Counter(env.health_status.value for env in environments)
        health_distribution = dict(health_counter)
        
        # Find notable environments
        largest_env = max(environments, key=lambda e: e.size_bytes or 0, default=None)
        oldest_env = None
        most_used_env = None
        
        if environments:
            # Find oldest environment
            envs_with_dates = [e for e in environments if e.created_date]
            if envs_with_dates:
                oldest_env = min(envs_with_dates, key=lambda e: e.created_date)
            
            # Find most used environment
            envs_with_usage = [e for e in environments if e.activation_count is not None]
            if envs_with_usage:
                most_used_env = max(envs_with_usage, key=lambda e: e.activation_count)
        
        # Calculate potential savings
        cleanup_suggestions = self.generate_cleanup_suggestions(environments)
        potential_savings_bytes = sum(s.space_recovered for s in cleanup_suggestions)
        
        return SystemSummary(
            total_environments=total_environments,
            total_size_bytes=total_size_bytes,
            environment_types=environment_types,
            health_distribution=health_distribution,
            oldest_environment=oldest_env,
            largest_environment=largest_env,
            most_used_environment=most_used_env,
            potential_savings_bytes=potential_savings_bytes
        )
    
    def generate_cleanup_suggestions(self, environments: List[EnvironmentInfo]) -> List[CleanupSuggestion]:
        """Generate intelligent cleanup suggestions"""
        suggestions = []
        
        for env in environments:
            # Skip if we don't have size information
            if env.size_bytes is None:
                continue
            
            suggestion = self._evaluate_environment_for_cleanup(env, environments)
            if suggestion:
                suggestions.append(suggestion)
        
        # Sort by confidence and space recovered
        suggestions.sort(key=lambda s: (s.confidence, s.space_recovered), reverse=True)
        
        return suggestions
    
    def find_duplicate_environments(self, environments: List[EnvironmentInfo]) -> List[List[EnvironmentInfo]]:
        """Find environments with similar package lists"""
        duplicates = []
        analyzed = set()
        
        for i, env1 in enumerate(environments):
            if i in analyzed or not env1.packages:
                continue
            
            similar_group = [env1]
            
            for j, env2 in enumerate(environments[i+1:], i+1):
                if j in analyzed or not env2.packages:
                    continue
                
                # Calculate package similarity
                similarity = self._calculate_package_similarity(env1.packages, env2.packages)
                if similarity > 0.8:  # 80% similarity threshold
                    similar_group.append(env2)
                    analyzed.add(j)
            
            if len(similar_group) > 1:
                duplicates.append(similar_group)
                analyzed.add(i)
        
        return duplicates
    
    def get_size_distribution(self, environments: List[EnvironmentInfo]) -> Dict[str, List[EnvironmentInfo]]:
        """Categorize environments by size"""
        distribution = {
            "tiny": [],      # < 50MB
            "small": [],     # 50MB - 200MB
            "medium": [],    # 200MB - 500MB
            "large": [],     # 500MB - 1GB
            "huge": []       # > 1GB
        }
        
        for env in environments:
            if env.size_bytes is None:
                continue
                
            size_mb = env.size_bytes / (1024 * 1024)
            
            if size_mb < 50:
                distribution["tiny"].append(env)
            elif size_mb < 200:
                distribution["small"].append(env)
            elif size_mb < 500:
                distribution["medium"].append(env)
            elif size_mb < 1024:
                distribution["large"].append(env)
            else:
                distribution["huge"].append(env)
        
        return distribution
    
    def track_environment_usage(self, env_path: Path, action: str = "activation"):
        """Track environment usage for analytics"""
        env_key = str(env_path)
        current_time = datetime.now().isoformat()
        
        if env_key not in self._usage_data:
            self._usage_data[env_key] = {
                "activations": [],
                "package_changes": [],
                "first_seen": current_time,
            }
        
        if action == "activation":
            self._usage_data[env_key]["activations"].append(current_time)
        elif action == "package_change":
            self._usage_data[env_key]["package_changes"].append(current_time)
        
        # Keep only last 90 days of data
        cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        for key in self._usage_data:
            self._usage_data[key]["activations"] = [
                t for t in self._usage_data[key]["activations"] if t > cutoff
            ]
            self._usage_data[key]["package_changes"] = [
                t for t in self._usage_data[key]["package_changes"] if t > cutoff
            ]
        
        # Save usage data
        self._save_usage_data()
    
    def _analyze_packages(self, env_info: EnvironmentInfo) -> Tuple[Optional[List[str]], Optional[int]]:
        """Analyze packages in an environment"""
        if not env_info.python_executable:
            return None, None
        
        try:
            # Try to get package list using pip
            pip_exe = self._find_pip_executable(env_info)
            if pip_exe:
                output = safe_run_command([str(pip_exe), "list", "--format=freeze"])
                if output:
                    packages = []
                    for line in output.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Extract package name (before ==, >=, etc.)
                            package_name = line.split('==')[0].split('>=')[0].split('<=')[0]
                            packages.append(package_name)
                    return packages, len(packages)
        except Exception:
            pass
        
        return None, None
    
    def _get_pip_version(self, env_info: EnvironmentInfo) -> Optional[str]:
        """Get pip version for an environment"""
        pip_exe = self._find_pip_executable(env_info)
        if pip_exe:
            output = safe_run_command([str(pip_exe), "--version"])
            if output and "pip" in output:
                # Extract version from "pip X.Y.Z from ..."
                parts = output.split()
                if len(parts) >= 2:
                    return parts[1]
        return None
    
    def _find_pip_executable(self, env_info: EnvironmentInfo) -> Optional[Path]:
        """Find pip executable in environment"""
        if not env_info.path.exists():
            return None
        
        # Check common locations
        possible_locations = [
            env_info.path / "Scripts" / "pip.exe",  # Windows
            env_info.path / "Scripts" / "pip",      # Windows without .exe
            env_info.path / "bin" / "pip",          # Unix
            env_info.path / "bin" / "pip3",         # Unix pip3
        ]
        
        for pip_path in possible_locations:
            if pip_path.exists():
                return pip_path
        
        return None
    
    def _analyze_health(self, env_info: EnvironmentInfo) -> Tuple[HealthStatus, Optional[List[str]]]:
        """Analyze environment health"""
        issues = []
        
        # Check if Python executable exists and works
        if not env_info.python_executable or not env_info.python_executable.exists():
            issues.append("Missing Python executable")
        else:
            # Test if Python executable works
            try:
                result = subprocess.run(
                    [str(env_info.python_executable), "--version"],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode != 0:
                    issues.append("Python executable is broken")
            except Exception:
                issues.append("Python executable cannot be executed")
        
        # Check for broken symlinks
        broken_links = self._find_broken_symlinks(env_info.path)
        if broken_links:
            issues.append(f"Found {len(broken_links)} broken symlinks")
        
        # Check pip health
        pip_exe = self._find_pip_executable(env_info)
        if not pip_exe:
            issues.append("pip not found")
        elif env_info.pip_version:
            # Check if pip is very outdated (arbitrary threshold)
            try:
                major_version = int(env_info.pip_version.split('.')[0])
                if major_version < 20:  # pip versions < 20 are quite old
                    issues.append("Outdated pip version")
            except ValueError:
                pass
        
        # Determine overall health status
        if not issues:
            return HealthStatus.HEALTHY, None
        elif len(issues) == 1 and "Outdated pip version" in issues:
            return HealthStatus.OUTDATED, issues
        elif any("broken" in issue.lower() or "missing" in issue.lower() for issue in issues):
            return HealthStatus.BROKEN, issues
        else:
            return HealthStatus.WARNING, issues
    
    def _find_broken_symlinks(self, path: Path) -> List[Path]:
        """Find broken symbolic links in a directory"""
        broken_links = []
        try:
            for item in path.rglob("*"):
                if item.is_symlink() and not item.exists():
                    broken_links.append(item)
        except (OSError, PermissionError):
            pass
        return broken_links
    
    def _get_activation_count(self, env_info: EnvironmentInfo) -> Optional[int]:
        """Get activation count from usage data"""
        env_key = str(env_info.path)
        if env_key in self._usage_data:
            return len(self._usage_data[env_key].get("activations", []))
        return 0
    
    def _get_days_since_used(self, env_info: EnvironmentInfo) -> Optional[int]:
        """Calculate days since environment was last used"""
        env_key = str(env_info.path)
        
        # Check usage data first
        if env_key in self._usage_data:
            activations = self._usage_data[env_key].get("activations", [])
            if activations:
                last_activation = datetime.fromisoformat(activations[-1])
                return days_since_timestamp(last_activation)
        
        # Fallback to filesystem timestamps
        if env_info.last_accessed:
            return days_since_timestamp(env_info.last_accessed)
        
        return None
    
    def _detect_linked_projects(self, env_info: EnvironmentInfo) -> Optional[List[Path]]:
        """Detect projects that might be linked to this environment"""
        projects = []
        
        # Look for nearby project directories
        parent_dir = env_info.path.parent
        
        # Common project indicators
        project_indicators = [
            "setup.py",
            "pyproject.toml", 
            "requirements.txt",
            "Pipfile",
            ".git",
            "README.md",
            "README.rst",
        ]
        
        # Check parent directory for project files
        for indicator in project_indicators:
            if (parent_dir / indicator).exists():
                projects.append(parent_dir)
                break
        
        # Check for nearby directories that look like projects
        try:
            for sibling in parent_dir.iterdir():
                if sibling.is_dir() and sibling != env_info.path:
                    # Check if this directory has project indicators
                    for indicator in project_indicators:
                        if (sibling / indicator).exists():
                            projects.append(sibling)
                            break
        except (OSError, PermissionError):
            pass
        
        return projects if projects else None
    
    def _find_requirements_files(self, env_info: EnvironmentInfo) -> Optional[List[Path]]:
        """Find requirements files associated with environment"""
        requirements_files = []
        
        # Search in environment directory
        req_patterns = ["requirements*.txt", "requirements*.pip", "requirements.in"]
        
        for pattern in req_patterns:
            for req_file in env_info.path.glob(pattern):
                if req_file.is_file():
                    requirements_files.append(req_file)
        
        # Search in linked projects
        if env_info.linked_projects:
            for project_path in env_info.linked_projects:
                for pattern in req_patterns:
                    for req_file in project_path.glob(pattern):
                        if req_file.is_file():
                            requirements_files.append(req_file)
        
        return requirements_files if requirements_files else None
    
    def _evaluate_environment_for_cleanup(self, env: EnvironmentInfo, all_environments: List[EnvironmentInfo]) -> Optional[CleanupSuggestion]:
        """Evaluate if an environment should be suggested for cleanup"""
        reasons = []
        confidence = 0.0
        risk_level = "low"
        
        # Check if environment is broken
        if env.health_status == HealthStatus.BROKEN:
            reasons.append("Environment is broken and cannot be used")
            confidence += 0.9
            risk_level = "low"
        
        # Check if environment hasn't been used in a long time
        if env.days_since_used is not None:
            if env.days_since_used > 180:  # 6 months
                reasons.append(f"Not used for {env.days_since_used} days")
                confidence += 0.8
            elif env.days_since_used > 90:  # 3 months
                reasons.append(f"Not used for {env.days_since_used} days")
                confidence += 0.6
                risk_level = "medium"
        
        # Check if environment is orphaned (no linked projects)
        if env.is_orphaned and not env.name.lower() in ["base", "root", "default"]:
            reasons.append("No associated projects found")
            confidence += 0.3
        
        # Check for test/temporary environment patterns
        temp_patterns = ["test", "tmp", "temp", "experiment", "trial", "demo"]
        if any(pattern in env.name.lower() for pattern in temp_patterns):
            reasons.append("Appears to be a temporary/test environment")
            confidence += 0.4
        
        # Only suggest if we have reasonable confidence
        if confidence > 0.4 and reasons:
            return CleanupSuggestion(
                environment=env,
                reason="; ".join(reasons),
                confidence=min(confidence, 1.0),
                space_recovered=env.size_bytes or 0,
                risk_level=risk_level
            )
        
        return None
    
    def _calculate_package_similarity(self, packages1: List[str], packages2: List[str]) -> float:
        """Calculate similarity between two package lists"""
        if not packages1 or not packages2:
            return 0.0
        
        set1 = set(pkg.lower() for pkg in packages1)
        set2 = set(pkg.lower() for pkg in packages2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def _load_usage_data(self) -> Dict:
        """Load usage tracking data"""
        if self.usage_data_file.exists():
            try:
                content = safe_read_file(self.usage_data_file)
                if content:
                    return json.loads(content)
            except json.JSONDecodeError:
                pass
        return {}
    
    def _save_usage_data(self):
        """Save usage tracking data"""
        try:
            # Ensure directory exists
            self.usage_data_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write data
            with open(self.usage_data_file, 'w') as f:
                json.dump(self._usage_data, f, indent=2)
        except Exception:
            # Silently fail if we can't save usage data
            pass