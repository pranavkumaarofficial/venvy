"""
Pytest configuration and fixtures for venvy tests
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock

from venvy.models import EnvironmentInfo, EnvironmentType, HealthStatus


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_venv_dir(temp_dir):
    """Create a mock venv directory structure"""
    venv_path = temp_dir / "test_venv"
    venv_path.mkdir()
    
    # Create pyvenv.cfg
    pyvenv_cfg = venv_path / "pyvenv.cfg"
    pyvenv_cfg.write_text("""home = /usr/bin
include-system-site-packages = false
version = 3.9.7""")
    
    # Create Scripts/bin directory
    if Path().cwd().drive:  # Windows
        scripts_dir = venv_path / "Scripts"
        scripts_dir.mkdir()
        python_exe = scripts_dir / "python.exe"
    else:  # Unix
        scripts_dir = venv_path / "bin"
        scripts_dir.mkdir()
        python_exe = scripts_dir / "python"
    
    # Create mock python executable
    python_exe.write_text("#!/usr/bin/env python3")
    python_exe.chmod(0o755)
    
    # Create activate script
    activate_script = scripts_dir / "activate"
    activate_script.write_text("# Activation script")
    
    return venv_path


@pytest.fixture
def mock_conda_dir(temp_dir):
    """Create a mock conda directory structure"""
    conda_path = temp_dir / "test_conda"
    conda_path.mkdir()
    
    # Create conda-meta directory
    conda_meta = conda_path / "conda-meta"
    conda_meta.mkdir()
    
    # Create history file
    history_file = conda_meta / "history"
    history_file.write_text("""# cmd: conda create --name test_conda python=3.9
# date: 2023-01-01 12:00:00 UTC
""")
    
    # Create bin/Scripts directory with Python
    if Path().cwd().drive:  # Windows
        scripts_dir = conda_path / "Scripts"
        scripts_dir.mkdir()
        python_exe = scripts_dir / "python.exe"
    else:  # Unix
        scripts_dir = conda_path / "bin"
        scripts_dir.mkdir()
        python_exe = scripts_dir / "python"
    
    python_exe.write_text("#!/usr/bin/env python3")
    python_exe.chmod(0o755)
    
    return conda_path


@pytest.fixture
def sample_environment_info():
    """Create sample EnvironmentInfo for testing"""
    return EnvironmentInfo(
        name="test_env",
        path=Path("/test/path"),
        type=EnvironmentType.VENV,
        python_version="3.9.7",
        size_bytes=1024000,
        package_count=25,
        health_status=HealthStatus.HEALTHY,
        days_since_used=15,
        activation_count=50
    )


@pytest.fixture
def sample_environments_list():
    """Create a list of sample environments for testing"""
    environments = []
    
    # Healthy venv
    env1 = EnvironmentInfo(
        name="project1_venv",
        path=Path("/projects/project1/venv"),
        type=EnvironmentType.VENV,
        python_version="3.9.7",
        size_bytes=50 * 1024 * 1024,  # 50 MB
        package_count=30,
        health_status=HealthStatus.HEALTHY,
        days_since_used=5,
        activation_count=100
    )
    environments.append(env1)
    
    # Broken conda env
    env2 = EnvironmentInfo(
        name="old_data_science",
        path=Path("/envs/old_data_science"),
        type=EnvironmentType.CONDA,
        python_version="3.7.0",
        size_bytes=200 * 1024 * 1024,  # 200 MB
        package_count=150,
        health_status=HealthStatus.BROKEN,
        days_since_used=180,
        activation_count=5
    )
    environments.append(env2)
    
    # Outdated virtualenv
    env3 = EnvironmentInfo(
        name="legacy_project",
        path=Path("/home/user/legacy_project/env"),
        type=EnvironmentType.VIRTUALENV,
        python_version="3.6.8",
        size_bytes=25 * 1024 * 1024,  # 25 MB
        package_count=15,
        health_status=HealthStatus.OUTDATED,
        days_since_used=45,
        activation_count=10
    )
    environments.append(env3)
    
    # Large unused environment
    env4 = EnvironmentInfo(
        name="ml_experiment",
        path=Path("/experiments/ml_experiment"),
        type=EnvironmentType.VENV,
        python_version="3.10.0",
        size_bytes=500 * 1024 * 1024,  # 500 MB
        package_count=80,
        health_status=HealthStatus.HEALTHY,
        days_since_used=120,
        activation_count=2
    )
    environments.append(env4)
    
    return environments


@pytest.fixture
def mock_config_file(temp_dir):
    """Create a mock configuration file"""
    config_content = """{
    "schema_version": "1.0",
    "config": {
        "search_paths": ["/home/user/venvs", "/projects"],
        "auto_backup": true,
        "confirm_deletions": true,
        "default_unused_days": 90,
        "default_output_format": "table",
        "default_sort_by": "name",
        "show_system_environments": false,
        "max_suggestions": 10,
        "cleanup_confidence_threshold": 0.7,
        "create_backups": true,
        "backup_retention_days": 30,
        "enable_usage_tracking": true,
        "parallel_analysis": true,
        "cache_results": true,
        "cache_duration_hours": 24
    }
}"""
    config_file = temp_dir / "config.json"
    config_file.write_text(config_content)
    return config_file


@pytest.fixture
def mock_usage_data():
    """Create mock usage tracking data"""
    return {
        "/test/env1": {
            "activations": [
                "2023-01-01T10:00:00",
                "2023-01-02T11:30:00",
                "2023-01-03T14:15:00"
            ],
            "package_changes": [
                "2023-01-01T10:05:00"
            ],
            "first_seen": "2023-01-01T10:00:00"
        },
        "/test/env2": {
            "activations": [
                "2022-06-01T09:00:00"
            ],
            "package_changes": [],
            "first_seen": "2022-06-01T09:00:00"
        }
    }