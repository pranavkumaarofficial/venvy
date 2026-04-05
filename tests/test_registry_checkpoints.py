"""Tests for registry checkpoint operations."""
import json
import pytest
import sqlite3
from pathlib import Path
from venvy.registry import VenvRegistry, CheckpointRecord


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Create a VenvRegistry with a temp database."""
    monkeypatch.setattr("venvy.registry.get_venvy_data_dir", lambda: tmp_path)
    reg = VenvRegistry()
    return reg


class TestCheckpointCRUD:
    def test_create_checkpoint(self, registry):
        cp_id = registry.create_checkpoint(
            env_path=Path("/fake/env"),
            name="test-cp",
            pip_freeze=["requests==2.31.0", "flask==3.0.0"],
            python_version="3.11.0",
        )
        assert cp_id is not None
        assert cp_id > 0

    def test_get_checkpoint(self, registry):
        cp_id = registry.create_checkpoint(
            env_path=Path("/fake/env"),
            name="test-cp",
            pip_freeze=["requests==2.31.0"],
            python_version="3.11.0",
        )
        cp = registry.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.name == "test-cp"
        assert cp.pip_freeze == ["requests==2.31.0"]
        assert cp.python_version == "3.11.0"
        assert cp.package_count == 1

    def test_get_checkpoint_by_name(self, registry):
        env_path = Path("/fake/env")
        registry.create_checkpoint(
            env_path=env_path, name="my-cp",
            pip_freeze=["numpy==1.26.0"], python_version="3.11.0",
        )
        cp = registry.get_checkpoint_by_name(env_path, "my-cp")
        assert cp is not None
        assert cp.name == "my-cp"
        assert cp.pip_freeze == ["numpy==1.26.0"]

    def test_get_checkpoint_by_name_not_found(self, registry):
        cp = registry.get_checkpoint_by_name(Path("/fake/env"), "nonexistent")
        assert cp is None

    def test_list_checkpoints_ordered(self, registry):
        env_path = Path("/fake/env")
        registry.create_checkpoint(
            env_path=env_path, name="first",
            pip_freeze=["a==1.0"], python_version="3.11.0",
        )
        registry.create_checkpoint(
            env_path=env_path, name="second",
            pip_freeze=["a==1.0", "b==2.0"], python_version="3.11.0",
        )

        checkpoints = registry.list_checkpoints(env_path)
        assert len(checkpoints) == 2
        # Newest first
        assert checkpoints[0].name == "second"
        assert checkpoints[1].name == "first"

    def test_get_latest_checkpoint(self, registry):
        env_path = Path("/fake/env")
        registry.create_checkpoint(
            env_path=env_path, name="old",
            pip_freeze=["a==1.0"], python_version="3.11.0",
        )
        registry.create_checkpoint(
            env_path=env_path, name="new",
            pip_freeze=["a==2.0"], python_version="3.11.0",
        )

        latest = registry.get_latest_checkpoint(env_path)
        assert latest is not None
        assert latest.name == "new"

    def test_get_latest_checkpoint_none(self, registry):
        latest = registry.get_latest_checkpoint(Path("/no/checkpoints"))
        assert latest is None

    def test_delete_checkpoint(self, registry):
        cp_id = registry.create_checkpoint(
            env_path=Path("/fake/env"), name="to-delete",
            pip_freeze=["x==1.0"], python_version="3.11.0",
        )
        assert registry.delete_checkpoint(cp_id) is True
        assert registry.get_checkpoint(cp_id) is None

    def test_delete_nonexistent_checkpoint(self, registry):
        assert registry.delete_checkpoint(99999) is False

    def test_checkpoint_isolation_by_env(self, registry):
        env1 = Path("/fake/env1")
        env2 = Path("/fake/env2")

        registry.create_checkpoint(
            env_path=env1, name="cp1",
            pip_freeze=["a==1.0"], python_version="3.11.0",
        )
        registry.create_checkpoint(
            env_path=env2, name="cp2",
            pip_freeze=["b==1.0"], python_version="3.11.0",
        )

        assert len(registry.list_checkpoints(env1)) == 1
        assert len(registry.list_checkpoints(env2)) == 1
        assert registry.list_checkpoints(env1)[0].name == "cp1"
        assert registry.list_checkpoints(env2)[0].name == "cp2"

    def test_checkpoint_pip_freeze_serialization(self, registry):
        packages = ["numpy==1.26.0", "pandas==2.1.0", "scipy==1.11.0"]
        cp_id = registry.create_checkpoint(
            env_path=Path("/fake/env"), name="big-cp",
            pip_freeze=packages, python_version="3.11.0",
        )
        cp = registry.get_checkpoint(cp_id)
        assert cp.pip_freeze == packages
        assert cp.package_count == 3
