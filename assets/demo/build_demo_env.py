"""Build a deterministic, HARMLESS demo environment for the venvy README GIF.

No package is ever installed and no code from these names ever runs. We only write
``*.dist-info/METADATA`` text files, which is exactly (and only) what ``venvy audit``
reads. The names/versions are chosen so the scan shows one recognizable malicious
typosquat plus a few genuinely vulnerable versions, for a tight, dramatic demo.

Each directory's mtime is pinned to a fixed past date so the ``landed`` column in the
report shows a realistic spread — the malicious typosquat arriving weeks ago is the
whole point: "this landed on the 8th, scope what was exposed."

Usage:  python assets/demo/build_demo_env.py <target_dir>
"""
import os
import sys
from datetime import datetime
from pathlib import Path

# (dist_name, version, landed) — versions are real and genuinely flagged; nothing runs.
PACKAGES = [
    ("requestts", "1.0.0", "2026-07-08"),   # malicious typosquat of "requests"
    ("PyYAML", "5.3.1", "2025-11-02"),       # vulnerable — the classic yaml.load RCE
    ("requests", "2.32.4", "2026-03-15"),    # vulnerable — even a recent version isn't clean
    ("click", "8.1.8", "2026-01-20"),        # vulnerable — single advisory, tight table
    ("numpy", "1.22.0", "2025-09-10"),       # clean — proves the scan discriminates
]


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-env")
    site = target / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (target / "pyvenv.cfg").write_text("version = 3.11.9\n")
    for name, ver, landed in PACKAGES:
        d = site / f"{name}-{ver}.dist-info"
        d.mkdir(parents=True, exist_ok=True)
        (d / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {ver}\n"
        )
        # Pin the dist-info mtime to the demo "install date" (local noon on that day).
        ts = datetime.strptime(landed + " 12:00", "%Y-%m-%d %H:%M").timestamp()
        os.utime(d, (ts, ts))
    print(f"demo env ready at {target} ({len(PACKAGES)} packages, metadata only)")


if __name__ == "__main__":
    main()
