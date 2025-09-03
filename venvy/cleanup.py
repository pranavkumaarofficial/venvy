"""
Environment cleanup operations for venvy
Safe removal and cleanup of Python virtual environments
"""
import shutil
import os
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from venvy.models import EnvironmentInfo, HealthStatus, CleanupSuggestion
from venvy.utils import human_readable_size, create_directory_safely, get_venvy_data_dir


class EnvironmentCleanup:
    """Handles safe cleanup operations for Python virtual environments"""
    
    def __init__(self):
        self.backup_dir = get_venvy_data_dir() / "backups"
        self.cleanup_log_file = get_venvy_data_dir() / "cleanup_log.txt"
        create_directory_safely(self.backup_dir)
    
    def remove_environment(self, env_info: EnvironmentInfo, create_backup: bool = False) -> bool:
        """
        Safely remove a virtual environment
        
        Args:
            env_info: Environment to remove
            create_backup: Whether to create a backup before removal
            
        Returns:
            True if successful, False otherwise
        """
        if not env_info.path.exists():
            self._log_cleanup(f"Environment {env_info.name} does not exist at {env_info.path}")
            return False
        
        try:
            # Create backup if requested
            if create_backup:
                backup_success = self._create_backup(env_info)
                if not backup_success:
                    self._log_cleanup(f"Failed to create backup for {env_info.name}")
                    return False
            
            # Log the removal
            size_str = human_readable_size(env_info.size_bytes) if env_info.size_bytes else "unknown size"
            self._log_cleanup(f"Removing environment: {env_info.name} ({size_str}) from {env_info.path}")
            
            # Remove the directory
            shutil.rmtree(env_info.path)
            
            self._log_cleanup(f"Successfully removed {env_info.name}")
            return True
            
        except PermissionError as e:
            self._log_cleanup(f"Permission denied removing {env_info.name}: {e}")
            return False
        except OSError as e:
            self._log_cleanup(f"OS error removing {env_info.name}: {e}")
            return False
        except Exception as e:
            self._log_cleanup(f"Unexpected error removing {env_info.name}: {e}")
            return False
    
    def batch_remove_environments(self, environments: List[EnvironmentInfo], 
                                create_backups: bool = False) -> Dict[str, List[EnvironmentInfo]]:
        """
        Remove multiple environments in batch
        
        Args:
            environments: List of environments to remove
            create_backups: Whether to create backups before removal
            
        Returns:
            Dictionary with 'success' and 'failed' keys containing lists of environments
        """
        results = {
            'success': [],
            'failed': []
        }
        
        for env in environments:
            success = self.remove_environment(env, create_backup=create_backups)
            if success:
                results['success'].append(env)
            else:
                results['failed'].append(env)
        
        return results
    
    def clean_broken_environments(self, environments: List[EnvironmentInfo]) -> Dict[str, List[EnvironmentInfo]]:
        """
        Clean up environments that are broken or corrupted
        
        Args:
            environments: List of all environments to check
            
        Returns:
            Dictionary with cleanup results
        """
        broken_environments = [
            env for env in environments 
            if env.health_status == HealthStatus.BROKEN
        ]
        
        if not broken_environments:
            return {'success': [], 'failed': []}
        
        self._log_cleanup(f"Cleaning {len(broken_environments)} broken environment(s)")
        return self.batch_remove_environments(broken_environments, create_backups=False)
    
    def clean_unused_environments(self, environments: List[EnvironmentInfo], 
                                unused_days: int = 90) -> Dict[str, List[EnvironmentInfo]]:
        """
        Clean up environments that haven't been used for specified days
        
        Args:
            environments: List of all environments to check
            unused_days: Number of days to consider environment unused
            
        Returns:
            Dictionary with cleanup results
        """
        unused_environments = []
        
        for env in environments:
            if (env.days_since_used is not None and 
                env.days_since_used >= unused_days and
                not self._is_system_environment(env)):
                unused_environments.append(env)
        
        if not unused_environments:
            return {'success': [], 'failed': []}
        
        self._log_cleanup(f"Cleaning {len(unused_environments)} unused environment(s) (unused for {unused_days}+ days)")
        return self.batch_remove_environments(unused_environments, create_backups=True)
    
    def execute_cleanup_suggestions(self, suggestions: List[CleanupSuggestion], 
                                  min_confidence: float = 0.7) -> Dict[str, List[EnvironmentInfo]]:
        """
        Execute cleanup suggestions that meet minimum confidence threshold
        
        Args:
            suggestions: List of cleanup suggestions
            min_confidence: Minimum confidence level to execute (0.0 to 1.0)
            
        Returns:
            Dictionary with cleanup results
        """
        # Filter suggestions by confidence and risk level
        safe_suggestions = [
            s for s in suggestions 
            if s.confidence >= min_confidence and s.risk_level in ["low", "medium"]
        ]
        
        if not safe_suggestions:
            return {'success': [], 'failed': []}
        
        environments_to_remove = [s.environment for s in safe_suggestions]
        
        self._log_cleanup(f"Executing {len(safe_suggestions)} cleanup suggestion(s)")
        return self.batch_remove_environments(environments_to_remove, create_backups=True)
    
    def clean_duplicate_environments(self, duplicate_groups: List[List[EnvironmentInfo]], 
                                   keep_newest: bool = True) -> Dict[str, List[EnvironmentInfo]]:
        """
        Clean up duplicate environments, keeping one from each group
        
        Args:
            duplicate_groups: Groups of similar environments
            keep_newest: Whether to keep the newest or oldest environment
            
        Returns:
            Dictionary with cleanup results
        """
        environments_to_remove = []
        
        for group in duplicate_groups:
            if len(group) <= 1:
                continue
            
            # Determine which environment to keep
            if keep_newest:
                # Keep the most recently used
                group_sorted = sorted(group, key=lambda e: e.days_since_used or float('inf'))
                to_keep = group_sorted[0]
            else:
                # Keep the oldest
                group_sorted = sorted(group, key=lambda e: e.created_date or datetime.min, reverse=True)
                to_keep = group_sorted[0]
            
            # Add others to removal list
            for env in group:
                if env != to_keep:
                    environments_to_remove.append(env)
        
        if not environments_to_remove:
            return {'success': [], 'failed': []}
        
        self._log_cleanup(f"Cleaning {len(environments_to_remove)} duplicate environment(s)")
        return self.batch_remove_environments(environments_to_remove, create_backups=True)
    
    def archive_environment(self, env_info: EnvironmentInfo) -> Optional[Path]:
        """
        Archive an environment instead of deleting it
        
        Args:
            env_info: Environment to archive
            
        Returns:
            Path to archive file if successful, None otherwise
        """
        if not env_info.path.exists():
            return None
        
        try:
            # Create archive filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"{env_info.name}_{timestamp}"
            archive_path = self.backup_dir / f"{archive_name}.tar.gz"
            
            # Create tar.gz archive
            import tarfile
            
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(env_info.path, arcname=env_info.name)
            
            self._log_cleanup(f"Archived {env_info.name} to {archive_path}")
            
            # Now remove the original
            shutil.rmtree(env_info.path)
            
            return archive_path
            
        except Exception as e:
            self._log_cleanup(f"Failed to archive {env_info.name}: {e}")
            return None
    
    def restore_environment(self, archive_path: Path, restore_path: Optional[Path] = None) -> bool:
        """
        Restore an environment from archive
        
        Args:
            archive_path: Path to archive file
            restore_path: Path to restore to (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not archive_path.exists():
            return False
        
        try:
            import tarfile
            
            # Determine restore location
            if restore_path is None:
                # Use user's home directory or common venv location
                restore_path = Path.home() / "venvs"
                create_directory_safely(restore_path)
            
            # Extract archive
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(restore_path)
            
            self._log_cleanup(f"Restored environment from {archive_path} to {restore_path}")
            return True
            
        except Exception as e:
            self._log_cleanup(f"Failed to restore from {archive_path}: {e}")
            return False
    
    def get_cleanup_stats(self) -> Dict:
        """Get statistics about cleanup operations"""
        stats = {
            'total_cleaned': 0,
            'total_space_freed': 0,
            'backups_created': 0,
            'archives_created': 0,
        }
        
        # Count backup files
        if self.backup_dir.exists():
            backup_files = list(self.backup_dir.glob("*.tar.gz"))
            stats['backups_created'] = len(backup_files)
            stats['archives_created'] = len(backup_files)
        
        # Parse log file for stats (simplified)
        if self.cleanup_log_file.exists():
            try:
                with open(self.cleanup_log_file, 'r') as f:
                    content = f.read()
                    stats['total_cleaned'] = content.count('Successfully removed')
            except Exception:
                pass
        
        return stats
    
    def _create_backup(self, env_info: EnvironmentInfo) -> bool:
        """Create a backup of an environment before removal"""
        try:
            # Create backup as tar.gz archive
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{env_info.name}_backup_{timestamp}.tar.gz"
            backup_path = self.backup_dir / backup_name
            
            import tarfile
            
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(env_info.path, arcname=env_info.name)
            
            self._log_cleanup(f"Created backup: {backup_path}")
            return True
            
        except Exception as e:
            self._log_cleanup(f"Failed to create backup for {env_info.name}: {e}")
            return False
    
    def _is_system_environment(self, env_info: EnvironmentInfo) -> bool:
        """Check if environment appears to be a system environment"""
        system_names = {
            'base', 'root', 'system', 'default', 'main', 
            'python3', 'python', 'global'
        }
        
        # Check if name suggests it's a system environment
        if env_info.name.lower() in system_names:
            return True
        
        # Check if path suggests it's a system environment
        system_paths = {
            '/usr/', '/opt/', '/System/', 'C:\\Program Files', 
            'C:\\Windows', '/Library/'
        }
        
        path_str = str(env_info.path)
        for sys_path in system_paths:
            if sys_path.lower() in path_str.lower():
                return True
        
        return False
    
    def _log_cleanup(self, message: str):
        """Log cleanup operations"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            
            # Ensure log directory exists
            create_directory_safely(self.cleanup_log_file.parent)
            
            with open(self.cleanup_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception:
            # Silently fail if we can't log
            pass
    
    def get_cleanup_log(self, lines: int = 100) -> List[str]:
        """Get recent cleanup log entries"""
        if not self.cleanup_log_file.exists():
            return []
        
        try:
            with open(self.cleanup_log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return all_lines[-lines:] if lines else all_lines
        except Exception:
            return []
    
    def clear_cleanup_log(self) -> bool:
        """Clear the cleanup log file"""
        try:
            if self.cleanup_log_file.exists():
                self.cleanup_log_file.unlink()
            return True
        except Exception:
            return False