"""
inventory.py — enumerate installed packages in an environment, safely and fast.

Hard rules (invariants #2, #3, #5):
  * NEVER import a scanned package and NEVER shell out to its ``pip``. We read the
    ``*.dist-info`` / ``*.egg-info`` metadata as text only. A scanner that imports a
    package to inspect it *is* the vulnerability.
  * Fast path: the ``*.dist-info`` directory name is ``{name}-{version}.dist-info``
    (PEP 427/503), so name+version come from ``os.scandir`` with zero file opens. We
    fall back to reading ``METADATA`` / ``PKG-INFO`` only when the directory name is
    ambiguous or the version doesn't parse.
  * Failures are surfaced per-env in ``errors``, never swallowed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from packaging.version import InvalidVersion, Version

from venvy.audit.matcher import canonicalize_name

# Cap on metadata file reads — defensive against pathological/hostile files.
_MAX_METADATA_BYTES = 256 * 1024


@dataclass(frozen=True)
class InstalledPackage:
    name: str          # canonical PEP 503 name (matches advisory names)
    version: str       # as recorded (validated parseable where possible)
    raw_name: str      # name as declared in metadata / dir name, for display
    source: str        # path to the .dist-info / .egg-info dir (provenance)
    installed_at: Optional[str] = None  # local ISO date this package landed on disk


@dataclass(frozen=True)
class EnvInventory:
    path: str
    name: Optional[str]
    python_version: Optional[str]
    registered: bool
    packages: Tuple[InstalledPackage, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Locating site-packages (platform-aware).
# ---------------------------------------------------------------------------
def find_site_packages(env_path: Path) -> List[Path]:
    """Return existing site-packages directories for a venv/virtualenv root.

    Handles Windows (``Lib\\site-packages``) and POSIX
    (``lib/pythonX.Y/site-packages``) layouts. Returns every match found; an empty
    list means "no site-packages here" (the caller records that as an error).
    """
    found: List[Path] = []

    # Windows layout.
    win = env_path / "Lib" / "site-packages"
    if win.is_dir():
        found.append(win)

    # POSIX layout: lib/python*/site-packages (there is normally exactly one).
    lib = env_path / "lib"
    if lib.is_dir():
        try:
            for child in sorted(lib.iterdir()):
                sp = child / "site-packages"
                if sp.is_dir():
                    found.append(sp)
        except OSError:
            pass

    # Some layouts (e.g. certain Debian/virtualenv) also use lib64.
    lib64 = env_path / "lib64"
    if lib64.is_dir() and not lib64.is_symlink():
        try:
            for child in sorted(lib64.iterdir()):
                sp = child / "site-packages"
                if sp.is_dir() and sp not in found:
                    found.append(sp)
        except OSError:
            pass

    return found


def read_python_version(env_path: Path) -> Optional[str]:
    """Read the interpreter version from ``pyvenv.cfg`` if present (text-only)."""
    cfg = env_path / "pyvenv.cfg"
    try:
        with cfg.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip().lower() == "version":
                    return value.strip()
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------
# Reading a single metadata directory.
# ---------------------------------------------------------------------------
def _read_metadata_fields(meta_file: Path) -> Tuple[Optional[str], Optional[str]]:
    """Extract (Name, Version) from a METADATA / PKG-INFO file. Text-only, size-capped."""
    name: Optional[str] = None
    version: Optional[str] = None
    try:
        with meta_file.open("r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(_MAX_METADATA_BYTES)
    except OSError:
        return None, None
    for line in data.splitlines():
        # Metadata headers end at the first blank line (body follows).
        if not line.strip():
            break
        low = line.lower()
        if name is None and low.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif version is None and low.startswith("version:"):
            version = line.split(":", 1)[1].strip()
        if name and version:
            break
    return name, version


def _parse_dist_info_dirname(stem: str) -> Optional[Tuple[str, str]]:
    """Parse ``{name}-{version}`` from a ``.dist-info`` stem.

    The name portion never contains ``-`` (it is escaped to ``_`` per the wheel spec),
    so the first ``-`` is the delimiter. Returns (raw_name, version) only when the
    version parses as PEP 440; otherwise None to force the METADATA fallback.
    """
    if "-" not in stem:
        return None
    raw_name, version = stem.split("-", 1)
    if not raw_name or not version:
        return None
    try:
        Version(version)
    except InvalidVersion:
        return None
    return raw_name, version


def _package_from_dir(entry_path: Path) -> Optional[InstalledPackage]:
    """Build an InstalledPackage from a ``.dist-info`` or ``.egg-info`` directory.

    Returns None if neither the directory name nor the metadata yield a usable
    (name, version). Raises nothing — I/O errors degrade to None and are handled above.
    """
    dirname = entry_path.name
    raw_name: Optional[str] = None
    version: Optional[str] = None

    if dirname.endswith(".dist-info"):
        stem = dirname[: -len(".dist-info")]
        parsed = _parse_dist_info_dirname(stem)
        if parsed is not None:
            raw_name, version = parsed

    # Fallback / egg-info: read the metadata file directly.
    if raw_name is None or version is None:
        meta_name = "METADATA" if dirname.endswith(".dist-info") else "PKG-INFO"
        m_name, m_version = _read_metadata_fields(entry_path / meta_name)
        raw_name = raw_name or m_name
        version = version or m_version

    if not raw_name or not version:
        return None

    return InstalledPackage(
        name=canonicalize_name(raw_name),
        version=version,
        raw_name=raw_name,
        source=str(entry_path),
        installed_at=_dir_install_date(entry_path),
    )


def _dir_install_date(entry_path: Path) -> Optional[str]:
    """Best-effort install date from the ``.dist-info`` directory mtime (local date).

    pip writes the metadata directory at install time, so its mtime approximates when
    the package landed. Crude, but it turns a finding from "uninstall it" into "this
    arrived on <date> — scope what was exposed." Never raises; returns None on failure.
    """
    try:
        mtime = entry_path.stat().st_mtime
    except OSError:
        return None
    try:
        return datetime.fromtimestamp(mtime).astimezone().date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _read_packages_from_site(site_packages: Path) -> Tuple[List[InstalledPackage], List[str]]:
    """Scan one site-packages dir. Returns (packages, errors)."""
    packages: List[InstalledPackage] = []
    errors: List[str] = []
    try:
        entries = list(os.scandir(site_packages))
    except OSError as exc:
        return packages, ["cannot read %s: %s" % (site_packages, exc)]

    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if not (entry.name.endswith(".dist-info") or entry.name.endswith(".egg-info")):
            continue
        try:
            pkg = _package_from_dir(Path(entry.path))
        except OSError as exc:
            errors.append("cannot read %s: %s" % (entry.name, exc))
            continue
        if pkg is None:
            errors.append("unrecognized metadata in %s" % entry.name)
        else:
            packages.append(pkg)
    return packages, errors


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
def read_env_inventory(
    env_path: Path,
    name: Optional[str] = None,
    registered: bool = False,
) -> EnvInventory:
    """Read the full package inventory of one environment. Never raises.

    An unreadable / non-existent / empty environment yields an EnvInventory with an
    ``errors`` entry and no packages — the caller decides how to surface it, but it is
    never confused with "clean".
    """
    env_path = Path(env_path)
    python_version = read_python_version(env_path)

    if not env_path.exists():
        return EnvInventory(
            path=str(env_path), name=name, python_version=python_version,
            registered=registered, errors=("environment path does not exist",),
        )

    site_dirs = find_site_packages(env_path)
    if not site_dirs:
        return EnvInventory(
            path=str(env_path), name=name, python_version=python_version,
            registered=registered, errors=("no site-packages directory found",),
        )

    all_packages: List[InstalledPackage] = []
    all_errors: List[str] = []
    seen: set = set()  # dedup (name, version) within an env (e.g. lib + lib64)
    for sp in site_dirs:
        pkgs, errs = _read_packages_from_site(sp)
        for pkg in pkgs:
            key = (pkg.name, pkg.version)
            if key not in seen:
                seen.add(key)
                all_packages.append(pkg)
        all_errors.extend(errs)

    # Deterministic ordering, independent of filesystem iteration order.
    all_packages.sort(key=lambda p: (p.name, p.version))

    return EnvInventory(
        path=str(env_path),
        name=name,
        python_version=python_version,
        registered=registered,
        packages=tuple(all_packages),
        errors=tuple(all_errors),
    )
