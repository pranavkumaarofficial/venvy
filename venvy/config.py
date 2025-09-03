"""
Configuration management for venvy
Handles user settings, preferences, and persistent configuration
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from venvy.utils import get_venvy_data_dir, create_directory_safely, safe_read_file


@dataclass
class VenvyConfig:
    """Configuration settings for venvy"""
    
    # Search paths for environments
    search_paths: List[str] = None
    
    # Default behavior settings
    auto_backup: bool = True
    confirm_deletions: bool = True
    default_unused_days: int = 90
    
    # Display preferences
    default_output_format: str = "table"  # table, json, simple
    default_sort_by: str = "name"  # name, size, age, usage
    show_system_environments: bool = False
    max_suggestions: int = 10
    
    # Cleanup preferences
    cleanup_confidence_threshold: float = 0.7
    create_backups: bool = True
    backup_retention_days: int = 30
    
    # Advanced settings
    enable_usage_tracking: bool = True
    parallel_analysis: bool = True
    cache_results: bool = True
    cache_duration_hours: int = 24
    
    def __post_init__(self):
        """Initialize default values"""
        if self.search_paths is None:
            self.search_paths = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VenvyConfig':
        """Create config from dictionary"""
        return cls(**data)


class ConfigManager:
    """Manages venvy configuration loading, saving, and validation"""
    
    def __init__(self):
        self.config_dir = get_venvy_data_dir()
        self.config_file = self.config_dir / "config.json"
        self.config_schema_version = "1.0"
        
        # Ensure config directory exists
        create_directory_safely(self.config_dir)
        
        # Load or create default config
        self._config = self._load_config()
    
    @property
    def config(self) -> VenvyConfig:
        """Get current configuration"""
        return self._config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value"""
        return getattr(self._config, key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """Set a configuration value"""
        try:
            if hasattr(self._config, key):
                setattr(self._config, key, value)
                return self.save()
            return False
        except Exception:
            return False
    
    def update(self, **kwargs) -> bool:
        """Update multiple configuration values"""
        try:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
            return self.save()
        except Exception:
            return False
    
    def save(self) -> bool:
        """Save current configuration to file"""
        try:
            config_data = {
                "schema_version": self.config_schema_version,
                "config": self._config.to_dict()
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception:
            return False
    
    def load(self) -> bool:
        """Reload configuration from file"""
        try:
            self._config = self._load_config()
            return True
        except Exception:
            return False
    
    def reset_to_defaults(self) -> bool:
        """Reset configuration to default values"""
        try:
            self._config = VenvyConfig()
            return self.save()
        except Exception:
            return False
    
    def add_search_path(self, path: str) -> bool:
        """Add a path to the search paths list"""
        try:
            path_obj = Path(path).resolve()
            path_str = str(path_obj)
            
            if path_obj.exists() and path_obj.is_dir():
                if path_str not in self._config.search_paths:
                    self._config.search_paths.append(path_str)
                    return self.save()
            return False
        except Exception:
            return False
    
    def remove_search_path(self, path: str) -> bool:
        """Remove a path from the search paths list"""
        try:
            path_obj = Path(path).resolve()
            path_str = str(path_obj)
            
            if path_str in self._config.search_paths:
                self._config.search_paths.remove(path_str)
                return self.save()
            return False
        except Exception:
            return False
    
    def get_search_paths(self) -> List[Path]:
        """Get search paths as Path objects"""
        paths = []
        for path_str in self._config.search_paths:
            try:
                path_obj = Path(path_str)
                if path_obj.exists() and path_obj.is_dir():
                    paths.append(path_obj)
            except Exception:
                continue
        return paths
    
    def validate_config(self) -> List[str]:
        """Validate current configuration and return list of issues"""
        issues = []
        
        # Validate search paths
        invalid_paths = []
        for path_str in self._config.search_paths:
            try:
                path_obj = Path(path_str)
                if not path_obj.exists():
                    invalid_paths.append(path_str)
            except Exception:
                invalid_paths.append(path_str)
        
        if invalid_paths:
            issues.append(f"Invalid search paths: {', '.join(invalid_paths)}")
        
        # Validate numeric ranges
        if not 0 <= self._config.cleanup_confidence_threshold <= 1.0:
            issues.append("Cleanup confidence threshold must be between 0.0 and 1.0")
        
        if self._config.default_unused_days < 0:
            issues.append("Default unused days must be positive")
        
        if self._config.backup_retention_days < 0:
            issues.append("Backup retention days must be positive")
        
        if self._config.cache_duration_hours < 0:
            issues.append("Cache duration hours must be positive")
        
        if self._config.max_suggestions < 1:
            issues.append("Max suggestions must be at least 1")
        
        # Validate string choices
        valid_formats = {"table", "json", "simple"}
        if self._config.default_output_format not in valid_formats:
            issues.append(f"Invalid output format: {self._config.default_output_format}")
        
        valid_sort_options = {"name", "size", "age", "usage"}
        if self._config.default_sort_by not in valid_sort_options:
            issues.append(f"Invalid sort option: {self._config.default_sort_by}")
        
        return issues
    
    def get_config_info(self) -> Dict[str, Any]:
        """Get information about the configuration"""
        return {
            "config_file": str(self.config_file),
            "config_exists": self.config_file.exists(),
            "config_dir": str(self.config_dir),
            "schema_version": self.config_schema_version,
            "search_paths_count": len(self._config.search_paths),
            "valid_search_paths": len(self.get_search_paths()),
            "validation_issues": self.validate_config(),
        }
    
    def export_config(self, export_path: Path) -> bool:
        """Export configuration to a file"""
        try:
            config_data = {
                "schema_version": self.config_schema_version,
                "config": self._config.to_dict(),
                "exported_at": str(datetime.now().isoformat()),
                "exported_by": "venvy"
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception:
            return False
    
    def import_config(self, import_path: Path) -> bool:
        """Import configuration from a file"""
        try:
            if not import_path.exists():
                return False
            
            content = safe_read_file(import_path)
            if not content:
                return False
            
            data = json.loads(content)
            
            # Validate schema version
            if data.get("schema_version") != self.config_schema_version:
                return False
            
            # Import configuration
            config_dict = data.get("config", {})
            self._config = VenvyConfig.from_dict(config_dict)
            
            # Validate and save
            if not self.validate_config():
                return self.save()
            
            return False
        except Exception:
            return False
    
    def _load_config(self) -> VenvyConfig:
        """Load configuration from file or create default"""
        if not self.config_file.exists():
            # Create default configuration
            default_config = VenvyConfig()
            self._save_default_config(default_config)
            return default_config
        
        try:
            content = safe_read_file(self.config_file)
            if content:
                data = json.loads(content)
                
                # Check schema version
                schema_version = data.get("schema_version", "1.0")
                if schema_version != self.config_schema_version:
                    # Handle migration if needed
                    return self._migrate_config(data)
                
                # Load configuration
                config_dict = data.get("config", {})
                return VenvyConfig.from_dict(config_dict)
        
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        
        # If loading fails, return default config
        return VenvyConfig()
    
    def _save_default_config(self, config: VenvyConfig):
        """Save default configuration to file"""
        try:
            config_data = {
                "schema_version": self.config_schema_version,
                "config": config.to_dict(),
                "created_at": str(datetime.now().isoformat()),
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def _migrate_config(self, old_data: Dict[str, Any]) -> VenvyConfig:
        """Migrate configuration from older versions"""
        # For now, just return default config
        # In the future, implement version-specific migration logic
        return VenvyConfig()


# Global config instance
_config_manager = None


def get_config() -> ConfigManager:
    """Get global configuration manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_setting(key: str, default: Any = None) -> Any:
    """Get a configuration setting"""
    return get_config().get(key, default)


def set_setting(key: str, value: Any) -> bool:
    """Set a configuration setting"""
    return get_config().set(key, value)