"""
Tests for venvy.audit.scanner — orchestration, dedup, ordering, stats.

Fully offline: synthetic advisory DB + synthetic site-packages trees. Exercises the
end-to-end path (inventory -> match -> assemble) that the CLI will sit on top of.
"""
import pytest

from venvy.audit.db import AdvisoryDB, compile_database
from venvy.audit.scanner import scan


# ---------------------------------------------------------------------------
# Fixtures: advisory DB + environments.
# ---------------------------------------------------------------------------
def _osv(id, name, events=None, versions=None):
    return {
        "id": id,
        "summary": "advisory %s" % id,
        "affected": [{
            "package": {"ecosystem": "PyPI", "name": name},
            "ranges": ([{"type": "ECOSYSTEM", "events": events}] if events else []),
            "versions": versions or [],
        }],
    }


@pytest.fixture
def db(tmp_path):
    records = [
        # requests < 2.20 vulnerable
        _osv("PYSEC-REQ", "requests", events=[{"introduced": "0"}, {"fixed": "2.20.0"}]),
        # a malicious typosquat, specific version
        _osv("MAL-2026-1", "reqeusts", versions=["9.9.9"]),
        # an unscoped advisory -> UNKNOWN for any version of vaguepkg
        _osv("PYSEC-VAGUE", "vaguepkg"),
        # a toolchain package advisory (pip)
        _osv("PYSEC-PIP", "pip", events=[{"introduced": "0"}, {"fixed": "23.3"}]),
    ]
    dbfile = tmp_path / "audit" / "osv.sqlite"
    compile_database(dbfile, records)
    return AdvisoryDB(dbfile)


def _make_env(base, envname, packages):
    """packages: list of (dirname). Creates a Windows-layout venv site-packages."""
    env = base / envname
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    for dn in packages:
        (sp / dn).mkdir()
    (env / "pyvenv.cfg").write_text("version = 3.11.0\n", encoding="utf-8")
    return env


# ---------------------------------------------------------------------------
# Detection: vulnerable, malicious, clean.
# ---------------------------------------------------------------------------
def test_detects_vulnerable_package(tmp_path, db):
    env = _make_env(tmp_path, "proj", ["requests-2.19.0.dist-info"])
    with db:
        result = scan(env_paths=[env], db=db)
    assert result.stats.vulnerable_findings == 1
    er = result.environments[0]
    assert er.affected[0].advisory_id == "PYSEC-REQ"
    assert er.affected[0].kind == "vulnerability"


def test_clean_package_no_findings(tmp_path, db):
    env = _make_env(tmp_path, "proj", ["requests-2.31.0.dist-info"])  # patched
    with db:
        result = scan(env_paths=[env], db=db)
    assert result.stats.vulnerable_findings == 0
    assert result.environments[0].findings == ()


def test_detects_malicious_and_orders_first(tmp_path, db):
    env = _make_env(tmp_path, "proj", [
        "requests-2.19.0.dist-info",     # vulnerable
        "reqeusts-9.9.9.dist-info",      # malicious typosquat
    ])
    with db:
        result = scan(env_paths=[env], db=db)
    assert result.stats.malicious_findings == 1
    assert result.stats.vulnerable_findings == 1
    # Malicious sorts before vulnerability in the env's findings.
    kinds = [f.kind for f in result.environments[0].findings]
    assert kinds[0] == "malicious"


def test_unknown_is_surfaced_not_clean(tmp_path, db):
    env = _make_env(tmp_path, "proj", ["vaguepkg-1.0.0.dist-info"])
    with db:
        result = scan(env_paths=[env], db=db)
    assert result.stats.unknown_findings == 1
    assert result.environments[0].unknown[0].advisory_id == "PYSEC-VAGUE"
    # Unknown must NOT count as vulnerable/clean.
    assert result.stats.vulnerable_findings == 0


# ---------------------------------------------------------------------------
# Dedup accounting across environments.
# ---------------------------------------------------------------------------
def test_dedup_shared_package_across_envs(tmp_path, db):
    # Two envs both contain the identical vulnerable requests + a clean shared pkg.
    e1 = _make_env(tmp_path, "a", ["requests-2.19.0.dist-info", "click-8.1.7.dist-info"])
    e2 = _make_env(tmp_path, "b", ["requests-2.19.0.dist-info", "click-8.1.7.dist-info"])
    with db:
        result = scan(env_paths=[e1, e2], db=db)

    # 4 installed packages total, but only 2 unique (name, version).
    assert result.stats.packages_scanned == 4
    assert result.stats.unique_packages == 2
    # Both envs are independently flagged.
    assert result.stats.vulnerable_findings == 2
    assert result.stats.affected_packages == 2   # (env-a, requests) and (env-b, requests)
    for er in result.environments:
        assert any(f.advisory_id == "PYSEC-REQ" for f in er.affected)


# ---------------------------------------------------------------------------
# Errors and metadata.
# ---------------------------------------------------------------------------
def test_env_read_error_is_surfaced(tmp_path, db):
    missing = tmp_path / "ghost"      # does not exist
    with db:
        result = scan(env_paths=[missing], db=db)
    er = result.environments[0]
    assert er.errors                  # error recorded
    assert er.package_count == 0
    assert er.findings == ()          # never confused with clean


def test_db_meta_present(tmp_path, db):
    env = _make_env(tmp_path, "proj", ["click-8.1.7.dist-info"])
    with db:
        result = scan(env_paths=[env], db=db)
    assert result.db_meta["advisory_count"] == "4"
    assert result.db_meta["stale"] is False
    assert result.db_meta["age_days"] is not None


def test_deterministic_env_ordering(tmp_path, db):
    ez = _make_env(tmp_path, "zeta", ["click-8.1.7.dist-info"])
    ea = _make_env(tmp_path, "alpha", ["click-8.1.7.dist-info"])
    with db:
        result = scan(env_paths=[ez, ea], db=db)
    paths = [e.path.lower() for e in result.environments]
    assert paths == sorted(paths)


def test_toolchain_split_from_headline(tmp_path, db):
    # An env with a vulnerable app dep (requests) AND vulnerable toolchain (pip).
    env = _make_env(tmp_path, "proj", [
        "requests-2.19.0.dist-info",     # app dependency -> headline
        "pip-22.0.4.dist-info",          # toolchain -> separate tally
    ])
    with db:
        result = scan(env_paths=[env], db=db)
    # Headline counts only the app package; pip is tallied separately.
    assert result.stats.affected_packages == 1
    assert result.stats.toolchain_affected_packages == 1
    # Both are still reported as findings; toolchain flagged and sorted last.
    findings = result.environments[0].findings
    assert any(f.toolchain and f.package == "pip" for f in findings)
    assert findings[0].package == "requests"      # app dep before toolchain
    assert findings[-1].package == "pip"


def test_fixed_versions_reported(tmp_path, db):
    env = _make_env(tmp_path, "proj", ["requests-2.19.0.dist-info"])
    with db:
        result = scan(env_paths=[env], db=db)
    finding = result.environments[0].affected[0]
    assert "2.20.0" in finding.fixed_versions
