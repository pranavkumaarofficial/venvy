"""
db.py — the local advisory snapshot for ``venvy audit``.

Ground truth lives in a prebuilt SQLite index compiled from the OSV PyPI dump. The scan
path only ever *reads* this file (no network, invariant #3); the network is touched only
by :func:`refresh_database`.

Design points:
  * The compile step is decoupled from downloading/zip handling so it is unit-testable
    offline: :func:`compile_database` takes an iterable of raw OSV record dicts.
  * Refresh is atomic: build into a temp file, fsync, then ``os.replace`` over the live
    DB. A crash mid-refresh never leaves a half-built database that could read as "clean".
  * Provenance (source URL, content hash, fetch time, counts) is recorded in ``meta`` so
    a user can audit exactly what their results are based on.
  * Withdrawn advisories are recorded but NOT indexed for matching — a retracted advisory
    must not produce findings.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple
from urllib.request import Request, urlopen

from venvy.audit.matcher import AffectedPackage, AffectedRange, RangeEvent, parse_osv_affected
from venvy.utils import get_venvy_data_dir

SCHEMA_VERSION = 1
DEFAULT_OSV_URL = "https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip"
DEFAULT_STALE_DAYS = 14

# Defensive caps for the refresh path (zip-bomb / hostile-input guards).
_MAX_ZIP_ENTRY_BYTES = 8 * 1024 * 1024      # a single advisory JSON is a few KB
_MAX_TOTAL_UNCOMPRESSED = 512 * 1024 * 1024  # whole dump is well under this
_DOWNLOAD_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Public data shapes.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AdvisoryMatch:
    """One advisory relevant to a queried package, with its affected definition."""

    id: str
    kind: str          # "vulnerability" | "malicious"
    summary: str
    severity: str
    aliases: Tuple[str, ...]
    affected: AffectedPackage


@dataclass
class BuildReport:
    path: str
    schema_version: int
    records_total: int = 0
    advisories: int = 0
    affected_rows: int = 0
    malicious: int = 0
    withdrawn: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    source_url: Optional[str] = None
    source_sha256: Optional[str] = None
    source_bytes: int = 0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Classification / extraction helpers.
# ---------------------------------------------------------------------------
def _classify(record: dict) -> str:
    """vulnerability vs malicious. MAL- id prefix is the OpenSSF convention."""
    rid = str(record.get("id", "")).upper()
    if rid.startswith("MAL-"):
        return "malicious"
    ds = record.get("database_specific") or {}
    if ds.get("malicious") is True:
        return "malicious"
    return "vulnerability"


def _severity(record: dict) -> str:
    """Best-effort human severity label. Display-only; never gates correctness."""
    ds = record.get("database_specific") or {}
    label = ds.get("severity")
    if isinstance(label, str) and label.strip():
        return label.strip().upper()
    sev = record.get("severity")
    if isinstance(sev, list) and sev and isinstance(sev[0], dict):
        return str(sev[0].get("score") or sev[0].get("type") or "UNKNOWN")
    return "UNKNOWN"


def _dump_ranges(ap: AffectedPackage) -> str:
    return json.dumps(
        [[{"kind": e.kind, "value": e.value} for e in rng.events] for rng in ap.ranges]
    )


def _load_ranges(blob: str) -> Tuple[AffectedRange, ...]:
    raw = json.loads(blob)
    return tuple(
        AffectedRange(events=tuple(RangeEvent(e["kind"], e["value"]) for e in rng))
        for rng in raw
    )


# ---------------------------------------------------------------------------
# Compile: raw OSV records -> SQLite index.
# ---------------------------------------------------------------------------
def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE advisories (
            id        TEXT PRIMARY KEY,
            kind      TEXT NOT NULL,
            summary   TEXT,
            severity  TEXT,
            aliases   TEXT,
            withdrawn INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE affected (
            advisory_id  TEXT NOT NULL,
            package_norm TEXT NOT NULL,
            ranges_json  TEXT NOT NULL,
            versions_json TEXT NOT NULL,
            unscoped     INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )


def compile_database(
    dest_path: Path,
    records: Iterable[dict],
    source_meta: Optional[dict] = None,
) -> BuildReport:
    """Compile raw OSV record dicts into an atomic SQLite snapshot at ``dest_path``.

    Never raises on a bad individual record — malformed entries are counted in
    ``report.skipped`` and skipped, so one broken advisory can't abort the whole build.
    """
    start = _now()
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    report = BuildReport(path=str(dest_path), schema_version=SCHEMA_VERSION)
    if source_meta:
        report.source_url = source_meta.get("source_url")
        report.source_sha256 = source_meta.get("source_sha256")
        report.source_bytes = source_meta.get("source_bytes", 0)

    fd, tmp_name = tempfile.mkstemp(
        prefix=dest_path.name + ".tmp-", dir=str(dest_path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    conn = sqlite3.connect(str(tmp_path))
    try:
        _create_schema(conn)
        cur = conn.cursor()
        for record in records:
            report.records_total += 1
            try:
                rid = record.get("id")
                if not rid:
                    report.skipped += 1
                    continue
                kind = _classify(record)
                withdrawn = 1 if record.get("withdrawn") else 0
                cur.execute(
                    "INSERT OR REPLACE INTO advisories "
                    "(id, kind, summary, severity, aliases, withdrawn) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        str(rid),
                        kind,
                        record.get("summary") or record.get("details") or "",
                        _severity(record),
                        json.dumps(list(record.get("aliases") or [])),
                        withdrawn,
                    ),
                )
                report.advisories += 1
                if withdrawn:
                    # Recorded for transparency, but never indexed -> never matches.
                    continue

                for aff in record.get("affected") or []:
                    pkgobj = aff.get("package") or {}
                    eco = pkgobj.get("ecosystem")
                    if eco not in (None, "PyPI"):
                        continue  # PyPI dump, but guard against mixed-ecosystem records
                    ap = parse_osv_affected(aff)
                    if not ap.name:
                        continue
                    cur.execute(
                        "INSERT INTO affected "
                        "(advisory_id, package_norm, ranges_json, versions_json, unscoped) "
                        "VALUES (?,?,?,?,?)",
                        (
                            str(rid),
                            ap.name,
                            _dump_ranges(ap),
                            json.dumps(list(ap.versions)),
                            1 if ap.unscoped else 0,
                        ),
                    )
                    report.affected_rows += 1
                    if kind == "malicious":
                        report.malicious += 1
            except Exception as exc:  # one bad record must not sink the build
                report.skipped += 1
                if len(report.errors) < 50:
                    report.errors.append("record %r: %s" % (record.get("id"), exc))

        cur.execute("CREATE INDEX idx_affected_pkg ON affected(package_norm)")

        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "built_at": _now().isoformat(),
            "advisory_count": str(report.advisories),
            "affected_count": str(report.affected_rows),
            "malicious_count": str(report.malicious),
            "source_url": report.source_url or "",
            "source_sha256": report.source_sha256 or "",
            "source_bytes": str(report.source_bytes),
        }
        if source_meta and source_meta.get("sources"):
            meta["sources"] = json.dumps(source_meta["sources"])
        cur.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", list(meta.items())
        )
        conn.commit()
    finally:
        conn.close()

    # Atomic publish: fsync the temp file, then replace the live DB in one step.
    _fsync_file(tmp_path)
    os.replace(str(tmp_path), str(dest_path))

    report.duration_seconds = (_now() - start).total_seconds()
    return report


# ---------------------------------------------------------------------------
# Download + refresh (the ONLY network path).
# ---------------------------------------------------------------------------
def download_osv_zip(url: str, dest: Path) -> Tuple[str, int]:
    """Download ``url`` to ``dest`` over HTTPS. Returns (sha256_hex, byte_count)."""
    if not url.lower().startswith("https://"):
        raise ValueError("refusing non-HTTPS advisory source: %s" % url)
    req = Request(url, headers={"User-Agent": "venvy-audit"})
    hasher = hashlib.sha256()
    total = 0
    with urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            hasher.update(chunk)
            total += len(chunk)
            out.write(chunk)
    return hasher.hexdigest(), total


def iter_osv_from_zip(zip_path: Path) -> Iterator[dict]:
    """Yield parsed OSV record dicts from an all.zip, skipping unreadable entries.

    Size-capped per entry and in aggregate (zip-bomb guard). Bad JSON is skipped, not
    fatal — the compile step counts skips.
    """
    total_uncompressed = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".json"):
                continue
            if info.file_size > _MAX_ZIP_ENTRY_BYTES:
                continue
            total_uncompressed += info.file_size
            if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("OSV archive exceeds size cap; refusing to continue")
            try:
                with zf.open(info) as fh:
                    yield json.loads(fh.read())
            except (json.JSONDecodeError, OSError, zipfile.BadZipFile):
                continue


def refresh_database(
    dest_path: Optional[Path] = None,
    url: str = DEFAULT_OSV_URL,
    include_enrichment: bool = True,
) -> BuildReport:
    """Rebuild the local snapshot atomically from OSV plus enrichment feeds.

    OSV is required. The DataDog malicious dataset and the typosquat dataset are
    best-effort: if either is unreachable, the build proceeds without it and records the
    failure in the ``sources`` provenance, rather than failing the whole refresh.
    """
    import itertools

    dest_path = Path(dest_path) if dest_path else default_db_path()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    now = _now().isoformat()

    with tempfile.TemporaryDirectory(prefix="venvy-osv-") as tmpdir:
        zip_path = Path(tmpdir) / "all.zip"
        osv_sha, nbytes = download_osv_zip(url, zip_path)

        record_streams = [iter_osv_from_zip(zip_path)]
        sources = [{"name": "osv-pypi", "url": url, "sha256": osv_sha,
                    "bytes": nbytes, "fetched_at": now}]

        if include_enrichment:
            from venvy.audit import sources as src

            try:
                manifest, dd_sha = src.fetch_datadog()
                record_streams.append(src.datadog_to_osv(manifest))
                sources.append({"name": "datadog-malicious", "url": src.DEFAULT_DATADOG_URL,
                                "sha256": dd_sha, "fetched_at": now})
            except Exception as exc:  # best-effort enrichment
                sources.append({"name": "datadog-malicious", "error": str(exc)})

            try:
                csv_text, ts_sha = src.fetch_typosquats()
                record_streams.append(src.typosquats_to_osv(csv_text))
                sources.append({"name": "typosquat", "url": src.DEFAULT_TYPOSQUAT_URL,
                                "sha256": ts_sha, "fetched_at": now})
            except Exception as exc:
                sources.append({"name": "typosquat", "error": str(exc)})

        source_meta = {
            "source_url": url,
            "source_sha256": osv_sha,
            "source_bytes": nbytes,
            "sources": sources,
        }
        return compile_database(
            dest_path, itertools.chain(*record_streams), source_meta=source_meta
        )


# ---------------------------------------------------------------------------
# Query API (scan path — read-only, no network).
# ---------------------------------------------------------------------------
def default_db_path() -> Path:
    return get_venvy_data_dir() / "audit" / "osv-pypi.sqlite"


class AdvisoryDB:
    """Read-only accessor over a compiled snapshot. Cheap to open; call ``close``."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_db_path()
        if not self.path.exists():
            raise FileNotFoundError(
                "advisory database not found at %s — run `venvy audit --refresh`"
                % self.path
            )
        # Read-only URI connection so a scan can never mutate ground truth.
        # Path.as_uri() yields the platform-correct form (file:///C:/... on Windows,
        # with proper percent-encoding); a hand-built "file:%s" breaks on drive letters
        # and spaces.
        uri = self.path.resolve().as_uri() + "?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row
        self._meta_cache: Optional[dict] = None

    # -- metadata / staleness -------------------------------------------------
    @property
    def meta(self) -> dict:
        if self._meta_cache is None:
            rows = self._conn.execute("SELECT key, value FROM meta").fetchall()
            self._meta_cache = {r["key"]: r["value"] for r in rows}
        return self._meta_cache

    def built_at(self) -> Optional[datetime]:
        raw = self.meta.get("built_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def age_days(self) -> Optional[float]:
        built = self.built_at()
        if built is None:
            return None
        if built.tzinfo is None:
            built = built.replace(tzinfo=timezone.utc)
        return (_now() - built).total_seconds() / 86400.0

    def is_stale(self, threshold_days: int = DEFAULT_STALE_DAYS) -> bool:
        age = self.age_days()
        return age is None or age > threshold_days

    def advisory_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM advisories").fetchone()[0]

    def affected_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM affected").fetchone()[0]

    # -- lookups --------------------------------------------------------------
    def advisories_for(self, package_norm: str) -> List[AdvisoryMatch]:
        """Return all advisories whose affected set names ``package_norm`` (canonical)."""
        rows = self._conn.execute(
            """
            SELECT a.id AS id, a.kind AS kind, a.summary AS summary,
                   a.severity AS severity, a.aliases AS aliases,
                   f.ranges_json AS ranges_json, f.versions_json AS versions_json,
                   f.unscoped AS unscoped
            FROM affected f JOIN advisories a ON a.id = f.advisory_id
            WHERE f.package_norm = ?
            """,
            (package_norm,),
        ).fetchall()

        matches: List[AdvisoryMatch] = []
        for r in rows:
            affected = AffectedPackage(
                name=package_norm,
                ranges=_load_ranges(r["ranges_json"]),
                versions=tuple(json.loads(r["versions_json"])),
                unscoped=bool(r["unscoped"]),
            )
            try:
                aliases = tuple(json.loads(r["aliases"] or "[]"))
            except json.JSONDecodeError:
                aliases = ()
            matches.append(
                AdvisoryMatch(
                    id=r["id"],
                    kind=r["kind"],
                    summary=r["summary"] or "",
                    severity=r["severity"] or "UNKNOWN",
                    aliases=aliases,
                    affected=affected,
                )
            )
        return matches

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AdvisoryDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Small internals kept at the bottom so patching in tests is straightforward.
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fsync_file(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # fsync is best-effort durability, not correctness
