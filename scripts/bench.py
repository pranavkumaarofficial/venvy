"""Benchmark `venvy audit` and `venvy dedup` at 10, 50 and 100 environments.

Usage:
    python scripts/bench.py --workdir <empty dir> [--sizes 10 50 100] [--runs 3] [--keep]

What it does:
  1. Downloads a fixed set of pinned wheels into <workdir>/wheelhouse (the only network
     step besides the advisory DB fetch). Pins include known-vulnerable versions so the
     audit has real findings to report.
  2. Creates max(--sizes) venvs, rotating through three profiles (web, cli, data), and
     installs each profile from the wheelhouse with --no-index.
  3. Fetches a fresh advisory DB into an isolated venvy data dir (<workdir>/appdata), so
     the user's own registry and DB are never read or written.
  4. For each N, runs `venvy audit --offline --json` over the first N envs: one warm-up,
     then --runs timed runs (median reported). Then one `venvy dedup --json` dry run.
  5. Prints a Markdown table plus machine details, and writes results.json.

Nothing is hardlinked: dedup runs read-only. The workdir is deleted at the end unless
--keep is passed (the wheelhouse is kept either way, so re-runs skip the download).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

COMMON = ["pip==23.0.1", "setuptools==65.5.0"]
PROFILES = {
    "web": [
        "flask==1.1.2", "werkzeug==1.0.1", "jinja2==2.11.2", "markupsafe==2.0.1",
        "itsdangerous==1.1.0", "click==7.1.2", "requests==2.25.1", "urllib3==1.26.4",
        "idna==2.10", "chardet==4.0.0", "certifi==2020.12.5",
    ],
    "cli": [
        "rich==13.7.1", "pygments==2.15.0", "markdown-it-py==3.0.0", "mdurl==0.1.2",
        "requests==2.31.0", "urllib3==2.0.7", "idna==3.6",
        "charset-normalizer==3.3.2", "certifi==2024.2.2",
    ],
    "data": [
        "numpy==1.26.4", "requests==2.31.0", "urllib3==2.0.7", "idna==3.6",
        "charset-normalizer==3.3.2", "certifi==2024.2.2",
    ],
}
ORDER = ["web", "cli", "web", "data"]  # 50% web, 25% cli, 25% data


def run(cmd, env=None, check=True):
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if check and proc.returncode != 0:
        sys.exit("command failed (%d): %s\n%s" % (
            proc.returncode, " ".join(cmd[:6]), proc.stderr[-2000:]))
    return proc


def site_packages(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Lib" / "site-packages"
    ver = "python%d.%d" % sys.version_info[:2]
    return venv / "lib" / ver / "site-packages"


def build_wheelhouse(wh: Path) -> None:
    pins = sorted(set(COMMON + [p for prof in PROFILES.values() for p in prof]))
    wh.mkdir(parents=True, exist_ok=True)
    print("downloading %d pinned wheels -> %s" % (len(pins), wh), flush=True)
    # One pin per call: pip refuses two versions of the same package in one command.
    for pin in pins:
        run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps",
             "--only-binary=:all:", "-d", str(wh), pin])


def build_envs(root: Path, wh: Path, count: int) -> list:
    envs = []
    for i in range(count):
        profile = ORDER[i % len(ORDER)]
        venv = root / ("env%03d-%s" % (i, profile))
        if not (venv / "pyvenv.cfg").exists():
            run([sys.executable, "-m", "venv", "--without-pip", str(venv)])
            run([sys.executable, "-m", "pip", "install", "--quiet", "--no-index",
                 "--no-deps", "--find-links", str(wh), "--target",
                 str(site_packages(venv))] + COMMON + PROFILES[profile])
        envs.append(venv)
        if (i + 1) % 10 == 0:
            print("  built %d/%d envs" % (i + 1, count), flush=True)
    return envs


def venvy(args, env):
    return [sys.executable, "-m", "venvy.cli"] + args, env


def dir_bytes(paths) -> int:
    total = 0
    for p in paths:
        for f in p.rglob("*"):
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--sizes", type=int, nargs="+", default=[10, 50, 100])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    work = a.workdir.resolve()
    wh, envroot, appdata = work / "wheelhouse", work / "envs", work / "appdata"
    appdata.mkdir(parents=True, exist_ok=True)

    # Isolate venvy's data dir: APPDATA on Windows, HOME elsewhere.
    child = dict(os.environ)
    child["APPDATA"] = str(appdata)
    if os.name != "nt":
        child["HOME"] = str(appdata)

    if not any(wh.glob("*.whl")):
        build_wheelhouse(wh)
    t0 = time.perf_counter()
    envs = build_envs(envroot, wh, max(a.sizes))
    print("built %d envs in %.0fs" % (len(envs), time.perf_counter() - t0), flush=True)

    print("fetching advisory DB into isolated data dir", flush=True)
    cmd, e = venvy(["audit", "--refresh", "--json", "--env", str(envs[0])], child)
    first = json.loads(run(cmd, env=e, check=False).stdout)
    db = first["db"]

    results = []
    for n in sorted(a.sizes):
        targets = []
        for p in envs[:n]:
            targets += ["--env", str(p)]
        cmd, e = venvy(["audit", "--offline", "--json"] + targets, child)
        run(cmd, env=e, check=False)  # warm-up
        walls, internal, last = [], [], None
        for _ in range(a.runs):
            t = time.perf_counter()
            proc = run(cmd, env=e, check=False)
            walls.append((time.perf_counter() - t) * 1000)
            last = json.loads(proc.stdout)
            internal.append(last["summary"]["duration_ms"])
        s = last["summary"]

        cmd, e = venvy(["dedup", "--json"] + targets, child)
        t = time.perf_counter()
        dd = json.loads(run(cmd, env=e, check=False).stdout)
        dedup_wall = (time.perf_counter() - t) * 1000
        size = dir_bytes(envs[:n])

        results.append({
            "envs": n,
            "packages_scanned": s["packages_scanned"],
            "unique_packages": s["unique_packages"],
            "affected_app_packages": s["affected_packages"],
            "exit_code": last["exit_code"],
            "audit_wall_ms_median": round(statistics.median(walls)),
            "audit_scan_ms_median": round(statistics.median(internal)),
            "dedup_wall_ms": round(dedup_wall),
            "dedup_files_scanned": dd["files_scanned"],
            "env_bytes": size,
            "reclaimable_bytes": dd["reclaimable_bytes"],
        })
        print("N=%d done" % n, flush=True)

    machine = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "cpu_count": os.cpu_count(),
        "runs_per_size": a.runs,
        "db_built_at": db.get("built_at"),
        "db_advisory_count": db.get("advisory_count"),
    }
    out = {"machine": machine, "results": results}
    (work / "results.json").write_text(json.dumps(out, indent=2))

    mb = lambda b: "%.0f MB" % (b / 1e6)
    print("\n| envs | packages | unique | affected app pkgs | audit wall (median) "
          "| audit scan (median) | dedup dry run | env size | reclaimable |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        print("| %d | %d | %d | %d | %d ms | %d ms | %d ms | %s | %s (%.0f%%) |" % (
            r["envs"], r["packages_scanned"], r["unique_packages"],
            r["affected_app_packages"], r["audit_wall_ms_median"],
            r["audit_scan_ms_median"], r["dedup_wall_ms"], mb(r["env_bytes"]),
            mb(r["reclaimable_bytes"]), 100 * r["reclaimable_bytes"] / r["env_bytes"]))
    print("\n" + json.dumps(machine, indent=2))
    print("results.json ->", work / "results.json")

    if not a.keep:
        shutil.rmtree(envroot, ignore_errors=True)
        shutil.rmtree(appdata, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
