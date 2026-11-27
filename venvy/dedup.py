"""
dedup.py — reclaim disk space by hardlinking identical files across environments.

Every virtual environment installs its own byte-for-byte copy of the same wheels. Ten
environments with `numpy` store `numpy` ten times. This module finds files that are
provably identical across the environments venvy knows about and replaces the duplicates
with hardlinks, so the bytes exist once on disk. Nothing is deleted; every environment
keeps working exactly as before.

Safety rules (a dedup tool that corrupts an environment is worse than no dedup tool):

  * **Only regular files inside site-packages.** Never symlinks, never anything outside
    a known environment.
  * **Never `.pyc` / `__pycache__`.** CPython rewrites bytecode caches in place, and an
    in-place write to a hardlink mutates every environment sharing that inode. Package
    payload files are treated as immutable (pip/uv replace files rather than editing
    them, which safely breaks the link); bytecode is not.
  * **Byte-identity is verified by hash immediately before linking**, not inferred from
    size or mtime. The read-only scan may take a file's SHA-256 from the RECORD file
    pip wrote at install time (when the size on disk matches), because reading every
    file is the dominant cost. Apply never trusts RECORD: it re-hashes every file it is
    about to link, so a stale or forged RECORD can only cost a skipped file.
  * **Same filesystem only.** Hardlinks cannot cross devices; groups are keyed on st_dev.
  * **Atomic swap.** We link to a temp name and `os.replace` it over the target, so the
    target file is never absent — a crash mid-run leaves the environment intact.
  * **Dry-run by default.** Nothing is modified unless the caller explicitly applies.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from venvy.audit.inventory import find_site_packages

# Files below this size yield little or nothing after filesystem block rounding, and
# linking them burns inodes for no gain.
DEFAULT_MIN_SIZE = 4096

_HASH_CHUNK = 1 << 20

# A RECORD file lists every installed file of one distribution; numpy's is ~150 KB.
# Anything far larger is not a real RECORD and is ignored.
_MAX_RECORD_BYTES = 16 * 1024 * 1024

# Never deduplicate these: CPython may rewrite bytecode caches in place, which would
# propagate through a shared inode into every other environment.
_SKIP_SUFFIXES = (".pyc", ".pyo")
_SKIP_DIR_NAMES = {"__pycache__"}


@dataclass(frozen=True)
class DuplicateGroup:
    """One set of byte-identical files living on the same filesystem."""

    digest: str
    size: int
    paths: Tuple[str, ...]
    inodes: int          # distinct inodes currently backing these paths

    @property
    def reclaimable(self) -> int:
        """Bytes freed by collapsing every distinct inode into one."""
        return self.size * max(0, self.inodes - 1)


@dataclass
class DedupReport:
    envs_scanned: int = 0
    files_scanned: int = 0
    candidate_files: int = 0
    hashed_files: int = 0             # candidates whose content was read and hashed
    record_hashed_files: int = 0      # candidates whose hash came from a RECORD file
    groups: Tuple[DuplicateGroup, ...] = field(default_factory=tuple)
    reclaimable_bytes: int = 0
    already_shared_bytes: int = 0     # savings existing hardlinks already provide
    linked_files: int = 0             # only set when applied
    reclaimed_bytes: int = 0          # only set when applied
    applied: bool = False
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------
def _iter_candidate_files(site_packages: Path, min_size: int):
    """Yield (path, stat) for regular files eligible for deduplication.

    Uses os.scandir so file type and size come from the directory listing: one
    filesystem call per directory instead of three per file. On Windows the returned
    stat has st_ino == 0; callers that need the inode must lstat the path themselves.
    """
    stack = [str(site_packages)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue                  # never follow or rewrite symlinks
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIR_NAMES:
                        stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.name.endswith(_SKIP_SUFFIXES):
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if st.st_size < min_size:
                continue
            yield Path(entry.path), st


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _load_record_hashes(site_packages: Path) -> Dict[str, Tuple[int, str]]:
    """Map installed-file path -> (size, sha256 hex) from every *.dist-info/RECORD.

    Entries without a sha256 hash or size, and entries pointing outside site-packages
    (console scripts, data files), are ignored. A missing or unreadable RECORD just
    means those files get hashed the slow way.
    """
    out: Dict[str, Tuple[int, str]] = {}
    root = _path_key(str(site_packages))
    try:
        dist_infos = [e.path for e in os.scandir(str(site_packages))
                      if e.name.endswith(".dist-info") and e.is_dir(follow_symlinks=False)]
    except OSError:
        return out
    for dist in dist_infos:
        record = os.path.join(dist, "RECORD")
        try:
            if os.path.getsize(record) > _MAX_RECORD_BYTES:
                continue
            with open(record, "rb") as fh:
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 3 or not row[1].startswith("sha256=") or not row[2].isdigit():
                continue
            key = _path_key(os.path.join(str(site_packages), row[0]))
            if not key.startswith(root + os.sep):
                continue
            b64 = row[1][len("sha256="):]
            try:
                digest = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).hex()
            except (ValueError, TypeError):
                continue
            if len(digest) != 64:
                continue
            out[key] = (int(row[2]), digest)
    return out


def _hash_file(path: Path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_HASH_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(
    env_paths: Sequence[Path],
    min_size: int = DEFAULT_MIN_SIZE,
    use_record: bool = True,
) -> DedupReport:
    """Scan environments and report byte-identical files that could share storage.

    Read-only: this never modifies anything. With ``use_record`` (the default), a
    file's hash is taken from its distribution's RECORD when the recorded size matches
    the size on disk; pass False to read and hash every candidate.
    """
    import time

    start = time.time()
    report = DedupReport()

    # Pass 1: bucket by size. Only files matching another file's size can possibly be
    # linkable, so nothing is hashed or even lstat'ed yet.
    by_size: Dict[int, List[Tuple[Path, os.stat_result]]] = {}
    records: Dict[str, Tuple[int, str]] = {}
    for env in env_paths:
        sites = find_site_packages(Path(env))
        if not sites:
            continue
        report.envs_scanned += 1
        for site in sites:
            if use_record:
                records.update(_load_record_hashes(site))
            for path, st in _iter_candidate_files(site, min_size):
                report.files_scanned += 1
                by_size.setdefault(st.st_size, []).append((path, st))

    # Pass 2: for files that share a size, get device, inode and content hash.
    by_content: Dict[Tuple[int, int, str], List[Tuple[Path, os.stat_result]]] = {}
    for size, entries in by_size.items():
        if len(entries) < 2:
            continue
        for path, st in entries:
            report.candidate_files += 1
            if not st.st_ino:                 # Windows scandir stat carries no inode
                try:
                    st = os.lstat(str(path))
                except OSError:
                    report.errors.append("unreadable: %s" % path)
                    continue
            rec = records.get(_path_key(str(path)))
            if rec is not None and rec[0] == st.st_size:
                digest = rec[1]  # type: Optional[str]
                report.record_hashed_files += 1
            else:
                digest = _hash_file(path)
                report.hashed_files += 1
            if digest is None:
                report.errors.append("unreadable: %s" % path)
                continue
            by_content.setdefault((st.st_dev, size, digest), []).append((path, st))

    groups: List[DuplicateGroup] = []
    for (dev, size, digest), entries in by_content.items():
        if len(entries) < 2:
            continue
        distinct_inodes = {st.st_ino for _, st in entries}
        # Files already sharing an inode are already deduplicated; count that saving
        # separately so we never claim credit for it twice.
        already = size * (len(entries) - len(distinct_inodes))
        report.already_shared_bytes += already
        if len(distinct_inodes) < 2:
            continue
        group = DuplicateGroup(
            digest=digest,
            size=size,
            paths=tuple(sorted(str(p) for p, _ in entries)),
            inodes=len(distinct_inodes),
        )
        groups.append(group)
        report.reclaimable_bytes += group.reclaimable

    # Largest wins first — deterministic ordering for stable output.
    groups.sort(key=lambda g: (-g.reclaimable, g.paths[0]))
    report.groups = tuple(groups)
    report.duration_ms = int((time.time() - start) * 1000)
    return report


# ---------------------------------------------------------------------------
# Apply.
# ---------------------------------------------------------------------------
def _link_over(source: Path, target: Path) -> None:
    """Replace ``target`` with a hardlink to ``source``, atomically.

    Creates the link under a temp name in the same directory, then renames it over the
    target. The target therefore always exists — a crash cannot leave a hole in the
    environment. Raises on failure, having cleaned up the temp file.
    """
    tmp = target.with_name(target.name + ".venvy-dedup-tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    os.link(str(source), str(tmp))
    try:
        os.replace(str(tmp), str(target))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def apply_dedup(report: DedupReport, min_size: int = DEFAULT_MIN_SIZE) -> DedupReport:
    """Collapse each duplicate group onto a single inode via hardlinks.

    Re-verifies size, device and content hash immediately before every link so a file
    changed since the scan is skipped rather than clobbered.
    """
    import time

    start = time.time()
    linked = 0
    reclaimed = 0

    for group in report.groups:
        paths = [Path(p) for p in group.paths]
        # Canonical copy: first path in sorted order that still matches the group.
        canonical: Optional[Path] = None
        canonical_st = None
        for path in paths:
            try:
                st = path.lstat()
            except OSError:
                continue
            if st.st_size != group.size or os.path.islink(str(path)):
                continue
            if _hash_file(path) != group.digest:
                continue
            canonical, canonical_st = path, st
            break
        if canonical is None or canonical_st is None:
            report.errors.append("no verifiable source for group %s" % group.digest[:12])
            continue

        for path in paths:
            if path == canonical:
                continue
            try:
                st = path.lstat()
            except OSError:
                continue
            # Already the same inode -> nothing to do.
            if st.st_dev == canonical_st.st_dev and st.st_ino == canonical_st.st_ino:
                continue
            # Re-verify everything at apply time (closes the TOCTOU window).
            if st.st_dev != canonical_st.st_dev:
                continue                      # cannot hardlink across filesystems
            if os.path.islink(str(path)):
                continue
            # Size or content differing from the scan means the file was rewritten in
            # the meantime. Skip it and say so — never clobber a file we can't verify.
            if st.st_size != group.size or _hash_file(path) != group.digest:
                report.errors.append(
                    "changed since scan (or its RECORD hash was wrong), "
                    "skipped: %s" % path)
                continue
            try:
                _link_over(canonical, path)
                linked += 1
                reclaimed += group.size
            except OSError as exc:
                report.errors.append("could not link %s: %s" % (path, exc))

    report.applied = True
    report.linked_files = linked
    report.reclaimed_bytes = reclaimed
    report.duration_ms += int((time.time() - start) * 1000)
    return report


# ---------------------------------------------------------------------------
# Environment enumeration (mirrors the audit path: registry, or explicit paths).
# ---------------------------------------------------------------------------
def enumerate_environments(explicit: Optional[Sequence[Path]] = None) -> Tuple[List[Path], List[str]]:
    if explicit:
        return [Path(p) for p in explicit], []
    errors: List[str] = []
    try:
        from venvy.registry import VenvRegistry
        records = VenvRegistry().list_all()
    except Exception as exc:
        return [], ["registry unavailable: %s" % exc]
    envs = [Path(r.path) for r in records if not getattr(r, "missing", 0)]
    return envs, errors
