# Verifying venvy's claims

Every claim in the README is meant to be checkable. This file lists the commands.
Run them yourself; none of them need network access after the first, and none of them
install anything malicious.

Last run: 2026-09-22, venvy 1.1.0 from PyPI, Windows 11, Python 3.10.
Advisory database of that date: 27,579 advisories, 13,667 malicious records, 26 MB.

To keep your own registry untouched, point venvy's data directory somewhere temporary:
`APPDATA` on Windows, `XDG_CONFIG_HOME` on Linux, `~/Library/Application Support` on macOS.

---

## 1. First run works from a clean install

```bash
python -m venv .venv && .venv/bin/pip install venvy
.venv/bin/venvy audit --env .venv
```

Expected: the advisory database downloads once, the scan runs, exit code `0` on a clean
environment. Observed: 9.5 s total including the download, scan itself 52 ms.

## 2. Known-vulnerable packages are found, exit code 20

```bash
python -m venv vuln && vuln/bin/pip install "requests==2.32.5" "urllib3==2.6.3"
venvy audit --env vuln; echo $?
```

Expected: findings for both packages with fix versions, exit `20`. Observed: 6 advisories
across the two packages, exit `20`, scan 276 ms.

## 3. Malicious packages are found without installing one

venvy reads `*.dist-info` metadata as text and never imports the package. You can prove
both halves of that at once by fabricating metadata for a package that is in the malicious
feed, without the package existing at all:

```bash
mkdir -p mal/lib/python3.10/site-packages/security_util_py-0.0.6.dist-info
printf 'Metadata-Version: 2.1\nName: security-util-py\nVersion: 0.0.6\n' \
  > mal/lib/python3.10/site-packages/security_util_py-0.0.6.dist-info/METADATA
printf 'home = x\nversion = 3.10.0\n' > mal/pyvenv.cfg
venvy audit --env mal; echo $?
```

Expected: `security-util-py 0.0.6` flagged as malicious against `MAL-2023-10`, exit `21`.
Observed: exactly that. There is no code in that directory, only a text file, which is
the point: an inventory that had to import or execute the package would find nothing here,
and an inventory that executes a real malicious package has already lost.

## 4. It fails closed rather than reporting a false all-clear

Three ways a database can be unusable. All three must refuse to scan.

```bash
# (a) no database at all
XDG_CONFIG_HOME=$(mktemp -d) venvy audit --env vuln --offline; echo $?

# (b) corrupt file
D=$(mktemp -d); mkdir -p $D/venvy/audit
head -c 400000 /dev/urandom > $D/venvy/audit/osv-pypi.sqlite
XDG_CONFIG_HOME=$D venvy audit --env vuln --offline; echo $?

# (c) valid SQLite, correct schema, zero rows — the dangerous one
```

Expected `23` for all three. Observed `23` for all three, each with a message naming the
cause and the fix. Case (c) matters most: a database that opens cleanly but holds no
advisories would make every package read as clean. venvy reports
`has no usable advisories (advisories=0, affected=0)` instead.

## 5. Stale data degrades the exit code instead of lying

Backdate `built_at` in the database's `meta` table by more than 14 days, then scan a clean
environment.

Expected: a stale warning and exit `22`, not `0`. Observed: `advisory database is stale
(34 days old)`, exit `22`. On an environment that also has vulnerable packages, exit `20`
wins, confirming the documented precedence malicious > vulnerable > stale > clean.

## 6. Scans need no network

With a database already present:

```bash
venvy audit --env vuln --offline; echo $?
```

Expected: a normal scan. Observed: exit `20` in 28 ms with `--offline` set, which fails
if anything tries to reach the network.

## 7. JSON output is versioned and machine-readable

```bash
venvy audit --env vuln --json | python -m json.tool | head
```

Observed: valid JSON, `schema_version: 1`, top-level keys `schema_version`, `exit_code`,
`success`, `generated_at`, `db`, `summary`, `environments`, `errors`.

## 8. The test suite passes

```bash
pip install -e ".[dev]" && pytest
```

Observed: 230 collected, 229 passed, 1 skipped (a symlink test that needs privileges
Windows does not grant by default). CI runs the same suite on Windows, macOS and Linux
across Python 3.8 to 3.13.

---

## What a full machine scan actually costs

On one developer laptop, `venvy audit --scan` (full-disk discovery, not the fast default
path) found 13 environments, scanned 1,429 packages (1,199 unique), and reported 187
affected application packages across 10 environments; 3 environments were clean.
No malicious packages on that machine.

That scan took **192 seconds**, with no progress output while it ran. This is the known
limitation tracked in [#4](https://github.com/pranavkumaarofficial/venvy/issues/4).
The default `venvy audit`, which uses the registry instead of walking the disk, completes
in tens of milliseconds per environment.
