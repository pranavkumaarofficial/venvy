"""
Tests for venvy.audit.db — compile + query, fully offline (synthetic OSV records).

These prove the DB round-trip preserves the exact semantics the matcher relies on:
withdrawn advisories never match, malicious is classified, unscoped survives storage,
and querying + evaluating a real installed version gives the right verdict.
"""
import json

import pytest

from venvy.audit.db import AdvisoryDB, compile_database
from venvy.audit.matcher import MatchStatus, version_status


def _osv(id, name, events=None, versions=None, withdrawn=None, aliases=None):
    rec = {
        "id": id,
        "aliases": aliases or [],
        "summary": "test advisory %s" % id,
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": name},
                "ranges": ([{"type": "ECOSYSTEM", "events": events}] if events else []),
                "versions": versions or [],
            }
        ],
    }
    if withdrawn:
        rec["withdrawn"] = withdrawn
    return rec


def _build(tmp_path, records):
    dbfile = tmp_path / "audit" / "osv.sqlite"
    report = compile_database(dbfile, records)
    return dbfile, report


# ---------------------------------------------------------------------------
# Compile + basic query round-trip.
# ---------------------------------------------------------------------------
def test_compile_and_query_roundtrip(tmp_path):
    records = [
        _osv("PYSEC-1", "Django",
             events=[{"introduced": "0"}, {"fixed": "3.2.14"}],
             aliases=["CVE-2022-1"]),
    ]
    dbfile, report = _build(tmp_path, records)
    assert report.advisories == 1
    assert report.affected_rows == 1

    with AdvisoryDB(dbfile) as db:
        matches = db.advisories_for("django")   # canonical name
        assert len(matches) == 1
        m = matches[0]
        assert m.id == "PYSEC-1"
        assert m.kind == "vulnerability"
        assert "CVE-2022-1" in m.aliases
        assert version_status("3.2.0", m.affected) == MatchStatus.AFFECTED
        assert version_status("3.2.14", m.affected) == MatchStatus.NOT_AFFECTED


def test_query_unknown_package_returns_empty(tmp_path):
    dbfile, _ = _build(tmp_path, [_osv("PYSEC-1", "Django",
                                       events=[{"introduced": "0"}, {"fixed": "1.0"}])])
    with AdvisoryDB(dbfile) as db:
        assert db.advisories_for("nonexistent-pkg") == []


# ---------------------------------------------------------------------------
# Withdrawn advisories are recorded but NEVER matched.
# ---------------------------------------------------------------------------
def test_withdrawn_advisory_is_not_indexed(tmp_path):
    records = [
        _osv("PYSEC-OLD", "requests",
             events=[{"introduced": "0"}, {"fixed": "9.9"}],
             withdrawn="2024-01-01T00:00:00Z"),
    ]
    dbfile, report = _build(tmp_path, records)
    assert report.advisories == 1          # recorded
    assert report.affected_rows == 0       # but not indexed
    with AdvisoryDB(dbfile) as db:
        assert db.advisories_for("requests") == []


# ---------------------------------------------------------------------------
# Malicious classification via MAL- id prefix.
# ---------------------------------------------------------------------------
def test_malicious_classification(tmp_path):
    records = [
        _osv("MAL-2026-0001", "evil-typosquat", versions=["1.0.0"]),
    ]
    dbfile, report = _build(tmp_path, records)
    assert report.malicious == 1
    with AdvisoryDB(dbfile) as db:
        matches = db.advisories_for("evil-typosquat")
        assert matches[0].kind == "malicious"
        assert version_status("1.0.0", matches[0].affected) == MatchStatus.AFFECTED


# ---------------------------------------------------------------------------
# Unscoped affected entry survives storage and forces UNKNOWN.
# ---------------------------------------------------------------------------
def test_unscoped_roundtrip_is_unknown(tmp_path):
    # No ranges, no versions -> unscoped -> must fail closed to UNKNOWN.
    records = [_osv("PYSEC-VAGUE", "somepkg")]
    dbfile, report = _build(tmp_path, records)
    assert report.affected_rows == 1
    with AdvisoryDB(dbfile) as db:
        m = db.advisories_for("somepkg")[0]
        assert m.affected.unscoped is True
        assert version_status("1.2.3", m.affected) == MatchStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Malformed records are skipped, not fatal.
# ---------------------------------------------------------------------------
def test_bad_records_are_skipped(tmp_path):
    records = [
        {"no_id": True},                                  # missing id -> skipped
        _osv("PYSEC-OK", "flask", events=[{"introduced": "0"}, {"fixed": "2.0"}]),
        {"id": "PYSEC-WEIRD", "affected": "not-a-list"},  # malformed -> counted, safe
    ]
    dbfile, report = _build(tmp_path, records)
    with AdvisoryDB(dbfile) as db:
        assert len(db.advisories_for("flask")) == 1
    # The good one indexed; the malformed ones didn't crash the build.
    assert report.records_total == 3
    assert report.affected_rows == 1


# ---------------------------------------------------------------------------
# Multi-ecosystem record: only the PyPI affected entry is indexed.
# ---------------------------------------------------------------------------
def test_only_pypi_ecosystem_indexed(tmp_path):
    rec = {
        "id": "GHSA-multi",
        "summary": "multi ecosystem",
        "affected": [
            {"package": {"ecosystem": "npm", "name": "left-pad"},
             "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}]}]},
            {"package": {"ecosystem": "PyPI", "name": "pyleftpad"},
             "ranges": [{"type": "ECOSYSTEM",
                         "events": [{"introduced": "0"}, {"fixed": "2.0"}]}]},
        ],
    }
    dbfile, report = _build(tmp_path, [rec])
    assert report.affected_rows == 1
    with AdvisoryDB(dbfile) as db:
        assert db.advisories_for("pyleftpad")          # PyPI one present
        assert db.advisories_for("left-pad") == []     # npm one skipped


# ---------------------------------------------------------------------------
# Meta / provenance and staleness.
# ---------------------------------------------------------------------------
def test_meta_and_freshness(tmp_path):
    dbfile, _ = _build(tmp_path, [_osv("PYSEC-1", "x",
                                       events=[{"introduced": "0"}, {"fixed": "1.0"}])])
    with AdvisoryDB(dbfile) as db:
        assert db.meta["schema_version"] == "1"
        assert db.built_at() is not None
        assert db.age_days() < 1
        assert db.is_stale(threshold_days=14) is False
        assert db.is_stale(threshold_days=0) is True   # everything is "older than 0 days"


def test_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        AdvisoryDB(tmp_path / "nope.sqlite")


# ---------------------------------------------------------------------------
# Atomic rebuild: recompiling over an existing DB replaces it cleanly.
# ---------------------------------------------------------------------------
def test_rebuild_replaces_atomically(tmp_path):
    dbfile = tmp_path / "audit" / "osv.sqlite"
    compile_database(dbfile, [_osv("A", "pkg-a", events=[{"introduced": "0"}])])
    with AdvisoryDB(dbfile) as db:
        assert db.advisories_for("pkg-a")
        assert db.advisories_for("pkg-b") == []

    compile_database(dbfile, [_osv("B", "pkg-b", events=[{"introduced": "0"}])])
    with AdvisoryDB(dbfile) as db:
        assert db.advisories_for("pkg-b")
        assert db.advisories_for("pkg-a") == []   # old content gone
