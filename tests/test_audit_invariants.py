"""
The three promises the README makes about a scan, as tests:

  1. venvy never imports or executes code from the environment it scans.
  2. venvy never spawns a subprocess during a scan.
  3. venvy never opens a network connection when a usable database exists.

Each test plants a trap that would fire if the promise were broken, then asserts the
scan still produced the right answer and the trap never fired.
"""
import json
import os
import socket
import subprocess
import sys

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


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "audit" / "osv.sqlite"
    compile_database(dbfile, [
        _osv("PYSEC-REQ", "requests", events=[{"introduced": "0"}, {"fixed": "2.20.0"}]),
        _osv("MAL-1", "reqeusts", versions=["9.9.9"]),
    ])
    monkeypatch.setattr(audit_db, "default_db_path", lambda: dbfile)
    return dbfile


def _booby_trapped_env(base, marker):
    """An env holding a malicious package whose code, if run by any route, writes `marker`."""
    env = base / "trapped"
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("version = 3.11.0\n", encoding="utf-8")

    payload = "open(%r, 'w').write('executed')\n" % str(marker)
    pkg = sp / "reqeusts"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(payload, encoding="utf-8")

    dist = sp / "reqeusts-9.9.9.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: reqeusts\nVersion: 9.9.9\n", encoding="utf-8")
    (dist / "entry_points.txt").write_text(
        "[console_scripts]\nreqeusts = reqeusts:main\n", encoding="utf-8")

    # Interpreter-startup hooks: these run when *that env's* Python starts.
    (sp / "zz_trap.pth").write_text("import os; " + payload, encoding="utf-8")
    (sp / "sitecustomize.py").write_text(payload, encoding="utf-8")

    (sp / "requests-2.19.0.dist-info").mkdir()   # plus one ordinary vulnerable package
    return env


def test_scan_never_executes_scanned_code(tmp_path, patched_db):
    marker = tmp_path / "EXECUTED"
    env = _booby_trapped_env(tmp_path, marker)

    result = CliRunner().invoke(main, ["audit", "--json", "--offline", "--env", str(env)])

    assert result.exit_code == 21, result.output        # still detected as malicious
    ids = {f["advisory_id"] for f in json.loads(result.output)["environments"][0]["findings"]}
    assert ids == {"MAL-1", "PYSEC-REQ"}
    assert not marker.exists(), "scanned package code was executed"
    assert "reqeusts" not in sys.modules


def test_scan_never_spawns_a_subprocess(tmp_path, patched_db, monkeypatch):
    marker = tmp_path / "EXECUTED"
    env = _booby_trapped_env(tmp_path, marker)

    def no_subprocess(*a, **k):
        raise AssertionError("subprocess spawned during scan: %r" % (a[:1],))
    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    monkeypatch.setattr(os, "system", no_subprocess)

    result = CliRunner().invoke(main, ["audit", "--json", "--offline", "--env", str(env)])

    assert result.exit_code == 21, result.output
    assert not marker.exists()


@pytest.mark.parametrize("flags", [["--offline"], []], ids=["offline", "default"])
def test_scan_opens_no_sockets_with_usable_db(tmp_path, patched_db, monkeypatch, flags):
    """With a usable database, even the default (non --offline) path must not network."""
    def no_network(*a, **k):
        raise AssertionError("network access attempted during scan")
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)

    env = tmp_path / "proj"
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    (sp / "requests-2.19.0.dist-info").mkdir()
    (env / "pyvenv.cfg").write_text("version = 3.11.0\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["audit", "--json", "--env", str(env)] + flags)

    assert result.exit_code == 20, result.output
    finding = json.loads(result.output)["environments"][0]["findings"][0]
    assert finding["advisory_id"] == "PYSEC-REQ"
