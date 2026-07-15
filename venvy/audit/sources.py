"""
sources.py — enrichment feeds that widen malicious coverage beyond OSV's MAL- records.

Both feeds are converted into OSV-shaped record dicts so they flow through the SAME
compile path (parse_osv_affected) and the SAME matcher as everything else — no parallel
matching logic, no second source of truth.

  * DataDog malicious-software-packages-dataset (samples/pypi/manifest.json):
        { "<pkg>": null | ["1.4.1", ...] }   null => every version is malicious.
  * ecosyste-ms typosquatting-dataset (typosquats.csv):
        malicious_package,target_package,ecosystem,registry,classification,source

Fetching is best-effort at the refresh layer: if a feed is unreachable, the refresh
proceeds with whatever it has rather than failing the whole database build.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Dict, Iterator, List, Tuple
from urllib.request import Request, urlopen

DEFAULT_DATADOG_URL = (
    "https://raw.githubusercontent.com/DataDog/"
    "malicious-software-packages-dataset/main/samples/pypi/manifest.json"
)
DEFAULT_TYPOSQUAT_URL = (
    "https://raw.githubusercontent.com/ecosyste-ms/"
    "typosquatting-dataset/main/typosquats.csv"
)

_TIMEOUT = 120
_MAX_BYTES = 64 * 1024 * 1024

# An open-ended range meaning "every version is malicious".
_ALL_VERSIONS = [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]


def _download_bytes(url: str) -> Tuple[bytes, str]:
    """Download over HTTPS, size-capped. Returns (data, sha256_hex)."""
    if not url.lower().startswith("https://"):
        raise ValueError("refusing non-HTTPS source: %s" % url)
    req = Request(url, headers={"User-Agent": "venvy-audit"})
    hasher = hashlib.sha256()
    chunks: List[bytes] = []
    total = 0
    with urlopen(req, timeout=_TIMEOUT) as resp:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_BYTES:
                raise ValueError("source exceeds size cap: %s" % url)
            hasher.update(chunk)
            chunks.append(chunk)
    return b"".join(chunks), hasher.hexdigest()


# ---------------------------------------------------------------------------
# DataDog malicious packages.
# ---------------------------------------------------------------------------
def fetch_datadog(url: str = DEFAULT_DATADOG_URL) -> Tuple[dict, str]:
    data, sha = _download_bytes(url)
    return json.loads(data), sha


def datadog_to_osv(manifest: Dict[str, object]) -> Iterator[dict]:
    """Convert a DataDog PyPI manifest into OSV-shaped malicious records."""
    for name, versions in manifest.items():
        if not name:
            continue
        affected: dict = {"package": {"ecosystem": "PyPI", "name": name}}
        if versions is None:
            affected["ranges"] = _ALL_VERSIONS
        else:
            vlist = [str(v) for v in versions if str(v).strip()]
            if vlist:
                affected["versions"] = vlist
            else:
                affected["ranges"] = _ALL_VERSIONS  # empty list -> treat as all versions
        yield {
            "id": "MAL-DD-PyPI-%s" % name,
            "summary": "Malicious package (DataDog malicious-software-packages-dataset)",
            "database_specific": {"malicious": True},
            "affected": [affected],
        }


# ---------------------------------------------------------------------------
# Typosquats.
# ---------------------------------------------------------------------------
def fetch_typosquats(url: str = DEFAULT_TYPOSQUAT_URL) -> Tuple[str, str]:
    data, sha = _download_bytes(url)
    return data.decode("utf-8", "replace"), sha


def typosquats_to_osv(csv_text: str) -> Iterator[dict]:
    """Convert the PyPI rows of typosquats.csv into OSV-shaped malicious records.

    Name-level (all-versions) match: having a known-typosquat package installed is a
    supply-chain red flag regardless of version. The legitimate target is carried in the
    summary so the report can say "typosquat of 'requests'". Deduplicated by name.
    """
    seen = set()
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if (row.get("ecosystem") or "").strip().lower() != "pypi":
            continue
        mal = (row.get("malicious_package") or "").strip()
        if not mal or mal in seen:
            continue
        seen.add(mal)
        target = (row.get("target_package") or "").strip()
        source = (row.get("source") or "").strip()
        summary = "Known typosquat of '%s'%s - verify you did not mean '%s'" % (
            target, (" (%s)" % source if source else ""), target,
        )
        yield {
            "id": "MAL-TYPO-PyPI-%s" % mal,
            "summary": summary,
            "database_specific": {"malicious": True},
            "affected": [{
                "package": {"ecosystem": "PyPI", "name": mal},
                "ranges": _ALL_VERSIONS,
            }],
        }
