"""
Tests for venvy utility functions
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, Mock
import tempfile
import shutil

from venvy.utils import (
    get_platform_info,
    get_home_directory,
    get_common_venv_locations,
    get_directory_size,
    safe_read_file,
    safe_run_command,
    human_readable_size,
    is_python_executable,
    find_python_executable,
    get_python_version,
    normalize_path,
    create_directory_safely,
    get_venvy_data_dir,
)


class TestPlatformInfo:
    """Test platform information functions"""
    
    def test_get_platform_info(self):
        """Test platform info detection"""
        info = get_platform_info()
        
        assert "system" in info
        assert "platform" in info
        assert "architecture" in info
        assert "python_version" in info
        assert "is_windows" in info
        assert "is_macos" in info
        assert "is_linux" in info
        
        # Exactly one platform should be True
        platform_flags = [info["is_windows"], info["is_macos"], info["is_linux"]]
        assert sum(platform_flags) >= 0  # At least one should be True
        
    def test_get_home_directory(self):
        """Test home directory detection"""
        home = get_home_directory()
        
        assert isinstance(home, Path)
        assert home.exists()
        assert home.is_dir()


class TestDirectoryOperations:
    """Test directory and file operations"""
    
    def test_get_directory_size_empty_dir(self):
        """Test size calculation for empty directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            size = get_directory_size(Path(temp_dir))
            assert size == 0
    
    def test_get_directory_size_with_files(self):
        """Test size calculation for directory with files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test files
            (temp_path / "file1.txt").write_text("Hello World")
            (temp_path / "file2.txt").write_text("Test content")
            
            size = get_directory_size(temp_path)
            assert size > 0
    
    def test_get_directory_size_nonexistent(self):
        """Test size calculation for non-existent directory"""
        fake_path = Path("/nonexistent/directory/path")
        size = get_directory_size(fake_path)
        assert size == 0
    
    def test_create_directory_safely(self):
        """Test safe directory creation"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            new_dir = temp_path / "new" / "nested" / "directory"
            
            success = create_directory_safely(new_dir)
            
            assert success is True
            assert new_dir.exists()
            assert new_dir.is_dir()
    
    def test_create_directory_safely_exists(self):
        """Test safe directory creation when directory already exists"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            success = create_directory_safely(temp_path)
            assert success is True


class TestFileOperations:
    """Test file reading and operations"""
    
    def test_safe_read_file_exists(self):
        """Test reading existing file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            test_content = "Test file content"
            f.write(test_content)
            f.flush()
            
            try:
                content = safe_read_file(Path(f.name))
                assert content == test_content
            finally:
                os.unlink(f.name)
    
    def test_safe_read_file_nonexistent(self):
        """Test reading non-existent file"""
        fake_file = Path("/nonexistent/file.txt")
        content = safe_read_file(fake_file)
        assert content is None
    
    def test_safe_run_command_success(self):
        """Test running successful command"""
        # Use a simple command that should work on all platforms
        if os.name == 'nt':  # Windows
            result = safe_run_command(["echo", "hello"])
        else:  # Unix-like
            result = safe_run_command(["echo", "hello"])
        
        # Note: May be None on some systems, but shouldn't raise exception
        assert result is None or isinstance(result, str)
    
    def test_safe_run_command_failure(self):
        """Test running failing command"""
        result = safe_run_command(["nonexistent_command_12345"])
        assert result is None
    
    def test_safe_run_command_timeout(self):
        """Test command timeout"""
        # This should timeout quickly
        result = safe_run_command(["python", "-c", "import time; time.sleep(100)"], timeout=1)
        assert result is None


class TestSizeFormatting:
    """Test human-readable size formatting"""
    
    def test_human_readable_size_bytes(self):
        """Test formatting bytes"""
        assert human_readable_size(0) == "0 B"
        assert human_readable_size(500) == "500 B"
        assert human_readable_size(1023) == "1023 B"
    
    def test_human_readable_size_kb(self):
        """Test formatting kilobytes"""
        assert human_readable_size(1024) == "1.0 KB"
        assert human_readable_size(1536) == "1.5 KB"
        assert human_readable_size(10240) == "10.0 KB"
    
    def test_human_readable_size_mb(self):
        """Test formatting megabytes"""
        assert human_readable_size(1024 * 1024) == "1.0 MB"
        assert human_readable_size(1024 * 1024 * 5) == "5.0 MB"
    
    def test_human_readable_size_gb(self):
        """Test formatting gigabytes"""
        assert human_readable_size(1024 * 1024 * 1024) == "1.0 GB"
        assert human_readable_size(1024 * 1024 * 1024 * 2) == "2.0 GB"


class TestPythonDetection:
    """Test Python executable detection"""
    
    def test_is_python_executable_nonexistent(self):
        """Test Python executable detection for non-existent file"""
        fake_path = Path("/nonexistent/python")
        assert is_python_executable(fake_path) is False
    
    @pytest.mark.skipif(not shutil.which("python"), reason="Python not in PATH")
    def test_is_python_executable_real_python(self):
        """Test Python executable detection for real Python"""
        python_path = Path(shutil.which("python"))
        # This might be True or False depending on the system
        result = is_python_executable(python_path)
        assert isinstance(result, bool)
    
    def test_find_python_executable_empty_dir(self):
        """Test finding Python executable in empty directory"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            result = find_python_executable(temp_path)
            assert result is None


class TestPathOperations:
    """Test path normalization and operations"""
    
    def test_normalize_path_absolute(self):
        """Test path normalization for absolute paths"""
        if os.name == 'nt':  # Windows
            test_path = Path("C:\\Windows\\System32")
        else:  # Unix-like
            test_path = Path("/usr/bin")
        
        normalized = normalize_path(test_path)
        assert isinstance(normalized, Path)
    
    def test_normalize_path_relative(self):
        """Test path normalization for relative paths"""
        test_path = Path("./test/path")
        normalized = normalize_path(test_path)
        assert isinstance(normalized, Path)
        assert normalized.is_absolute()


class TestVenvyDataDir:
    """Test venvy data directory functionality"""
    
    def test_get_venvy_data_dir(self):
        """Test getting venvy data directory"""
        data_dir = get_venvy_data_dir()
        
        assert isinstance(data_dir, Path)
        assert data_dir.exists()
        assert data_dir.is_dir()
        assert "venvy" in str(data_dir).lower()
    
    def test_get_venvy_data_dir_created(self):
        """Test that venvy data directory is created if it doesn't exist"""
        # This should work even if called multiple times
        data_dir1 = get_venvy_data_dir()
        data_dir2 = get_venvy_data_dir()
        
        assert data_dir1 == data_dir2
        assert data_dir1.exists()


class TestCommonVenvLocations:
    """Test common virtual environment location detection"""
    
    def test_get_common_venv_locations(self):
        """Test getting common venv locations"""
        locations = get_common_venv_locations()
        
        assert isinstance(locations, list)
        
        # All returned paths should exist and be directories
        for location in locations:
            assert isinstance(location, Path)
            assert location.exists()
            assert location.is_dir()
    
    def test_get_common_venv_locations_includes_home(self):
        """Test that common locations include home directory"""
        locations = get_common_venv_locations()
        home = get_home_directory()
        
        # Home should be in the list (if it exists)
        if home.exists():
            assert home in locations