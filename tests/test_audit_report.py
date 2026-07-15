"""
Tests for venvy.audit.report — exit-code policy and JSON contract.
"""
import pytest

from venvy.audit.db import AdvisoryDB, compile_database
from venvy.audit.report import build_json, decide_exit_code, severity_label
from venvy.audit.scanner import ScanResult, ScanStats, scan
from venvy.exit_codes import ExitCode


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
def db(tmp_path):
    records = [
        _osv("PYSEC-REQ", "requests", events=[{"introduced": "0"}, {"fixed": "2.20.0"}]),
        _osv("MAL-1", "reqeusts", versions=["9.9.9"]),
        _osv("PYSEC-VAGUE", "vaguepkg"),
        _osv("PYSEC-PIP", "pip", events=[{"introduced": "0"}, {"fixed": "99.0"}]),
    ]
    dbfile = tmp_path / "audit" / "osv.sqlite"
    compile_database(dbfile, records)
    return AdvisoryDB(dbfile)


def _env(base, name, dists):
    env = base / name
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    for d in dists:
        (sp / d).mkdir()
    (env / "pyvenv.cfg").write_text("version = 3.11.0\n", encoding="utf-8")
    return env


# ---------------------------------------------------------------------------
# Exit-code precedence.
# ---------------------------------------------------------------------------
def test_exit_clean(tmp_path, db):
    env = _env(tmp_path, "p", ["requests-2.31.0.dist-info"])
    with db:
        assert decide_exit_code(scan(env_paths=[env], db=db)) == ExitCode.SUCCESS


def test_exit_vulnerable(tmp_path, db):
    env = _env(tmp_path, "p", ["requests-2.19.0.dist-info"])
    with db:
        assert decide_exit_code(scan(env_paths=[env], db=db)) == ExitCode.AUDIT_VULNERABLE


def test_exit_malicious_dominates(tmp_path, db):
    env = _env(tmp_path, "p", ["requests-2.19.0.dist-info", "reqeusts-9.9.9.dist-info"])
    with db:
        # both vulnerable and malicious present -> malicious wins
        assert decide_exit_code(scan(env_paths=[env], db=db)) == ExitCode.AUDIT_MALICIOUS


def test_exit_partial_on_unknown(tmp_path, db):
    env = _env(tmp_path, "p", ["vaguepkg-1.0.0.dist-info"])
    with db:
        assert decide_exit_code(scan(env_paths=[env], db=db)) == ExitCode.AUDIT_STALE_OR_PARTIAL


# ---------------------------------------------------------------------------
# Toolchain gating: excluded by default, included on request.
# ---------------------------------------------------------------------------
def test_toolchain_does_not_fail_gate_by_default(tmp_path, db):
    env = _env(tmp_path, "p", ["pip-22.0.4.dist-info"])   # only pip vulnerable
    with db:
        result = scan(env_paths=[env], db=db)
    assert decide_exit_code(result, include_toolchain=False) == ExitCode.SUCCESS
    assert decide_exit_code(result, include_toolchain=True) == ExitCode.AUDIT_VULNERABLE


# ---------------------------------------------------------------------------
# Stale DB drives the exit code even with no findings.
# ---------------------------------------------------------------------------
def test_stale_db_is_partial():
    result = ScanResult(environments=(), db_meta={"stale": True}, stats=ScanStats())
    assert decide_exit_code(result) == ExitCode.AUDIT_STALE_OR_PARTIAL


def test_fresh_empty_is_clean():
    result = ScanResult(environments=(), db_meta={"stale": False}, stats=ScanStats())
    assert decide_exit_code(result) == ExitCode.SUCCESS


# ---------------------------------------------------------------------------
# JSON contract.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("HIGH", "HIGH"),
    ("moderate", "MODERATE"),
    ("", "UNKNOWN"),
    # CVSS v3.1 vectors -> qualitative bands
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "CRITICAL"),   # 9.8
    ("CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", "LOW"),        # ~2.0
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:L/A:N", "MEDIUM"),     # ~5.4
    ("CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P", "CVSS"),                # v2 not computed
])
def test_severity_label(raw, expected):
    assert severity_label(raw) == expected


def test_json_schema_shape(tmp_path, db):
    env = _env(tmp_path, "p", ["requests-2.19.0.dist-info"])
    with db:
        result = scan(env_paths=[env], db=db)
    exit_code = decide_exit_code(result)
    payload = build_json(result, exit_code)

    assert payload["schema_version"] == 1
    assert payload["exit_code"] == ExitCode.AUDIT_VULNERABLE
    assert payload["success"] is False
    assert "db" in payload and "summary" in payload
    assert payload["summary"]["affected_packages"] == 1
    finding = payload["environments"][0]["findings"][0]
    for key in ("package", "version", "advisory_id", "kind", "status",
                "severity", "fixed_versions", "toolchain"):
        assert key in finding
    assert finding["advisory_id"] == "PYSEC-REQ"
    assert finding["toolchain"] is False
