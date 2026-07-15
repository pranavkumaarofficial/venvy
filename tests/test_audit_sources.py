"""
Tests for venvy.audit.sources — DataDog + typosquat feeds converted to OSV records.

Offline: the converter functions are fed in-memory manifests/CSV, then run through the
real compile + query + matcher path to prove they classify and match correctly.
"""
import json

import pytest

from venvy.audit.db import AdvisoryDB, compile_database
from venvy.audit.matcher import MatchStatus, version_status
from venvy.audit.sources import datadog_to_osv, typosquats_to_osv


def _build(tmp_path, records):
    dbfile = tmp_path / "audit" / "osv.sqlite"
    report = compile_database(dbfile, records)
    return dbfile, report


# ---------------------------------------------------------------------------
# DataDog manifest -> malicious records.
# ---------------------------------------------------------------------------
def test_datadog_null_means_all_versions_malicious(tmp_path):
    manifest = {"evilpkg": None}
    dbfile, report = _build(tmp_path, list(datadog_to_osv(manifest)))
    assert report.malicious == 1
    with AdvisoryDB(dbfile) as db:
        m = db.advisories_for("evilpkg")[0]
        assert m.kind == "malicious"
        # every version is malicious
        assert version_status("0.0.1", m.affected) == MatchStatus.AFFECTED
        assert version_status("99.0", m.affected) == MatchStatus.AFFECTED


def test_datadog_specific_versions(tmp_path):
    manifest = {"halfevil": ["1.0.0", "1.0.1"]}
    dbfile, _ = _build(tmp_path, list(datadog_to_osv(manifest)))
    with AdvisoryDB(dbfile) as db:
        m = db.advisories_for("halfevil")[0]
        assert version_status("1.0.0", m.affected) == MatchStatus.AFFECTED
        assert version_status("2.0.0", m.affected) == MatchStatus.NOT_AFFECTED


def test_datadog_empty_version_list_is_all_versions(tmp_path):
    dbfile, _ = _build(tmp_path, list(datadog_to_osv({"weird": []})))
    with AdvisoryDB(dbfile) as db:
        m = db.advisories_for("weird")[0]
        assert version_status("3.1.4", m.affected) == MatchStatus.AFFECTED


# ---------------------------------------------------------------------------
# Typosquat CSV -> malicious records.
# ---------------------------------------------------------------------------
_CSV = (
    "malicious_package,target_package,ecosystem,registry,classification,source\n"
    "reqeusts,requests,pypi,https://pypi.org,repetition,ossf/malicious-packages\n"
    "left-pad,left-pad,npm,https://npmjs.com,x,y\n"                 # non-pypi -> skip
    "djangoo,django,pypi,https://pypi.org,repetition,datadog\n"
    "reqeusts,requests,pypi,https://pypi.org,swap,other-source\n"   # duplicate -> deduped
)


def test_typosquats_pypi_only_and_dedup(tmp_path):
    records = list(typosquats_to_osv(_CSV))
    names = [r["affected"][0]["package"]["name"] for r in records]
    assert names == ["reqeusts", "djangoo"]        # npm skipped, duplicate deduped


def test_typosquat_flags_any_version_with_target_in_summary(tmp_path):
    dbfile, report = _build(tmp_path, list(typosquats_to_osv(_CSV)))
    assert report.malicious == 2
    with AdvisoryDB(dbfile) as db:
        m = db.advisories_for("reqeusts")[0]
        assert m.kind == "malicious"
        assert "requests" in m.summary          # names the legit target
        assert version_status("1.0.0", m.affected) == MatchStatus.AFFECTED


# ---------------------------------------------------------------------------
# Mixed OSV + enrichment compile, plus provenance round-trip.
# ---------------------------------------------------------------------------
def test_mixed_sources_and_provenance(tmp_path):
    osv = {
        "id": "PYSEC-1", "summary": "vuln",
        "affected": [{"package": {"ecosystem": "PyPI", "name": "requests"},
                      "ranges": [{"type": "ECOSYSTEM",
                                  "events": [{"introduced": "0"}, {"fixed": "2.20"}]}]}],
    }
    records = [osv] + list(datadog_to_osv({"evilpkg": None})) + list(typosquats_to_osv(_CSV))
    dbfile = tmp_path / "audit" / "osv.sqlite"
    report = compile_database(
        dbfile, records,
        source_meta={"sources": [
            {"name": "osv-pypi", "url": "u1"},
            {"name": "datadog-malicious", "url": "u2"},
            {"name": "typosquat", "url": "u3"},
        ]},
    )
    # 1 vuln advisory + 1 datadog malicious + 2 typosquat malicious.
    assert report.malicious == 3
    with AdvisoryDB(dbfile) as db:
        provenance = json.loads(db.meta["sources"])
        assert [s["name"] for s in provenance] == [
            "osv-pypi", "datadog-malicious", "typosquat"]
        assert db.advisories_for("requests")[0].kind == "vulnerability"
        assert db.advisories_for("evilpkg")[0].kind == "malicious"
