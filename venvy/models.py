"""
Data models for venvy - environment representation and metadata
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from enum import Enum


class EnvironmentType(Enum):
    """Types of Python environments venvy can detect"""
    VENV = "venv"
    CONDA = "conda"
    PYENV = "pyenv"
    VIRTUALENV = "virtualenv"
    UNKNOWN = "unknown"


class HealthStatus(Enum):
    """Health status indicators for environments"""
    HEALTHY = "healthy"
    OUTDATED = "outdated"
    BROKEN = "broken"
    WARNING = "warning"
    UNKNOWN = "unknown"


@dataclass
class EnvironmentInfo:
    """Complete information about a Python virtual environment"""
    
    # Basic identification
    name: str
    path: Path
    type: EnvironmentType
    
    # Python information
    python_version: Optional[str] = None
    python_executable: Optional[Path] = None
    
    # Filesystem information
    size_bytes: Optional[int] = None
    created_date: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    
    # Package information
    package_count: Optional[int] = None
    packages: Optional[List[str]] = None
    pip_version: Optional[str] = None
    
    # Health and usage
    health_status: HealthStatus = HealthStatus.UNKNOWN
    health_issues: Optional[List[str]] = None
    activation_count: Optional[int] = None
    days_since_used: Optional[int] = None
    
    # Project association
    linked_projects: Optional[List[Path]] = None
    is_orphaned: bool = False
    
    # Additional metadata
    conda_env_name: Optional[str] = None  # For conda environments
    requirements_files: Optional[List[Path]] = None
    
    def __post_init__(self):
        """Post-initialization processing"""
        # Ensure path is a Path object
        if isinstance(self.path, str):
            self.path = Path(self.path)
            
        # Set python_executable if not provided
        if not self.python_executable and self.path.exists():
            self._detect_python_executable()
    
    def _detect_python_executable(self):
        """Detect the Python executable path for this environment"""
        # Windows uses Scripts/, Unix uses bin/
        if self.path.name == "Scripts" or (self.path / "Scripts").exists():
            # Windows environment
            python_exe = self.path / "Scripts" / "python.exe"
            if not python_exe.exists():
                python_exe = self.path / "python.exe"
        else:
            # Unix-like environment
            python_exe = self.path / "bin" / "python"
            if not python_exe.exists():
                python_exe = self.path / "python"
                
        if python_exe.exists():
            self.python_executable = python_exe
    
    @property
    def size_human(self) -> str:
        """Human-readable size string"""
        if self.size_bytes is None:
            return "Unknown"
            
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if self.size_bytes < 1024.0:
                return f"{self.size_bytes:.1f} {unit}"
            self.size_bytes /= 1024.0
        return f"{self.size_bytes:.1f} PB"
    
    @property
    def is_recently_used(self) -> bool:
        """Check if environment was used recently (within 30 days)"""
        return self.days_since_used is not None and self.days_since_used <= 30
    
    @property
    def is_healthy(self) -> bool:
        """Check if environment is healthy"""
        return self.health_status == HealthStatus.HEALTHY
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "name": self.name,
            "path": str(self.path),
            "type": self.type.value,
            "python_version": self.python_version,
            "python_executable": str(self.python_executable) if self.python_executable else None,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "created_date": self.created_date.isoformat() if self.created_date else None,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "package_count": self.package_count,
            "packages": self.packages,
            "pip_version": self.pip_version,
            "health_status": self.health_status.value,
            "health_issues": self.health_issues,
            "activation_count": self.activation_count,
            "days_since_used": self.days_since_used,
            "linked_projects": [str(p) for p in self.linked_projects] if self.linked_projects else None,
            "is_orphaned": self.is_orphaned,
            "conda_env_name": self.conda_env_name,
            "requirements_files": [str(f) for f in self.requirements_files] if self.requirements_files else None,
        }


@dataclass 
class CleanupSuggestion:
    """A suggestion for cleaning up an environment"""
    environment: EnvironmentInfo
    reason: str
    confidence: float  # 0.0 to 1.0
    space_recovered: int  # bytes
    risk_level: str  # "low", "medium", "high"
    
    @property
    def space_recovered_human(self) -> str:
        """Human-readable space recovery string"""
        size = self.space_recovered
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"


@dataclass
class SystemSummary:
    """Summary statistics for all environments on the system"""
    total_environments: int
    total_size_bytes: int
    environment_types: Dict[str, int]
    health_distribution: Dict[str, int]
    oldest_environment: Optional[EnvironmentInfo] = None
    largest_environment: Optional[EnvironmentInfo] = None
    most_used_environment: Optional[EnvironmentInfo] = None
    potential_savings_bytes: int = 0
    
    @property
    def total_size_human(self) -> str:
        """Human-readable total size"""
        size = self.total_size_bytes
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
    
    @property
    def potential_savings_human(self) -> str:
        """Human-readable potential savings"""
        size = self.potential_savings_bytes
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"