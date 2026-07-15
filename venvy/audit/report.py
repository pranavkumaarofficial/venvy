"""
report.py — turn a ScanResult into an exit code, JSON, and human output.

Exit-code policy (documented because CI and agents parse it):
  * Precedence: MALICIOUS(21) > VULNERABLE(20) > STALE_OR_PARTIAL(22) > CLEAN(0).
  * By default the gate is driven by APPLICATION dependencies. Toolchain packages
    (pip/setuptools/wheel) are always REPORTED but do not fail the build on their own —
    otherwise nearly every machine would exit non-zero because of an old bundled pip,
    and the signal would be worthless. Pass ``include_toolchain=True`` to gate on them too.
  * Nothing is ever hidden: toolchain and unknown findings always appear in the output
    and JSON regardless of whether they affect the exit code.
"""
from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional, Tuple

from venvy.exit_codes import ExitCode

SCHEMA_VERSION = 1

_QUALITATIVE = {"NONE", "LOW", "MEDIUM", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"}


# ---------------------------------------------------------------------------
# Severity display: turn a raw OSV severity (a qualitative word OR a CVSS vector)
# into a short label. Display-only; never affects a verdict.
# ---------------------------------------------------------------------------
def _cvss3_base(vector: str) -> Optional[float]:
    """Compute a CVSS v3.x base score from its vector string, or None if not v3."""
    try:
        parts = dict(p.split(":", 1) for p in vector.split("/") if ":" in p)
    except ValueError:
        return None
    if not parts.get("CVSS", "").startswith("3"):
        return None
    try:
        av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[parts["AV"]]
        ac = {"L": 0.77, "H": 0.44}[parts["AC"]]
        ui = {"N": 0.85, "R": 0.62}[parts["UI"]]
        scope = parts["S"]
        if scope == "U":
            pr = {"N": 0.85, "L": 0.62, "H": 0.27}[parts["PR"]]
        else:
            pr = {"N": 0.85, "L": 0.68, "H": 0.5}[parts["PR"]]
        cia = {"H": 0.56, "L": 0.22, "N": 0.0}
        c, i, a = cia[parts["C"]], cia[parts["I"]], cia[parts["A"]]
    except KeyError:
        return None
    iss = 1 - ((1 - c) * (1 - i) * (1 - a))
    impact = 6.42 * iss if scope == "U" else 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    expl = 8.22 * av * ac * pr * ui
    if impact <= 0:
        return 0.0
    base = (impact + expl) if scope == "U" else 1.08 * (impact + expl)
    return math.ceil(min(base, 10) * 10) / 10.0


def _score_label(score: float) -> str:
    if score <= 0:
        return "NONE"
    if score < 4:
        return "LOW"
    if score < 7:
        return "MEDIUM"
    if score < 9:
        return "HIGH"
    return "CRITICAL"


def severity_label(raw: str) -> str:
    """Short severity label from a qualitative word or CVSS vector."""
    if not raw:
        return "UNKNOWN"
    up = raw.strip().upper()
    if up in _QUALITATIVE:
        return up
    if up.startswith("CVSS:"):
        score = _cvss3_base(raw)
        if score is not None:
            return _score_label(score)
        return "CVSS"
    return raw[:12]


# ---------------------------------------------------------------------------
# Exit code.
# ---------------------------------------------------------------------------
def _presence(result, include_toolchain: bool) -> Tuple[bool, bool, bool]:
    """Return (has_malicious, has_vulnerable, has_unknown) for the gating scope."""
    mal = vuln = unknown = False
    for env in result.environments:
        for f in env.findings:
            if f.toolchain and not include_toolchain:
                continue
            if f.status == "unknown":
                unknown = True
            elif f.kind == "malicious":
                mal = True
            else:
                vuln = True
    return mal, vuln, unknown


def decide_exit_code(result, include_toolchain: bool = False) -> int:
    mal, vuln, unknown = _presence(result, include_toolchain)
    if mal:
        return ExitCode.AUDIT_MALICIOUS
    if vuln:
        return ExitCode.AUDIT_VULNERABLE
    if result.db_meta.get("stale") or unknown:
        return ExitCode.AUDIT_STALE_OR_PARTIAL
    return ExitCode.SUCCESS


# ---------------------------------------------------------------------------
# JSON.
# ---------------------------------------------------------------------------
def build_json(result, exit_code: int) -> dict:
    """Versioned, stable JSON. Additive changes only within a schema_version."""
    return {
        "schema_version": SCHEMA_VERSION,
        "exit_code": exit_code,
        "success": exit_code == ExitCode.SUCCESS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": dict(result.db_meta),
        "summary": asdict(result.stats),
        "environments": [
            {
                "path": env.path,
                "name": env.name,
                "python_version": env.python_version,
                "registered": env.registered,
                "package_count": env.package_count,
                "findings": [_finding_json(f) for f in env.findings],
                "errors": list(env.errors),
            }
            for env in result.environments
        ],
        "errors": list(result.errors),
    }


def _finding_json(f) -> dict:
    return {
        "package": f.package,
        "version": f.version,
        "raw_name": f.raw_name,
        "advisory_id": f.advisory_id,
        "kind": f.kind,
        "status": f.status,
        "severity": f.severity,
        "summary": f.summary,
        "aliases": list(f.aliases),
        "fixed_versions": list(f.fixed_versions),
        "toolchain": f.toolchain,
    }


# ---------------------------------------------------------------------------
# Human (Rich).
# ---------------------------------------------------------------------------
def render_human(result, console, include_toolchain: bool = False) -> None:
    from rich.table import Table

    s = result.stats
    exit_code = decide_exit_code(result, include_toolchain)

    # -- headline ------------------------------------------------------------
    if exit_code == ExitCode.AUDIT_MALICIOUS:
        color, word = "bold red", "MALICIOUS PACKAGES FOUND"
    elif exit_code == ExitCode.AUDIT_VULNERABLE:
        color, word = "yellow", "vulnerabilities found"
    elif exit_code == ExitCode.AUDIT_STALE_OR_PARTIAL:
        color, word = "dim yellow", "completed with caveats"
    else:
        color, word = "green", "clean"

    tail = ""
    if s.toolchain_affected_packages:
        tail = " [dim](+%d toolchain)[/dim]" % s.toolchain_affected_packages
    console.print(
        "[%s]%s[/%s] - [bold]%d[/bold] app package(s) affected across %d env(s)%s"
        % (color, word, color, s.affected_packages, s.envs_scanned, tail)
    )
    console.print(
        "[dim]scanned %d packages (%d unique) in %dms[/dim]"
        % (s.packages_scanned, s.unique_packages, s.duration_ms)
    )

    # -- database freshness --------------------------------------------------
    age = result.db_meta.get("age_days")
    if result.db_meta.get("stale"):
        console.print(
            "[bold yellow]! advisory database is stale[/bold yellow]"
            "%s - run `venvy audit --refresh`"
            % (" (%.0f days old)" % age if age is not None else "")
        )
    elif age is not None:
        console.print("[dim]advisory database: %.1f days old[/dim]" % age)

    # -- per-env findings ----------------------------------------------------
    clean_envs = 0
    for env in result.environments:
        app = [f for f in env.findings if not f.toolchain]
        tool = [f for f in env.findings if f.toolchain]
        shown = app + (tool if include_toolchain else [])
        if not shown and not env.errors:
            clean_envs += 1
            continue

        if env.name and env.name != env.path:
            console.print("\n[bold]%s[/bold] [dim]%s[/dim]" % (env.name, env.path))
        else:
            console.print("\n[bold]%s[/bold]" % env.path)

        if shown:
            table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
            table.add_column("")
            table.add_column("package")
            table.add_column("version")
            table.add_column("advisory")
            table.add_column("severity")
            table.add_column("fix")
            for f in shown:
                if f.status == "unknown":
                    marker = "[dim]?[/dim]"
                elif f.kind == "malicious":
                    marker = "[bold red]![/bold red]"
                else:
                    marker = "[yellow]*[/yellow]"
                pkg = f.package + (" [dim](toolchain)[/dim]" if f.toolchain else "")
                fix = ", ".join(f.fixed_versions[:2]) if f.fixed_versions else "[dim]-[/dim]"
                # A malicious package's "severity" is that it's malicious; a raw CVSS
                # UNKNOWN there reads as a gap when it isn't one.
                sev = "malicious" if f.kind == "malicious" else severity_label(f.severity)
                table.add_row(marker, pkg, f.version, f.advisory_id, sev, fix)
            console.print(table)

        # Toolchain summary when not expanded.
        if tool and not include_toolchain:
            console.print(
                "  [dim]+ %d toolchain finding(s) (pip/setuptools/wheel) - "
                "--include-toolchain to show[/dim]" % len(tool)
            )

        for err in env.errors:
            console.print("  [red]error:[/red] %s" % err)

    if clean_envs:
        console.print("\n[green]%d environment(s) clean[/green]" % clean_envs)

    for err in result.errors:
        console.print("[red]error:[/red] %s" % err)
