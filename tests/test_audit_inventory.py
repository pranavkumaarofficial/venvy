"""
Tests for venvy.audit.inventory — reading installed packages from an env, safely.

Uses synthetic site-packages trees (no real venvs, no network) so the behavior is
deterministic and the fail-closed paths are exercised directly.
"""
from pathlib import Path

import pytest

from venvy.audit.inventory import (
    find_site_packages,
    read_env_inventory,
    read_python_version,
)


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------
def _make_win_site(env: Path) -> Path:
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    return sp


def _dist_info(sp: Path, dirname: str, name=None, version=None, metadata_name="METADATA"):
    """Create a .dist-info/.egg-info dir, optionally with a METADATA/PKG-INFO file."""
    d = sp / dirname
    d.mkdir()
    if name is not None or version is not None:
        lines = ["Metadata-Version: 2.1"]
        if name is not None:
            lines.append("Name: %s" % name)
        if version is not None:
            lines.append("Version: %s" % version)
        lines.append("")  # end of headers
        lines.append("Some body text with Name: fake and Version: 9.9 that must be ignored")
        (d / metadata_name).write_text("\n".join(lines), encoding="utf-8")
    return d


def _names(inv):
    return {p.name: p.version for p in inv.packages}


# ---------------------------------------------------------------------------
# Fast path: name+version straight from the dist-info directory name.
# ---------------------------------------------------------------------------
def test_fast_path_dirname_only(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    _dist_info(sp, "requests-2.31.0.dist-info")   # no METADATA at all
    _dist_info(sp, "urllib3-1.26.18.dist-info")

    inv = read_env_inventory(env)
    assert inv.errors == ()
    assert _names(inv) == {"requests": "2.31.0", "urllib3": "1.26.18"}


def test_name_normalization_from_dirname(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    _dist_info(sp, "Flask_SQLAlchemy-3.0.5.dist-info")

    inv = read_env_inventory(env)
    # Canonicalized to match how advisories name the package.
    assert _names(inv) == {"flask-sqlalchemy": "3.0.5"}
    assert inv.packages[0].raw_name == "Flask_SQLAlchemy"


# ---------------------------------------------------------------------------
# METADATA fallback when the dir name is not authoritative.
# ---------------------------------------------------------------------------
def test_metadata_fallback_when_version_unparseable(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    # Dir-name version is garbage -> must fall back to METADATA.
    _dist_info(sp, "weird-notaversion.dist-info", name="weird", version="1.2.3")

    inv = read_env_inventory(env)
    assert _names(inv) == {"weird": "1.2.3"}


def test_egg_info_uses_pkg_info(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    _dist_info(sp, "legacy_pkg.egg-info", name="legacy-pkg", version="0.9",
               metadata_name="PKG-INFO")

    inv = read_env_inventory(env)
    assert _names(inv) == {"legacy-pkg": "0.9"}


# ---------------------------------------------------------------------------
# Error surfacing (invariant #5 — never silent, never "clean").
# ---------------------------------------------------------------------------
def test_unrecognized_metadata_is_reported(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    # No '-' in stem and no METADATA -> cannot determine name/version.
    _dist_info(sp, "brokenpkg.dist-info")

    inv = read_env_inventory(env)
    assert inv.packages == ()
    assert any("brokenpkg.dist-info" in e for e in inv.errors)


def test_missing_env_path_is_error(tmp_path):
    inv = read_env_inventory(tmp_path / "does-not-exist")
    assert inv.packages == ()
    assert inv.errors and "does not exist" in inv.errors[0]


def test_no_site_packages_is_error(tmp_path):
    env = tmp_path / "env"
    env.mkdir()
    inv = read_env_inventory(env)
    assert inv.packages == ()
    assert any("site-packages" in e for e in inv.errors)


# ---------------------------------------------------------------------------
# Non-package entries are ignored; ordering is deterministic.
# ---------------------------------------------------------------------------
def test_ignores_non_metadata_entries(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    _dist_info(sp, "click-8.1.7.dist-info")
    (sp / "click").mkdir()                 # the actual package code dir
    (sp / "some_module.py").write_text("x = 1", encoding="utf-8")
    (sp / "README.txt").write_text("hi", encoding="utf-8")

    inv = read_env_inventory(env)
    assert _names(inv) == {"click": "8.1.7"}


def test_deterministic_sort_order(tmp_path):
    env = tmp_path / "env"
    sp = _make_win_site(env)
    for dn in ["zzz-1.0.dist-info", "aaa-2.0.dist-info", "mmm-3.0.dist-info"]:
        _dist_info(sp, dn)

    inv = read_env_inventory(env)
    assert [p.name for p in inv.packages] == ["aaa", "mmm", "zzz"]


# ---------------------------------------------------------------------------
# POSIX layout + pyvenv.cfg.
# ---------------------------------------------------------------------------
def test_posix_layout_site_packages(tmp_path):
    env = tmp_path / "env"
    sp = env / "lib" / "python3.11" / "site-packages"
    sp.mkdir(parents=True)
    _dist_info(sp, "numpy-1.26.4.dist-info")

    found = find_site_packages(env)
    assert any("site-packages" in str(p) for p in found)

    inv = read_env_inventory(env)
    assert _names(inv) == {"numpy": "1.26.4"}


def test_read_python_version(tmp_path):
    env = tmp_path / "env"
    env.mkdir()
    (env / "pyvenv.cfg").write_text(
        "home = /usr/bin\nversion = 3.11.5\ninclude-system-site-packages = false\n",
        encoding="utf-8",
    )
    assert read_python_version(env) == "3.11.5"


def test_read_python_version_absent(tmp_path):
    env = tmp_path / "env"
    env.mkdir()
    assert read_python_version(env) is None


def test_installed_at_from_dist_info_mtime(tmp_path):
    # The install date is the .dist-info directory mtime, as a local ISO date.
    import os
    from datetime import datetime

    env = tmp_path / "env"
    sp = _make_win_site(env)
    d = _dist_info(sp, "ctx-0.1.2.dist-info", name="ctx", version="0.1.2")
    # Pin the directory mtime to a known instant (2026-07-08 12:00 local).
    ts = datetime(2026, 7, 8, 12, 0, 0).timestamp()
    os.utime(d, (ts, ts))

    inv = read_env_inventory(env)
    pkg = next(p for p in inv.packages if p.name == "ctx")
    assert pkg.installed_at == "2026-07-08"


def test_installed_at_survives_into_scan_json(tmp_path):
    # The date must reach the finding + JSON, per-env, so it can drive blast-radius scoping.
    import os, json
    from datetime import datetime
    from venvy.audit.db import compile_database, AdvisoryDB
    from venvy.audit.scanner import scan
    from venvy.audit import report as R

    dbp = tmp_path / "adv.sqlite"
    compile_database(dbp, [{
        "id": "MAL-DEMO-1", "summary": "x", "database_specific": {"malicious": True},
        "affected": [{"package": {"ecosystem": "PyPI", "name": "ctx"},
                      "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]}],
    }], min_advisories=1)

    env = tmp_path / "env"
    sp = _make_win_site(env)
    d = _dist_info(sp, "ctx-0.1.2.dist-info", name="ctx", version="0.1.2")
    ts = datetime(2026, 7, 8, 12, 0, 0).timestamp()
    os.utime(d, (ts, ts))

    result = scan(env_paths=[env], db_path=dbp)
    finding = result.environments[0].findings[0]
    assert finding.installed_at == "2026-07-08"
    payload = R.build_json(result, R.decide_exit_code(result))
    assert payload["environments"][0]["findings"][0]["installed_at"] == "2026-07-08"
