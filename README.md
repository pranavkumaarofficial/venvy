# venvy: offline supply-chain audit for every Python environment on your machine

venvy scans every Python virtual environment on your machine for known-vulnerable and known-malicious packages. The scan runs offline against a local advisory database and returns a versioned JSON report with semantic exit codes, so CI jobs and coding agents can act on the result without parsing text.

[![PyPI version](https://img.shields.io/pypi/v/venvy.svg)](https://pypi.org/project/venvy/)
[![Tests](https://github.com/pranavkumaarofficial/venvy/actions/workflows/tests.yml/badge.svg)](https://github.com/pranavkumaarofficial/venvy/actions/workflows/tests.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/venvy.svg)](https://pypi.org/project/venvy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="assets/demo.gif" alt="venvy audit scanning a virtual environment offline and flagging a malicious typosquat plus vulnerable packages" width="840">
</p>

```bash
pip install venvy
venvy audit          # scan every environment on your machine, offline
```

<details>
<summary><b>Example scan output</b> (text)</summary>

```text
MALICIOUS PACKAGES FOUND - 4 app package(s) affected across 1 env(s)
scanned 5 packages (5 unique) in 69ms
advisory database: 2.0 days old

demo/.venv
   package    version  advisory             severity   fix     landed
!  requestts  1.0.0    MAL-2022-7439        malicious  -       2026-07-08
*  click      8.1.8    PYSEC-2026-2132      HIGH       8.3.3   2026-01-20
*  pyyaml     5.3.1    GHSA-8q59-q68h-6hv4  CRITICAL   5.4     2025-11-02
*  pyyaml     5.3.1    PYSEC-2021-142       UNKNOWN    5.4     2025-11-02
*  requests   2.32.4   GHSA-gc5v-m9x4-r6x2  MODERATE   2.33.0  2026-03-15
*  requests   2.32.4   PYSEC-2026-2275      MEDIUM     2.33.0  2026-03-15
```

`!` malicious, `*` vulnerable. Exit code `21`, so CI fails the build. The `landed` date
comes from the `dist-info` mtime and tells you how long the package has been on disk:
here the typosquat arrived weeks before the scan. The demo environment is reproducible
from [`assets/demo/`](assets/demo/).
</details>

---

## Table of Contents

- [Why venvy](#why-venvy)
- [What venvy detects](#what-venvy-detects)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Exit codes](#exit-codes)
- [JSON output](#json-output)
- [How it works](#how-it-works)
- [Design notes](#design-notes)
- [Keeping the advisory database current](#keeping-the-advisory-database-current)
- [venvy vs pip-audit vs safety](#venvy-vs-pip-audit-vs-safety)
- [Measured performance](#measured-performance)
- [FAQ](#faq)
- [Coverage & limitations](#coverage--limitations)
- [Also included: dedup and environment management](#also-included-dedup-and-environment-management)
- [Contributing](#contributing)
- [License](#license)

---

## Why venvy

pip-audit and safety audit one project at a time, and pip-audit looks up advisories from an online service when it runs. Neither looks at the other twenty environments on the same laptop: the half-finished experiments, the venvs a coding agent created and nobody deleted, the old project that still has a 2021 `pyyaml` in it. Those are the ones nobody is checking.

venvy keeps a registry of every environment on the machine, so it can audit all of them in one command. It downloads its advisory database once and scans offline after that, which also makes CI runs deterministic. It checks known-malicious and typosquat lists alongside CVEs.

An agent asked "is this package safe?" will sometimes invent an answer. `venvy audit --json` is a lookup against published advisories, with exit codes an agent can branch on.

---

## What venvy detects

| Finding type | Description | Example |
|---|---|---|
| **Vulnerable** | An installed version falls within a known-vulnerable range (CVE / GHSA / PYSEC) | `requests 2.19.0` → GHSA-… (fixed in 2.20) |
| **Malicious** | An installed package/version is on a known-malicious list | `ctx`, `django` typosquats |
| **Typosquat** | The package name matches a known typosquat of a popular library | `reqeusts` → "did you mean `requests`?" |
| **Unknown** | An advisory exists but cannot be version-scoped. Reported, never cleared. | reported as `unknown` |

Anything venvy cannot evaluate with confidence is reported as `unknown`, never as safe. A false "you're clean" is the worst bug this tool can have; see [Design notes](#design-notes).

---

## Installation

```bash
pip install venvy
```

Requires Python 3.8+. The test suite runs on Windows, macOS and Linux across Python 3.8 to 3.13 in [CI](https://github.com/pranavkumaarofficial/venvy/actions/workflows/tests.yml) on every push. Dependencies: `click`, `rich`, `packaging`.

---

## Quick start

```bash
# Audit every known environment on your machine.
# On first run, venvy downloads a one-time advisory database (~26MB).
# Every scan after that is offline.
venvy audit

# Audit a single environment
venvy audit --env .venv

# Machine-readable output for CI or an agent
venvy audit --json

# Update the advisory database, then scan
venvy audit --refresh

# Never touch the network; fail if no local database exists (deterministic CI)
venvy audit --offline
```

Example output:

```text
vulnerabilities found - 1 app package(s) affected across 2 env(s) (+4 toolchain)
scanned 17 packages (16 unique) in 61ms
advisory database: 0.1 days old

/path/to/project/.venv
   package  version  advisory             severity  fix
*  pytest   8.4.2    GHSA-6w46-j5rx-g56g  MODERATE  9.0.3

  + 19 toolchain finding(s) (pip/setuptools/wheel) - --include-toolchain to show
```

---

## Command reference

| Command | Description |
|---|---|
| `venvy audit` | Scan all known environments (fetches the database on first run) |
| `venvy audit --env <path>` | Scan a specific environment (repeatable) |
| `venvy audit --json` | Emit the versioned JSON report |
| `venvy audit --refresh` | Download the latest advisory database, then scan |
| `venvy audit --offline` | Never access the network; fail if no local database exists |
| `venvy audit --scan` | Also discover unregistered environments on disk |
| `venvy audit --include-toolchain` | Include `pip`/`setuptools`/`wheel` in findings and the exit code |

`pip`, `setuptools` and `wheel` are reported but left out of the exit code by default. [Design notes](#design-notes) explains why.

Add `--json` to any command for structured output.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Clean, no findings |
| `20` | Vulnerable package(s) found |
| `21` | Malicious package(s) found |
| `22` | Completed with caveats (stale database or unresolved unknowns) |
| `23` | No advisory database (run `venvy audit --refresh`) |

**Precedence:** `malicious (21)` > `vulnerable (20)` > `stale/partial (22)` > `clean (0)`.

```bash
# Example CI gate: fail the build on vulnerable OR malicious findings
venvy audit --offline --json
code=$?
if [ "$code" = "20" ] || [ "$code" = "21" ]; then exit 1; fi
```

---

## JSON output

`venvy audit --json` emits a versioned schema. Key fields:

| Field | Description |
|---|---|
| `schema_version` | Integer; incremented only on breaking changes |
| `exit_code` / `success` | The exit code and a boolean mirror |
| `db.built_at` / `db.age_days` / `db.stale` | Advisory-database provenance and freshness |
| `db.advisory_count` / `db.malicious_count` | Integer record counts in the local database |
| `db.sources[]` | Each data feed with its URL, SHA-256, and fetch time |
| `summary` | Counts: envs scanned, packages, unique packages, vulnerable, malicious, unknown |
| `environments[]` | Per-environment `findings[]` (package, version, advisory ID, severity, fixed versions) and `errors[]` |

Unknowns and errors are always present as arrays, so automation can tell "clean" apart from "could not determine".

---

## How it works

1. **Enumerate** every environment from venvy's local registry (plus optional on-disk discovery).
2. **Read** each environment's installed packages from `*.dist-info` metadata as text. No subprocess, and the scanned package is never imported, because importing a malicious package runs its code.
3. **Match** each `name==version` against a local advisory database using PEP 440 version-range evaluation from `packaging`. No network.
4. **Report** findings malicious-first, with fix versions.

The advisory database is compiled into a single SQLite file from:

| Source | Contribution |
|---|---|
| [OSV.dev](https://osv.dev) (PyPI) | Most of the records, vulnerabilities and known-malicious packages alike |
| [DataDog malicious-software-packages-dataset](https://github.com/DataDog/malicious-software-packages-dataset) | Curated malicious PyPI packages |
| [ecosyste.ms typosquatting dataset](https://github.com/ecosyste-ms/typosquatting-dataset) | Name-to-target typosquat mappings |

A database built on 2026-09-30 held **27,742 advisories, 13,697 of them malicious-package
records**, in a 25.5MB SQLite file. Those counts move as the feeds do; `venvy audit` prints
the totals whenever it builds or refreshes the database, so the number you see is the
number you have. [docs/VERIFY.md](docs/VERIFY.md) has the commands to check every figure in
this README.

venvy never publishes an empty or corrupt database over a working one, and refuses to scan against an unusable database (exit `23`) rather than report a false clean.

---

## Design notes

**Fail closed: "unknown" is a result, not an error.** The matcher (`venvy/audit/matcher.py`) returns `AFFECTED`, `NOT_AFFECTED` or `UNKNOWN`. Any version or range boundary it cannot parse becomes `UNKNOWN` and is shown to the user. Running against the real OSV dump before the first release caught two bugs that would each have produced wrong answers:

- Some OSV records name a package with no version ranges at all. Treating "no range matched" as "not affected" cleared those silently. They are now flagged unscoped and reported as `UNKNOWN`.
- Many OSV records carry a `GIT` range (commit hashes) next to the `ECOSYSTEM` range (versions). The hashes fail to parse as versions and were turning correct results for `cryptography`, `pip`, `pyjwt` and `pygments` into `UNKNOWN`. The matcher now evaluates only `ECOSYSTEM` and untyped ranges.

Both cases are in the golden test corpus (`tests/test_audit_matcher.py`). The cost of failing closed is noise: you will see some `UNKNOWN` rows that a human can clear in a minute. I chose that over a tool that is sometimes silently wrong.

**Read metadata, never import.** The cheap way to list installed packages is `pip freeze` or `importlib.metadata` inside the target environment. Both run code from that environment, and a malicious package's code is exactly what you don't want to run. venvy parses `dist-info` and `egg-info` files as text from outside the environment. The tradeoff is that it only sees what pip-style metadata records, which is why Conda-channel packages are out of scope ([#5](https://github.com/pranavkumaarofficial/venvy/issues/5)).

**Toolchain findings don't set the exit code by default.** Almost every venv ships an old bundled `pip`, and `pip` has many advisories. With the toolchain included, nearly every machine exits `20` on every run, and a gate that always fails gets switched off. So `pip`, `setuptools` and `wheel` are reported in their own section, and the headline counts affected *application* packages rather than raw advisory rows. `--include-toolchain` restores strict gating.

**What I'd do differently.**
- Early versions had an on-device LLM (Gemma) that explained install errors. I removed it in 0.5.0: it added a multi-gigabyte download to a tool whose point is a deterministic answer, and nothing in the audit path needed it. I should have asked "does this need a model?" before building it.
- In 1.1.0, a fresh `pip install venvy` followed by `venvy audit` reported a HIGH finding against venvy's own `click` dependency. A release check that installs from PyPI and audits the result would have caught it before release. The publish workflow now does exactly that, and blocks the release if venvy finds anything in its own install.
- The CLI still carries more than thirty commands from venvy's time as an environment manager. If I started today, the audit would be the whole tool.

---

## Keeping the advisory database current

New advisories are published constantly, so the age of the data matters as much as the scanner.

**You do not need a new version of venvy to get new advisories.** The database is not bundled in the package; it is compiled on your machine from live upstream feeds:

```bash
venvy audit --refresh
```

**venvy tells you when the data is old.** Every run prints the database age. Past 14 days it is treated as stale: you get a warning, and a run that would otherwise be clean exits `22` instead of `0`.

**Scheduling a refresh.** venvy never touches the network during a scan and will not update itself, so you schedule refreshes yourself. Weekly is a reasonable default.

```bash
# Linux/macOS - crontab -e, refresh every Monday at 9am
0 9 * * 1 /usr/local/bin/venvy audit --refresh --json > /tmp/venvy-audit.json
```

```powershell
# Windows - weekly scheduled task
schtasks /create /tn "venvy audit" /tr "venvy audit --refresh --json" /sc weekly /d MON /st 09:00
```

In CI, run `--refresh` on a scheduled workflow and `--offline` on pull requests, so PR builds stay fast and deterministic while the scheduled job keeps the data current.

**Upstream feeds are monitored.** A [scheduled job](https://github.com/pranavkumaarofficial/venvy/actions/workflows/feeds.yml) does a real refresh against the live feeds every week and fails if a source breaks, changes format, or returns implausibly little data.

---

## venvy vs pip-audit vs safety

| Capability | venvy | pip-audit | safety |
|---|:---:|:---:|:---:|
| Scan installed packages for CVEs | Yes | Yes | Yes |
| Detect malicious / typosquat packages | Yes | No | Partial |
| Audit all environments at once | Yes | No (per-project) | No |
| Fully offline scan | Yes | No | Partial |
| Machine-parseable JSON | Yes | Yes | Yes |
| Semantic exit codes | Yes | Partial | Partial |
| License | MIT | Apache-2.0 | MIT (DB tiered) |

*Comparison reflects the default, freely available behavior of each tool. pip-audit and safety are good CVE scanners, and pip-audit can also audit a requirements file before anything is installed, which venvy cannot. venvy's difference is the combination of offline, machine-wide and malicious-aware.*

---

## Measured performance

Measured 2026-11-26 on a Windows 11 laptop (Intel Core i5-1135G7, 8 logical CPUs, NVMe SSD), Python 3.9, advisory database with 29,021 records. Reproduce with:

```bash
python scripts/bench.py --workdir <empty dir> --sizes 10 50 100 --runs 3
```

The script builds N environments from 23 pinned wheels (half Flask web stacks with known-vulnerable pins, a quarter CLI stacks, a quarter numpy), fetches a fresh database into an isolated data directory, and times `venvy audit --offline --json` (one warm-up, median of three runs) and one read-only `venvy dedup --json`. Raw output: [before](docs/benchmarks/2026-11-26-windows-before.json) and [after](docs/benchmarks/2026-11-26-windows-after.json) the 1.2.0 dedup change.

| Envs | Packages | `audit` scan | `audit` wall clock | `dedup` dry run, 1.1.1 | `dedup` dry run, 1.2.0 | Env size | Reclaimable |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 114 | 148 ms | 504 ms | 20.0 s | 1.7 s | 399 MB | 185 MB (46%) |
| 50 | 564 | 230 ms | 703 ms | 64.6 s | 6.3 s | 2,109 MB | 1,340 MB (64%) |
| 100 | 1,125 | 336 ms | 955 ms | 98.8 s | 13.0 s | 4,274 MB | 2,810 MB (66%) |

"Scan" is venvy's own timer; "wall clock" adds Python startup and imports. Audit times are from the 1.2.0 run; the earlier run measured 166 to 412 ms for the same scans, so treat differences of that size as noise. Reclaimable bytes were identical in both runs at every size.

How to read this:
- **The audit numbers flatter venvy.** These environments hold only 23 distinct `name==version` pairs, and venvy does one database lookup per distinct pair, so lookups barely grow with N. A real machine has far more distinct versions. What this does show is that reading 1,125 packages' metadata across 100 environments costs well under a second.
- **The dedup percentages are an upper bound.** Environments built from three package lists are near-copies of each other. Real environments overlap less, so expect less than 66%.
- **Why dedup got faster.** Profiling the 1.1.1 scan showed the time going to reading files and to three `stat` calls per file, not to SHA-256. 1.2.0 walks with `os.scandir` and takes each file's hash from the `RECORD` file pip wrote at install time, when the recorded size matches the size on disk, so most files are never opened. `--apply` ignores `RECORD` and hashes every file before linking it; `--verify` does the same for the dry run.

---

## FAQ

**Is `venvy audit` really offline?**
The scan never touches the network. The only online step is the one-time database download (or `--refresh`). Use `--offline` to hard-fail if no local database exists.

**Does it run any code from the packages it scans?**
No. venvy reads `*.dist-info` metadata as text. It never imports a scanned package or runs `pip` inside the target environment. [`tests/test_audit_invariants.py`](tests/test_audit_invariants.py) checks this with a planted package that writes a file if any of its code runs. [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) lists what venvy trusts and what it doesn't defend against; [SECURITY.md](SECURITY.md) says how to report a problem.

**Can my coding agent use it?**
Yes. `venvy audit --json` returns a versioned report with semantic exit codes. `venvy init` writes a `CLAUDE.md` into a project telling the agent how to call it.

**Which Python versions and OSes are supported?**
Python 3.8+ on Windows, macOS and Linux. On Python 3.8 and 3.9, venvy's own `click` dependency carries CVE-2026-7246 because the fixed release needs Python 3.10; venvy reports it rather than hiding it, and does not call the affected API.

**Does it audit Conda environments?**
It audits the `pip`-installed packages inside any environment, including Conda envs. Conda-channel packages are out of scope for now.

---

## Coverage & limitations

Each known gap is tracked as an open issue; see [all open issues](https://github.com/pranavkumaarofficial/venvy/issues).

| Limitation | Detail | Issue |
|---|---|---|
| **Malicious coverage is partial** | Detection is only as complete as its public feeds (~13k malicious records). Some well-known historical typosquats (`python3-dateutil`, `jeIlyfish`, `colourama`) are **not** currently flagged. | [#3](https://github.com/pranavkumaarofficial/venvy/issues/3) |
| **`--scan` is slow** | Full-disk discovery of unregistered environments can take over two minutes with no progress output. The default `venvy audit` path is fast. | [#4](https://github.com/pranavkumaarofficial/venvy/issues/4) |
| **Conda-channel packages not audited** | Only `pip`-installed packages inside an environment are scanned (including inside Conda envs). `conda-meta` packages are out of scope. | [#5](https://github.com/pranavkumaarofficial/venvy/issues/5) |
| **Benchmarks use synthetic environments** | The 100-environment numbers come from environments built from three package lists, which flatters both audit lookups and dedup savings. No measurement on a real developer machine yet. See [Measured performance](#measured-performance). | [#6](https://github.com/pranavkumaarofficial/venvy/issues/6) |

Also:
- **No scanner catches a novel supply-chain attack.** venvy matches against *known* advisories. Pair it with dependency cooldowns and least-privilege dev environments.
- **Advisory data ages between refreshes.** venvy prints the database age on every run and changes the exit code when it is stale.
- **Brand-new or already-yanked malicious packages** may not be in the feeds yet.

---

## Also included: dedup and environment management

These came before the audit and use the same registry.

**`venvy dedup`** finds byte-identical files across your environments and hardlinks them to one copy. The dry run takes hashes from pip's `RECORD` files where the size matches, so it rarely opens a file. It is read-only until `--apply`, never touches bytecode (`.pyc` is rewritten in place, which would corrupt a shared copy), re-verifies each file's hash immediately before linking, and swaps atomically. Measured on three small environments: 18.2 MB reclaimable, about 25% of their size.

```bash
venvy dedup            # report what could be reclaimed
venvy dedup --apply    # collapse duplicates into hardlinks
```

**Environment management** keeps a local SQLite registry and supports idempotent workflows:

```bash
venvy ensure --python 3.11 --json          # create/verify an environment
venvy safe-install requests flask --json   # install with auto-rollback on failure
venvy checkpoint --name "before-refactor"  # snapshot before risky changes
venvy rollback --latest                     # restore if something breaks
venvy ls --json                             # list all environments
```

Run `venvy --help` for the full list.

---

## Contributing

```bash
git clone https://github.com/pranavkumaarofficial/venvy
cd venvy
pip install -e ".[dev]"
pytest            # run the test suite
venvy audit       # try it locally
```

If you find a false positive or a false negative in the matcher, please open an issue with the package, version and advisory ID. Those become permanent regression tests.

The gaps in [Coverage & limitations](#coverage--limitations) are filed as `help wanted` issues, each with context, a proposed approach and the files to start in. [#3](https://github.com/pranavkumaarofficial/venvy/issues/3) has the most impact.

---

## License

[MIT](LICENSE) © Pranav Kumaar
