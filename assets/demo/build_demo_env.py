"""Build a deterministic, HARMLESS demo environment for the venvy README GIF.

No package is ever installed and no code from these names ever runs. We only write
``*.dist-info/METADATA`` text files, which is exactly (and only) what ``venvy audit``
reads. The names/versions are chosen so the scan shows one recognizable malicious
typosquat plus a few genuinely vulnerable versions, for a tight, dramatic demo.

Usage:  python assets/demo/build_demo_env.py <target_dir>
"""
import sys
from pathlib import Path

# (dist_name, version) — versions are real and genuinely flagged; nothing is executed.
PACKAGES = [
    ("requestts", "1.0.0"),   # malicious typosquat of "requests" (in the advisory feed)
    ("PyYAML", "5.3.1"),      # vulnerable — the classic yaml.load RCE (CRITICAL)
    ("requests", "2.32.4"),   # vulnerable — even a recent version isn't clean
    ("click", "8.1.8"),       # vulnerable — single advisory, keeps the table tight
    ("numpy", "1.22.0"),      # clean — proves the scan discriminates, not all-red
]


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-env")
    site = target / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (target / "pyvenv.cfg").write_text("version = 3.11.9\n")
    for name, ver in PACKAGES:
        d = site / f"{name}-{ver}.dist-info"
        d.mkdir(parents=True, exist_ok=True)
        (d / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {ver}\n"
        )
    print(f"demo env ready at {target} ({len(PACKAGES)} packages, metadata only)")


if __name__ == "__main__":
    main()
