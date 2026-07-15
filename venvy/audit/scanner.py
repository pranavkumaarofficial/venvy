"""
scanner.py — orchestration + the speed layer for ``venvy audit``.

Ties together inventory (installed packages) and db (advisories) into per-environment
findings. Two deliberate performance moves:

  * **Deduplicated lookups.** Many environments contain the identical ``name==version``
    (every ML env drags the same ``numpy``/``torch``). We collapse to the *unique* set
    of (name, version), do each DB query once per unique name and each match once per
    unique (name, version), then fan the results back out to every env. This is the
    single biggest win for the vibecoder graveyard.
  * **Parallel env walking.** Reading dist-info is filesystem I/O (releases the GIL), so
    inventories are read in a thread pool. Matching stays single-threaded for
    determinism — no ordering nondeterminism in the security verdict.

Only AFFECTED and UNKNOWN produce findings; NOT_AFFECTED is silent. UNKNOWN is always
surfaced (invariant #5) — it is never conflated with clean.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from venvy.audit.db import AdvisoryDB, default_db_path
from venvy.audit.inventory import EnvInventory, read_env_inventory
from venvy.audit.matcher import MatchStatus, fixed_versions, version_status

# Ordering: malicious is the loudest, then vulnerabilities, then unresolved unknowns.
_KIND_RANK = {"malicious": 0, "vulnerability": 1, "unknown": 2}

# Packaging toolchain: present in nearly every venv, carries many advisories, and is the
# installer rather than an app dependency. Reported, but in a separate section so it does
# not bury real dependency findings and does not inflate the headline count.
_TOOLCHAIN = frozenset({"pip", "setuptools", "wheel"})


# ---------------------------------------------------------------------------
# Result model (the scan output contract; P4 renders these to JSON/human).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    package: str                    # canonical name
    version: str
    raw_name: str
    advisory_id: str
    kind: str                       # "malicious" | "vulnerability"
    status: str                     # "affected" | "unknown"
    severity: str
    summary: str
    aliases: Tuple[str, ...]
    fixed_versions: Tuple[str, ...]
    toolchain: bool = False

    def sort_key(self):
        rank = _KIND_RANK.get("unknown" if self.status == "unknown" else self.kind, 3)
        # Toolchain findings sink below app-dependency findings of the same class.
        return (int(self.toolchain), rank, self.package, self.version, self.advisory_id)


@dataclass(frozen=True)
class EnvResult:
    path: str
    name: Optional[str]
    python_version: Optional[str]
    registered: bool
    package_count: int
    findings: Tuple[Finding, ...]
    errors: Tuple[str, ...]

    @property
    def affected(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status == "affected")

    @property
    def unknown(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status == "unknown")


@dataclass(frozen=True)
class ScanStats:
    envs_scanned: int = 0
    packages_scanned: int = 0        # total installed across all envs (with dups)
    unique_packages: int = 0         # distinct (name, version)
    vulnerable_findings: int = 0     # affected vulnerability findings (env x advisory)
    malicious_findings: int = 0      # affected malicious findings
    unknown_findings: int = 0
    affected_packages: int = 0       # HEADLINE: distinct (env, app-package) affected
    toolchain_affected_packages: int = 0  # distinct (env, toolchain-package) affected
    duration_ms: int = 0


@dataclass(frozen=True)
class ScanResult:
    environments: Tuple[EnvResult, ...]
    db_meta: dict
    stats: ScanStats
    errors: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_malicious(self) -> bool:
        return self.stats.malicious_findings > 0

    @property
    def has_vulnerable(self) -> bool:
        return self.stats.vulnerable_findings > 0

    @property
    def has_unknown(self) -> bool:
        return self.stats.unknown_findings > 0


# ---------------------------------------------------------------------------
# Environment enumeration.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _EnvInput:
    path: Path
    name: Optional[str]
    registered: bool


def _enumerate_from_registry() -> Tuple[List[_EnvInput], List[str]]:
    """Pull environments from the venvy registry (the machine-wide moat)."""
    errors: List[str] = []
    try:
        from venvy.registry import VenvRegistry  # lazy, matches project pattern
        registry = VenvRegistry()
        records = registry.list_all()
    except Exception as exc:
        return [], ["registry unavailable: %s" % exc]

    envs: List[_EnvInput] = []
    for rec in records:
        if getattr(rec, "missing", 0):
            continue  # skip envs the registry knows are gone
        envs.append(
            _EnvInput(
                path=Path(rec.path),
                name=getattr(rec, "name", None),
                registered=True,
            )
        )
    return envs, errors


def _enumerate_from_scan() -> Tuple[List[_EnvInput], List[str]]:
    """Best-effort discovery of unregistered envs, so 'machine-wide' stays honest."""
    try:
        from venvy.discovery import EnvironmentDiscovery
        found = EnvironmentDiscovery().discover_all()
    except Exception as exc:
        return [], ["discovery scan failed: %s" % exc]
    return [_EnvInput(path=Path(e.path), name=getattr(e, "name", None),
                      registered=False) for e in found], []


def _resolve_inputs(
    env_paths: Optional[Sequence[Path]],
    include_scan: bool,
) -> Tuple[List[_EnvInput], List[str]]:
    """Decide which environments to scan, de-duplicated by resolved path."""
    errors: List[str] = []
    if env_paths is not None:
        inputs = [_EnvInput(path=Path(p), name=None, registered=False) for p in env_paths]
    else:
        inputs, errors = _enumerate_from_registry()
        if include_scan:
            scanned, scan_errs = _enumerate_from_scan()
            inputs.extend(scanned)
            errors.extend(scan_errs)

    # De-duplicate by resolved path; keep the first (registry-preferred) descriptor.
    seen = set()
    unique: List[_EnvInput] = []
    for env in inputs:
        try:
            key = str(env.path.resolve()).lower()
        except OSError:
            key = str(env.path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(env)
    return unique, errors


# ---------------------------------------------------------------------------
# The scan.
# ---------------------------------------------------------------------------
def scan(
    env_paths: Optional[Sequence[Path]] = None,
    db: Optional[AdvisoryDB] = None,
    db_path: Optional[Path] = None,
    include_scan: bool = False,
    workers: Optional[int] = None,
) -> ScanResult:
    """Audit environments and return a structured :class:`ScanResult`.

    ``env_paths`` explicit list overrides registry enumeration (used by tests and
    ``--env``). ``db`` may be injected; otherwise one is opened from ``db_path`` (or the
    default location). The caller owns a ``db`` it injects; a ``db`` we open here is
    closed before returning.
    """
    import time

    start = time.time()
    inputs, global_errors = _resolve_inputs(env_paths, include_scan)

    owns_db = db is None
    if db is None:
        db = AdvisoryDB(db_path or default_db_path())
    try:
        return _run(db, inputs, global_errors, workers, start)
    finally:
        if owns_db:
            db.close()


def _run(db, inputs, global_errors, workers, start):
    import time

    # 1) Read inventories in parallel (filesystem I/O bound).
    inventories: List[Tuple[_EnvInput, EnvInventory]] = []
    if inputs:
        n_workers = workers or min(8, len(inputs))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            invs = list(pool.map(lambda e: read_env_inventory(e.path, e.name, e.registered), inputs))
        inventories = list(zip(inputs, invs))

    # 2) Collapse to unique (name, version) across ALL envs — the dedup win.
    unique_keys = set()
    unique_names = set()
    for _, inv in inventories:
        for pkg in inv.packages:
            unique_keys.add((pkg.name, pkg.version))
            unique_names.add(pkg.name)

    # 3) One DB query per unique name; one match per unique (name, version).
    advisories_by_name = {name: db.advisories_for(name) for name in unique_names}
    findings_by_key: Dict[Tuple[str, str], List[Finding]] = {}
    for name, version in unique_keys:
        bucket: List[Finding] = []
        for adv in advisories_by_name.get(name, ()):
            status = version_status(version, adv.affected)
            if status == MatchStatus.NOT_AFFECTED:
                continue
            bucket.append(
                Finding(
                    package=name,
                    version=version,
                    raw_name=name,  # replaced per-env below with the display name
                    advisory_id=adv.id,
                    kind=adv.kind,
                    status="affected" if status == MatchStatus.AFFECTED else "unknown",
                    severity=adv.severity,
                    summary=adv.summary,
                    aliases=adv.aliases,
                    fixed_versions=fixed_versions(adv.affected),
                    toolchain=name in _TOOLCHAIN,
                )
            )
        findings_by_key[(name, version)] = bucket

    # 4) Fan findings back out to each env, tallying stats.
    env_results: List[EnvResult] = []
    total_packages = 0
    vuln = mal = unknown = 0
    app_pairs = set()
    toolchain_pairs = set()

    for env_input, inv in inventories:
        total_packages += len(inv.packages)
        env_findings: List[Finding] = []
        for pkg in inv.packages:
            for base in findings_by_key.get((pkg.name, pkg.version), ()):
                # Attach this env's display name for the package.
                f = Finding(
                    package=base.package, version=base.version, raw_name=pkg.raw_name,
                    advisory_id=base.advisory_id, kind=base.kind, status=base.status,
                    severity=base.severity, summary=base.summary, aliases=base.aliases,
                    fixed_versions=base.fixed_versions, toolchain=base.toolchain,
                )
                env_findings.append(f)
                if f.status == "unknown":
                    unknown += 1
                    continue
                if f.kind == "malicious":
                    mal += 1
                else:
                    vuln += 1
                # Headline counts app packages; toolchain is tallied separately.
                if f.toolchain:
                    toolchain_pairs.add((inv.path, pkg.name))
                else:
                    app_pairs.add((inv.path, pkg.name))

        env_findings.sort(key=lambda f: f.sort_key())
        env_results.append(
            EnvResult(
                path=inv.path,
                name=inv.name,
                python_version=inv.python_version,
                registered=env_input.registered,
                package_count=len(inv.packages),
                findings=tuple(env_findings),
                errors=inv.errors,
            )
        )

    env_results.sort(key=lambda e: e.path.lower())

    stats = ScanStats(
        envs_scanned=len(env_results),
        packages_scanned=total_packages,
        unique_packages=len(unique_keys),
        vulnerable_findings=vuln,
        malicious_findings=mal,
        unknown_findings=unknown,
        affected_packages=len(app_pairs),
        toolchain_affected_packages=len(toolchain_pairs),
        duration_ms=int((time.time() - start) * 1000),
    )
    db_meta = _db_meta(db)
    return ScanResult(
        environments=tuple(env_results),
        db_meta=db_meta,
        stats=stats,
        errors=tuple(global_errors),
    )


def _db_meta(db: AdvisoryDB) -> dict:
    age = db.age_days()
    return {
        "built_at": db.meta.get("built_at"),
        "age_days": round(age, 3) if age is not None else None,
        "stale": db.is_stale(),
        "advisory_count": db.meta.get("advisory_count"),
        "malicious_count": db.meta.get("malicious_count"),
        "source_url": db.meta.get("source_url"),
        "source_sha256": db.meta.get("source_sha256"),
    }
