"""
Tests for venvy data models
"""
import pytest
from datetime import datetime
from pathlib import Path

from venvy.models import (
    EnvironmentType,
    HealthStatus,
    EnvironmentInfo,
    CleanupSuggestion,
    SystemSummary
)


class TestEnvironmentType:
    """Test environment type enumeration"""
    
    def test_environment_type_values(self):
        """Test environment type enum values"""
        assert EnvironmentType.VENV.value == "venv"
        assert EnvironmentType.CONDA.value == "conda"
        assert EnvironmentType.PYENV.value == "pyenv"
        assert EnvironmentType.VIRTUALENV.value == "virtualenv"
        assert EnvironmentType.UNKNOWN.value == "unknown"


class TestHealthStatus:
    """Test health status enumeration"""
    
    def test_health_status_values(self):
        """Test health status enum values"""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.OUTDATED.value == "outdated"
        assert HealthStatus.BROKEN.value == "broken"
        assert HealthStatus.WARNING.value == "warning"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestEnvironmentInfo:
    """Test EnvironmentInfo data model"""
    
    def test_environment_info_creation(self):
        """Test creating basic EnvironmentInfo"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV
        )
        
        assert env_info.name == "test_env"
        assert env_info.path == Path("/test/path")
        assert env_info.type == EnvironmentType.VENV
        assert env_info.health_status == HealthStatus.UNKNOWN
        assert env_info.is_orphaned is False
    
    def test_environment_info_string_path(self):
        """Test EnvironmentInfo with string path gets converted to Path"""
        env_info = EnvironmentInfo(
            name="test_env",
            path="/test/string/path",
            type=EnvironmentType.VENV
        )
        
        assert isinstance(env_info.path, Path)
        assert str(env_info.path) == "/test/string/path"
    
    def test_environment_info_size_human(self):
        """Test human-readable size property"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV,
            size_bytes=1024
        )
        
        assert env_info.size_human == "1.0 KB"
    
    def test_environment_info_size_human_none(self):
        """Test human-readable size with None size"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV,
            size_bytes=None
        )
        
        assert env_info.size_human == "Unknown"
    
    def test_environment_info_is_recently_used(self):
        """Test recently used property"""
        # Recently used environment
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV,
            days_since_used=15
        )
        
        assert env_info.is_recently_used is True
        
        # Old environment
        env_info.days_since_used = 60
        assert env_info.is_recently_used is False
        
        # Unknown usage
        env_info.days_since_used = None
        assert env_info.is_recently_used is False
    
    def test_environment_info_is_healthy(self):
        """Test healthy property"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV,
            health_status=HealthStatus.HEALTHY
        )
        
        assert env_info.is_healthy is True
        
        env_info.health_status = HealthStatus.BROKEN
        assert env_info.is_healthy is False
    
    def test_environment_info_to_dict(self):
        """Test converting EnvironmentInfo to dictionary"""
        created_date = datetime.now()
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV,
            python_version="3.9.7",
            size_bytes=1024000,
            created_date=created_date,
            packages=["numpy", "pandas"],
            health_status=HealthStatus.HEALTHY
        )
        
        result = env_info.to_dict()
        
        assert isinstance(result, dict)
        assert result["name"] == "test_env"
        assert result["path"] == "/test/path"
        assert result["type"] == "venv"
        assert result["python_version"] == "3.9.7"
        assert result["size_bytes"] == 1024000
        assert result["size_human"] == "1000.0 KB"
        assert result["packages"] == ["numpy", "pandas"]
        assert result["health_status"] == "healthy"
        assert result["created_date"] == created_date.isoformat()
    
    def test_environment_info_to_dict_none_values(self):
        """Test converting EnvironmentInfo with None values to dictionary"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV
        )
        
        result = env_info.to_dict()
        
        assert result["python_executable"] is None
        assert result["created_date"] is None
        assert result["packages"] is None
        assert result["linked_projects"] is None


class TestCleanupSuggestion:
    """Test CleanupSuggestion data model"""
    
    def test_cleanup_suggestion_creation(self):
        """Test creating CleanupSuggestion"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV
        )
        
        suggestion = CleanupSuggestion(
            environment=env_info,
            reason="Not used for 90 days",
            confidence=0.8,
            space_recovered=1024000,
            risk_level="low"
        )
        
        assert suggestion.environment == env_info
        assert suggestion.reason == "Not used for 90 days"
        assert suggestion.confidence == 0.8
        assert suggestion.space_recovered == 1024000
        assert suggestion.risk_level == "low"
    
    def test_cleanup_suggestion_space_recovered_human(self):
        """Test human-readable space recovery"""
        env_info = EnvironmentInfo(
            name="test_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV
        )
        
        suggestion = CleanupSuggestion(
            environment=env_info,
            reason="Test",
            confidence=0.8,
            space_recovered=1024*1024*5,  # 5 MB
            risk_level="low"
        )
        
        assert suggestion.space_recovered_human == "5.0 MB"


class TestSystemSummary:
    """Test SystemSummary data model"""
    
    def test_system_summary_creation(self):
        """Test creating SystemSummary"""
        summary = SystemSummary(
            total_environments=10,
            total_size_bytes=1024*1024*100,  # 100 MB
            environment_types={"venv": 7, "conda": 3},
            health_distribution={"healthy": 8, "broken": 2}
        )
        
        assert summary.total_environments == 10
        assert summary.total_size_bytes == 1024*1024*100
        assert summary.environment_types == {"venv": 7, "conda": 3}
        assert summary.health_distribution == {"healthy": 8, "broken": 2}
    
    def test_system_summary_total_size_human(self):
        """Test human-readable total size"""
        summary = SystemSummary(
            total_environments=5,
            total_size_bytes=1024*1024*1024,  # 1 GB
            environment_types={},
            health_distribution={}
        )
        
        assert summary.total_size_human == "1.0 GB"
    
    def test_system_summary_potential_savings_human(self):
        """Test human-readable potential savings"""
        summary = SystemSummary(
            total_environments=5,
            total_size_bytes=1024*1024*1024,
            environment_types={},
            health_distribution={},
            potential_savings_bytes=1024*1024*500  # 500 MB
        )
        
        assert summary.potential_savings_human == "500.0 MB"
    
    def test_system_summary_optional_fields(self):
        """Test SystemSummary with optional fields"""
        env_info = EnvironmentInfo(
            name="largest_env",
            path=Path("/test/path"),
            type=EnvironmentType.VENV,
            size_bytes=1024*1024*50
        )
        
        summary = SystemSummary(
            total_environments=5,
            total_size_bytes=1024*1024*100,
            environment_types={"venv": 5},
            health_distribution={"healthy": 5},
            largest_environment=env_info,
            oldest_environment=env_info,
            most_used_environment=env_info
        )
        
        assert summary.largest_environment == env_info
        assert summary.oldest_environment == env_info
        assert summary.most_used_environment == env_info