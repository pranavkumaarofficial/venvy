"""
Tests for venvy.dedup — cross-environment hardlink deduplication.

The safety cases matter more than the happy path: a dedup tool that corrupts an
environment is worse than no dedup tool at all.
"""
import os
from pathlib import Path

import pytest

from venvy.dedup import DEFAULT_MIN_SIZE, apply_dedup, find_duplicates

BIG = b"payload-" * 1000        # ~8KB, comfortably over the default min size
OTHER = b"different" * 1000


def _env(base, name, files):
    """Create a fake venv. files: {relative path -> bytes}."""
    env = base / name
    sp = env / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    for rel, content in files.items():
        p = sp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    (env / "pyvenv.cfg").write_text("version = 3.11.0\n", encoding="utf-8")
    return env


def _ino(path):
    return os.stat(str(path)).st_ino


# ---------------------------------------------------------------------------
# Detection.
# ---------------------------------------------------------------------------
def test_finds_identical_file_across_envs(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": BIG})

    report = find_duplicates([a, b], min_size=1)
    assert report.envs_scanned == 2
    assert len(report.groups) == 1
    assert report.groups[0].inodes == 2
    assert report.reclaimable_bytes == len(BIG)      # one redundant copy


def test_different_content_is_not_grouped(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": OTHER})

    report = find_duplicates([a, b], min_size=1)
    assert report.groups == ()
    assert report.reclaimable_bytes == 0


def test_same_size_different_content_not_linked(tmp_path):
    # Guards against grouping on size alone.
    a = _env(tmp_path, "a", {"x.bin": b"A" * 5000})
    b = _env(tmp_path, "b", {"x.bin": b"B" * 5000})

    report = find_duplicates([a, b], min_size=1)
    assert report.reclaimable_bytes == 0


def test_small_files_below_threshold_are_ignored(tmp_path):
    a = _env(tmp_path, "a", {"tiny.txt": b"hello"})
    b = _env(tmp_path, "b", {"tiny.txt": b"hello"})

    assert find_duplicates([a, b], min_size=DEFAULT_MIN_SIZE).reclaimable_bytes == 0
    assert find_duplicates([a, b], min_size=1).reclaimable_bytes == len(b"hello")


# ---------------------------------------------------------------------------
# Safety: bytecode must never be deduplicated (CPython rewrites it in place).
# ---------------------------------------------------------------------------
def test_pyc_and_pycache_are_never_deduplicated(tmp_path):
    a = _env(tmp_path, "a", {"m.pyc": BIG, "__pycache__/m.cpython-311.pyc": BIG})
    b = _env(tmp_path, "b", {"m.pyc": BIG, "__pycache__/m.cpython-311.pyc": BIG})

    report = find_duplicates([a, b], min_size=1)
    assert report.groups == ()
    assert report.reclaimable_bytes == 0


def test_symlinks_are_ignored(tmp_path):
    a = _env(tmp_path, "a", {"real.bin": BIG})
    b = _env(tmp_path, "b", {"real.bin": BIG})
    link = b / "Lib" / "site-packages" / "link.bin"
    try:
        os.symlink(str(b / "Lib" / "site-packages" / "real.bin"), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform/account")

    report = find_duplicates([a, b], min_size=1)
    # Only the two real files group; the symlink is never a candidate.
    assert all("link.bin" not in p for g in report.groups for p in g.paths)


# ---------------------------------------------------------------------------
# Apply.
# ---------------------------------------------------------------------------
def test_apply_creates_hardlink_and_preserves_content(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": BIG})
    fa = a / "Lib" / "site-packages" / "pkg" / "data.bin"
    fb = b / "Lib" / "site-packages" / "pkg" / "data.bin"
    assert _ino(fa) != _ino(fb)

    report = apply_dedup(find_duplicates([a, b], min_size=1), min_size=1)

    assert report.applied is True
    assert report.linked_files == 1
    assert report.reclaimed_bytes == len(BIG)
    assert _ino(fa) == _ino(fb)               # now one inode
    assert fa.read_bytes() == BIG             # content intact
    assert fb.read_bytes() == BIG
    assert fa.exists() and fb.exists()        # nothing deleted


def test_dry_run_modifies_nothing(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": BIG})
    fa = a / "Lib" / "site-packages" / "pkg" / "data.bin"
    fb = b / "Lib" / "site-packages" / "pkg" / "data.bin"
    before = (_ino(fa), _ino(fb))

    report = find_duplicates([a, b], min_size=1)      # no apply_dedup call

    assert report.applied is False
    assert report.reclaimable_bytes > 0
    assert (_ino(fa), _ino(fb)) == before             # untouched


def test_already_hardlinked_counted_as_shared_not_reclaimable(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {})
    target = b / "Lib" / "site-packages" / "data.bin"
    os.link(str(a / "Lib" / "site-packages" / "pkg" / "data.bin"), str(target))

    report = find_duplicates([a, b], min_size=1)
    assert report.reclaimable_bytes == 0              # nothing left to gain
    assert report.already_shared_bytes == len(BIG)    # credited separately


def test_file_changed_since_scan_is_skipped_not_clobbered(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": BIG})
    fb = b / "Lib" / "site-packages" / "pkg" / "data.bin"

    report = find_duplicates([a, b], min_size=1)
    # Someone rewrites the file between scan and apply.
    fb.write_bytes(OTHER)
    report = apply_dedup(report, min_size=1)

    assert report.linked_files == 0
    assert fb.read_bytes() == OTHER                   # user's data preserved
    assert any("changed since scan" in e for e in report.errors)


def test_apply_is_idempotent(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": BIG})

    apply_dedup(find_duplicates([a, b], min_size=1), min_size=1)
    second = apply_dedup(find_duplicates([a, b], min_size=1), min_size=1)

    assert second.linked_files == 0                   # nothing left to link
    assert second.reclaimable_bytes == 0


def test_three_envs_collapse_to_one_inode(tmp_path):
    envs = [_env(tmp_path, n, {"pkg/data.bin": BIG}) for n in ("a", "b", "c")]
    report = find_duplicates(envs, min_size=1)
    assert report.reclaimable_bytes == len(BIG) * 2   # 3 copies -> 1

    apply_dedup(report, min_size=1)
    inodes = {_ino(e / "Lib" / "site-packages" / "pkg" / "data.bin") for e in envs}
    assert len(inodes) == 1


# ---------------------------------------------------------------------------
# RECORD-assisted scanning: the dry run may take hashes from pip's RECORD file, but
# apply must never trust them.
# ---------------------------------------------------------------------------
import base64
import hashlib


def _record_hash(content):
    digest = hashlib.sha256(content).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _write_record(env, rows):
    """rows: [(relative path, content-for-hash, size)]"""
    dist = env / "Lib" / "site-packages" / "pkg-1.0.dist-info"
    dist.mkdir(exist_ok=True)
    lines = ["%s,%s,%d" % (rel, _record_hash(c), size) for rel, c, size in rows]
    lines.append("pkg-1.0.dist-info/RECORD,,")
    (dist / "RECORD").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_record_hashes_are_used_when_size_matches(tmp_path):
    envs = [_env(tmp_path, n, {"pkg/data.bin": BIG}) for n in ("a", "b")]
    for e in envs:
        _write_record(e, [("pkg/data.bin", BIG, len(BIG))])

    report = find_duplicates(envs, min_size=1000)
    assert report.record_hashed_files == 2
    assert report.hashed_files == 0
    assert report.reclaimable_bytes == len(BIG)


def test_record_size_mismatch_falls_back_to_hashing(tmp_path):
    envs = [_env(tmp_path, n, {"pkg/data.bin": BIG}) for n in ("a", "b")]
    for e in envs:
        _write_record(e, [("pkg/data.bin", BIG, len(BIG) + 1)])   # stale RECORD

    report = find_duplicates(envs, min_size=1000)
    assert report.record_hashed_files == 0
    assert report.hashed_files == 2
    assert report.reclaimable_bytes == len(BIG)


def test_use_record_false_hashes_everything(tmp_path):
    envs = [_env(tmp_path, n, {"pkg/data.bin": BIG}) for n in ("a", "b")]
    for e in envs:
        _write_record(e, [("pkg/data.bin", BIG, len(BIG))])

    report = find_duplicates(envs, min_size=1000, use_record=False)
    assert report.record_hashed_files == 0
    assert report.hashed_files == 2


def test_forged_record_cannot_cause_a_bad_link(tmp_path):
    """Two same-size files with different content, and a RECORD that lies that they
    match. The dry run is allowed to be fooled; apply must not be."""
    a_content, b_content = b"A" * 5000, b"B" * 5000
    a = _env(tmp_path, "a", {"pkg/data.bin": a_content})
    b = _env(tmp_path, "b", {"pkg/data.bin": b_content})
    _write_record(a, [("pkg/data.bin", a_content, 5000)])
    _write_record(b, [("pkg/data.bin", a_content, 5000)])         # the lie

    report = find_duplicates([a, b], min_size=1000)
    assert len(report.groups) == 1                                 # fooled, by design

    report = apply_dedup(report, min_size=1000)
    fa = a / "Lib" / "site-packages" / "pkg" / "data.bin"
    fb = b / "Lib" / "site-packages" / "pkg" / "data.bin"
    assert report.linked_files == 0
    assert fa.read_bytes() == a_content
    assert fb.read_bytes() == b_content
    assert _ino(fa) != _ino(fb)


def test_record_entries_outside_site_packages_are_ignored(tmp_path):
    a = _env(tmp_path, "a", {"pkg/data.bin": BIG})
    b = _env(tmp_path, "b", {"pkg/data.bin": BIG})
    outside = tmp_path / "a" / "Scripts" / "tool.exe"
    outside.parent.mkdir()
    outside.write_bytes(BIG)
    for e in (a, b):
        _write_record(e, [("pkg/data.bin", BIG, len(BIG)),
                          ("../../Scripts/tool.exe", BIG, len(BIG))])

    report = find_duplicates([a, b], min_size=1000)
    assert report.files_scanned == 2              # tool.exe is outside site-packages
    assert all("Scripts" not in p for g in report.groups for p in g.paths)
