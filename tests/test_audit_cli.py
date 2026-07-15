"""
CLI tests for `venvy audit` via click's CliRunner. Offline: a synthetic DB is built in
tmp and default_db_path is monkeypatched to point at it.
"""
import json

import pytest
from click.testing import CliRunner

import venvy.audit.db as audit_db
from venvy.audit.db import compile_database
from venvy.cli import main


def _osv(id, name, events=None, versions=None):
    return {
        "id": id, "summary": "adv %s" % id,
        "affected": [{
            "package": {"ecosystem": "PyPI", "name": name},
            "ranges": ([{"type": "ECOSYSTEM", "events": events}] if events else []),
            "versions": versions or [],
        }],
    }


def _env(base, name, dists):
    env = base / name
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    for d in dists:
        (sp / d).mkdir()
    (env / "pyvenv.cfg").write_text("version = 3.11.0\n", encoding="utf-8")
    return env


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "audit" / "osv.sqlite"
    compile_database(dbfile, [
        _osv("PYSEC-REQ", "requests", events=[{"introduced": "0"}, {"fixed": "2.20.0"}]),
        _osv("MAL-1", "reqeusts", versions=["9.9.9"]),
    ])
    monkeypatch.setattr(audit_db, "default_db_path", lambda: dbfile)
    return dbfile


def test_audit_json_vulnerable(tmp_path, patched_db):
    env = _env(tmp_path, "proj", ["requests-2.19.0.dist-info"])
    result = CliRunner().invoke(main, ["audit", "--json", "--env", str(env)])
    assert result.exit_code == 20
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["summary"]["affected_packages"] == 1
    assert payload["environments"][0]["findings"][0]["advisory_id"] == "PYSEC-REQ"


def test_audit_json_clean(tmp_path, patched_db):
    env = _env(tmp_path, "proj", ["requests-2.31.0.dist-info"])
    result = CliRunner().invoke(main, ["audit", "--json", "--env", str(env)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["summary"]["affected_packages"] == 0


def test_audit_json_malicious(tmp_path, patched_db):
    env = _env(tmp_path, "proj", ["reqeusts-9.9.9.dist-info"])
    result = CliRunner().invoke(main, ["audit", "--json", "--env", str(env)])
    assert result.exit_code == 21
    payload = json.loads(result.output)
    assert payload["environments"][0]["findings"][0]["kind"] == "malicious"


def test_audit_human_output(tmp_path, patched_db):
    env = _env(tmp_path, "proj", ["requests-2.19.0.dist-info"])
    result = CliRunner().invoke(main, ["audit", "--env", str(env)])
    assert result.exit_code == 20
    assert "PYSEC-REQ" in result.output
    assert "affected" in result.output.lower()


def test_audit_missing_db_exit_23(tmp_path, monkeypatch):
    missing = tmp_path / "nope" / "osv.sqlite"
    monkeypatch.setattr(audit_db, "default_db_path", lambda: missing)
    env = _env(tmp_path, "proj", ["requests-2.19.0.dist-info"])
    result = CliRunner().invoke(main, ["audit", "--json", "--env", str(env)])
    assert result.exit_code == 23
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert "refresh" in payload["error"]
