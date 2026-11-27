# Threat model

What `venvy audit` trusts, what it assumes is hostile, and what it does not try to stop.

## Assets

- **The answer.** A scan result someone will act on, often a CI gate or an agent. A
  false "clean" is the failure that matters most.
- **The machine running the scan.** venvy runs with the user's permissions, so anything
  it executes runs with them too.

## Trusted

| Component | Why it is trusted | What would break if it were not |
|---|---|---|
| The Python interpreter running venvy, and venvy's own dependencies (`click`, `rich`, `packaging`) | They are the scanner | Everything. venvy cannot protect itself from its own install |
| Upstream feeds: OSV.dev PyPI dump, DataDog malicious-packages dataset, ecosyste.ms typosquat dataset | They are the source of truth for "affected" | A poisoned feed can hide an advisory. venvy cannot detect that |
| TLS to `osv-vulnerabilities.storage.googleapis.com` and `raw.githubusercontent.com` | Fetches are HTTPS-only (`db.py`, `sources.py` refuse other schemes) | A network attacker could alter feed contents |

Feed SHA-256 hashes are recorded in the database's `sources` metadata and printed in
`--json` output for provenance. They are not checked against a pinned value, because the
feeds change daily.

## Hostile

**Every environment being scanned.** The point of the tool is that one of them may
contain a malicious package. venvy therefore:

- reads `*.dist-info` / `*.egg-info` metadata as text, capped at 256 KB per file
  (`inventory.py`);
- never imports a scanned package, never starts the scanned environment's interpreter
  (so its `.pth` files and `sitecustomize.py` never run), and never runs `pip` there;
- spawns no subprocess during a scan.

Tested in `tests/test_audit_invariants.py`: a planted package, `.pth` file and
`sitecustomize.py` each write a marker file if executed, and `subprocess.Popen` /
`os.system` are trapped. The scan must still report the package as malicious and the
marker must not exist.

**Feed contents, as parsed data.** A truncated or malformed download must not produce a
database that reports clean. venvy:

- caps each zip entry at 8 MB and the archive at 512 MB uncompressed (zip-bomb guard);
- skips unparseable records and counts them;
- refuses to publish a database with zero advisories or zero affected rows over a
  working one, and swaps the new file in atomically;
- validates the database on open; a corrupt or empty database is exit `23`, never a
  clean result.

## Network

A scan opens no sockets when a usable database exists, with or without `--offline`. The
network is used only to fetch the database: on first run, on `--refresh`, or to recover
a corrupt database. `--offline` forbids even that and fails with exit `23`.

Tested in `tests/test_audit_invariants.py` by replacing `socket.socket`,
`socket.create_connection` and `socket.getaddrinfo` with functions that raise.

## Failing closed

When the matcher cannot evaluate a version or range, the result is `UNKNOWN` and it is
reported. It is never counted as not affected. A stale database (older than 14 days)
changes an otherwise clean exit from `0` to `22`.

## Out of scope

- **Unknown attacks.** venvy matches against published advisories. A malicious package
  nobody has reported yet scans clean.
- **Coverage gaps in the feeds.** Some historical typosquats are not listed upstream
  ([#3](https://github.com/pranavkumaarofficial/venvy/issues/3)).
- **Packages without pip-style metadata**, including Conda-channel packages
  ([#5](https://github.com/pranavkumaarofficial/venvy/issues/5)) and code copied into an
  environment by hand.
- **Tampering with metadata.** A package that rewrites its own `dist-info` to report a
  different version will be matched as that version.
- **A compromised machine.** If an attacker can already write to venvy's data directory
  or its install, they can change the database or the scanner.
- **`venvy dedup`, `safe-install`, `checkpoint`.** These change environments on purpose
  and are covered by their own tests, not by the scan invariants above.
