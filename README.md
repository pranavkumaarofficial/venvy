# venvy — Offline Python Supply-Chain Security Audit for Every Virtual Environment

**venvy** knows where **every Python virtual environment on your machine** is — then it **audits them for known-vulnerable and malicious packages** (fully **offline**, deterministic, CI- and AI-agent-ready) and **reclaims the disk space they waste** by deduplicating identical files. It also doubles as a lightweight environment manager (registry, checkpoints, safe installs).

[![PyPI version](https://img.shields.io/pypi/v/venvy.svg)](https://pypi.org/project/venvy/) 
[![Tests](https://github.com/pranavkumaarofficial/venvy/actions/workflows/tests.yml/badge.svg)](https://github.com/pranavkumaarofficial/venvy/actions/workflows/tests.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/venvy.svg)](https://pypi.org/project/venvy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Scan: offline](https://img.shields.io/badge/scan-100%25%20offline-brightgreen.svg)](#how-it-works)
[![Detects: CVEs + malicious](https://img.shields.io/badge/detects-CVEs%20%2B%20malicious-critical.svg)](#what-venvy-detects)
[![Agent & CI ready](https://img.shields.io/badge/output-JSON%20%2B%20exit%20codes-informational.svg)](#json-output-for-ci--ai-agents)

> **Keywords:** python security audit · vulnerable package scanner · malicious PyPI package detection · offline CVE scanner · supply-chain security · typosquatting detection · pip-audit alternative · virtual environment manager · OSV database · CI dependency scanning · venv disk space · deduplicate virtual environments · hardlink dedup · reclaim disk space python.

---

## Table of Contents

- [Why venvy](#why-venvy)
- [What venvy detects](#what-venvy-detects)
- [Reclaim disk space](#reclaim-disk-space)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Exit codes](#exit-codes)
- [JSON output (for CI & AI agents)](#json-output-for-ci--ai-agents)
- [How it works](#how-it-works)
- [venvy vs pip-audit vs safety](#venvy-vs-pip-audit-vs-safety)
- [Virtual-environment management](#virtual-environment-management)
- [FAQ](#faq)
- [Coverage & limitations](#coverage--limitations)
- [Contributing](#contributing)
- [License](#license)

---

## Why venvy

Most Python security scanners audit **one project at a time**, need the **network**, and only look for **CVEs**. venvy fills the gap none of them cover at once:

| Capability | What it means | Who else does it |
|---|---|---|
| **Machine-wide** | Audit *every* environment on the box in one command, not one project at a time | Nobody, by default |
| **Offline-first** | Scans run with zero network; a one-time database download is the only online step | Not pip-audit |
| **CVEs *and* malicious** | Flags known-vulnerable versions **and** known-malicious / typosquat packages | Rare in one tool |
| **Agent- & CI-native** | Stable JSON schema + semantic exit codes designed for automation | Partial elsewhere |

**Built for the AI-coding era.** An LLM cannot be trusted to answer "is this package safe?" — it will hallucinate a CVE. venvy is a **deterministic ground-truth lookup** an agent can call (`venvy audit --json`) and rely on.

---

## What venvy detects

| Finding type | Description | Example |
|---|---|---|
| **Vulnerable** | An installed version falls within a known-vulnerable range (CVE / GHSA / PYSEC) | `requests 2.19.0` → GHSA-… (fixed in 2.20) |
| **Malicious** | An installed package/version is on a known-malicious list | `ctx`, `django`-typosquats |
| **Typosquat** | The package name matches a known typosquat of a popular library | `reqeusts` → "did you mean `requests`?" |
| **Unknown** | An advisory exists but cannot be version-scoped — surfaced, never silently cleared | reported as `unknown` |

**Correctness-first by design:** anything that cannot be confidently evaluated is reported as `unknown`, never as "safe." A false "you're clean" is treated as a critical bug.

---

## Reclaim disk space

Every virtual environment stores its **own byte-for-byte copy** of the same wheels. Ten environments with `numpy` store `numpy` ten times. AI coding agents make this dramatically worse — every throwaway project spawns another environment full of the same libraries.

`venvy dedup` finds files that are **provably identical** across your environments and collapses them onto one inode using hardlinks. **Nothing is deleted. Every environment keeps working.**

```bash
venvy dedup            # read-only: show what could be reclaimed
venvy dedup --apply    # collapse duplicates into hardlinks
venvy dedup --json     # machine-readable
```

```text
18.2 MB reclaimable across 3 environment(s) (659 duplicate group(s), 1879 files scanned)
reclaimable  size      copies  file
1.1 MB       226.6 KB  6       pyparsing.py
410.8 KB     136.9 KB  4       _emoji_codes.py
320.0 KB     64.0 KB   6       cli-32.exe
```

That's a **real measurement on three small environments** — roughly a quarter of their total size. It also catches *intra*-environment waste (pip and setuptools each vendor their own copy of `pyparsing`). Machines with several ML environments have far more to gain, since every copy of a large wheel collapses to one.

**How it stays safe** — a dedup tool that corrupts an environment is worse than no dedup tool:

| Rule | Why |
|---|---|
| Never `.pyc` / `__pycache__` | CPython rewrites bytecode **in place**; an in-place write through a shared inode would corrupt every other environment |
| Byte-identity verified by **hash** | Never inferred from size or mtime, and re-verified immediately before linking |
| Changed-since-scan files are skipped | Reported, never clobbered |
| Same filesystem only | Hardlinks cannot cross devices |
| Atomic swap | Links to a temp name then `os.replace`, so the file is never absent even mid-crash |
| Read-only by default | Nothing changes until you pass `--apply` |

Verified end-to-end on real environments: 8.9 MB reclaimed across 374 files, both environments still importing and running `pip` afterwards, with every unlinked file accounted for.

---

## Installation

```bash
pip install venvy
```

Requires **Python 3.8+**. Works on **Windows, macOS, and Linux** — the full test suite runs on all three across Python 3.8–3.13 in [CI](https://github.com/pranavkumaarofficial/venvy/actions/workflows/tests.yml) on every commit. No compiler, no heavyweight dependencies.

---

## Quick start

```bash
# Audit every known environment on your machine.
# On first run, venvy downloads a one-time advisory database (~30MB).
# Every scan after that is fully offline.
venvy audit

# Audit a single environment
venvy audit --env .venv

# Machine-readable output for CI or an AI agent
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

### Security audit

| Command | Description |
|---|---|
| `venvy audit` | Scan all known environments (auto-fetches the database on first run) |
| `venvy audit --env <path>` | Scan a specific environment (repeatable) |
| `venvy audit --json` | Emit the versioned JSON report (CI / agents) |
| `venvy audit --refresh` | Download the latest advisory database, then scan |
| `venvy audit --offline` | Never access the network; fail if no local database exists |
| `venvy audit --scan` | Also discover unregistered environments on disk |
| `venvy audit --include-toolchain` | Include `pip`/`setuptools`/`wheel` in findings and the exit code |

**Toolchain handling:** `pip`, `setuptools`, and `wheel` ship in nearly every venv and carry many advisories. They are always *reported* but excluded from the exit-code gate by default, so a stale bundled `pip` never buries a real application-dependency finding. Use `--include-toolchain` to gate on them too.

### Disk-space reclamation

| Command | Description |
|---|---|
| `venvy dedup` | Read-only: report space reclaimable by deduplicating identical files |
| `venvy dedup --apply` | Collapse duplicates into hardlinks (nothing is deleted) |
| `venvy dedup --env <path>` | Limit to specific environments (repeatable) |
| `venvy dedup --min-size <bytes>` | Ignore files below this size (default 4096) |
| `venvy dedup --json` | Machine-readable report |

### Environment management

| Command | Description |
|---|---|
| `venvy ls` | List all registered environments |
| `venvy ensure` | Create or verify an environment (idempotent) |
| `venvy safe-install <pkgs>` | Install packages with automatic rollback on failure |
| `venvy checkpoint --name <n>` | Snapshot environment state |
| `venvy rollback --latest` | Restore the last checkpoint |
| `venvy status` | Environment health report |
| `venvy doctor` | Diagnose setup issues |

Add `--json` to any command for structured output.

---

## Exit codes

venvy returns **semantic exit codes** so scripts, CI gates, and agents can branch on the result without parsing text.

| Code | Meaning |
|---|---|
| `0` | Clean — no findings |
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

## JSON output (for CI & AI agents)

`venvy audit --json` emits a **stable, versioned** schema. Key fields:

| Field | Description |
|---|---|
| `schema_version` | Integer; incremented only on breaking changes |
| `exit_code` / `success` | The exit code and a boolean mirror |
| `db.built_at` / `db.age_days` / `db.stale` | Advisory-database provenance and freshness |
| `db.sources[]` | Each data feed with its URL, SHA-256, and fetch time |
| `summary` | Counts: envs scanned, packages, unique packages, vulnerable, malicious, unknown |
| `environments[]` | Per-environment `findings[]` (package, version, advisory ID, severity, fixed versions) and `errors[]` |

Unknowns and errors are **first-class arrays** — they are never omitted, so automation can distinguish "clean" from "could not determine."

---

## How it works

1. **Enumerate** every environment from venvy's local registry (plus optional on-disk discovery).
2. **Read** each environment's installed packages directly from `*.dist-info` metadata — **text only, no subprocess, and never importing the scanned package** (importing a malicious package would run its code).
3. **Match** each `name==version` against a **local, prebuilt advisory database** using exact PEP 440 version-range evaluation. No network, no randomness, no model.
4. **Report** findings with the honest headline count, malicious-first, with fix versions.

**Advisory data** is compiled offline into a single SQLite index from:

| Source | Contribution |
|---|---|
| [OSV.dev](https://osv.dev) (PyPI) | ~26,000 advisories, including ~13,000 known-malicious package records |
| [DataDog malicious-software-packages-dataset](https://github.com/DataDog/malicious-software-packages-dataset) | Curated malicious PyPI packages |
| [ecosyste.ms typosquatting dataset](https://github.com/ecosyste-ms/typosquatting-dataset) | Name-to-target typosquat mappings |

The database ships as one snapshot; `venvy audit --refresh` rebuilds it. venvy **never publishes an empty or corrupt database over a working one**, and refuses to scan against an unusable database (fail-closed to exit `23`) rather than reporting a false "clean."

---

## venvy vs pip-audit vs safety

| Capability | venvy | pip-audit | safety |
|---|:---:|:---:|:---:|
| Scan installed packages for CVEs | Yes | Yes | Yes |
| Detect malicious / typosquat packages | **Yes** | No | Partial |
| Audit **all environments** at once | **Yes** | No (per-project) | No |
| Fully **offline** scan | **Yes** | No | Partial |
| Machine-parseable JSON | Yes | Yes | Yes |
| Semantic exit codes | Yes | Partial | Partial |
| Also manages virtual environments | **Yes** | No | No |
| License | MIT | Apache-2.0 | MIT (DB tiered) |

*Comparison reflects the default, freely available behavior of each tool. pip-audit and safety are excellent CVE scanners; venvy's edge is the offline, machine-wide, malicious-aware, agent-native combination.*

---

## Virtual-environment management

venvy started as an agent-safe environment manager and still is one. It keeps a local SQLite registry of your environments and supports safe, idempotent workflows:

```bash
venvy ensure --python 3.11 --json          # create/verify an environment
venvy safe-install requests flask --json   # install with auto-rollback on failure
venvy checkpoint --name "before-refactor"  # snapshot before risky changes
venvy rollback --latest                     # restore if something breaks
venvy ls --json                             # list all environments
```

---

## FAQ

**Is `venvy audit` really offline?**
Yes. The scan itself never touches the network. The only online step is the one-time advisory-database download (or `--refresh`). Use `--offline` to hard-fail if no local database exists.

**How is this different from `pip-audit`?**
`pip-audit` is a strong per-project, online CVE scanner. venvy adds three things it does not do by default: it scans **every** environment at once, it works **offline**, and it detects **malicious/typosquat** packages — not just CVEs.

**Does it run any code from the packages it scans?**
No. venvy reads `*.dist-info` metadata as text. It never imports a scanned package or runs `pip` inside the target environment.

**Can my AI agent use it?**
Yes — that is a primary design goal. `venvy audit --json` returns a deterministic, versioned report with semantic exit codes, so an agent gets ground truth instead of a hallucinated answer.

**Which Python versions and OSes are supported?**
Python 3.8+ on Windows, macOS, and Linux.

**Does it audit Conda environments?**
It audits the `pip`-installed packages inside any environment (including Conda envs). Conda-channel packages are out of scope for now.

---

## Coverage & limitations

venvy is deliberately honest about what it does **not** cover. Each known gap is tracked as an open issue — **contributions welcome**, see [all open issues](https://github.com/pranavkumaarofficial/venvy/issues).

| Limitation | Detail | Issue |
|---|---|---|
| **Malicious coverage is partial** | Detection is only as complete as its public feeds (~13k malicious records). Some well-known historical typosquats (`python3-dateutil`, `jeIlyfish`, `colourama`) are **not** currently flagged. | [#3](https://github.com/pranavkumaarofficial/venvy/issues/3) |
| **`--scan` is slow** | Full-disk discovery of unregistered environments can take >2 minutes with no progress output. The default `venvy audit` path is fast. | [#4](https://github.com/pranavkumaarofficial/venvy/issues/4) |
| **Conda-channel packages not audited** | Only `pip`-installed packages inside an environment are scanned (including inside Conda envs). `conda-meta` packages are out of scope. | [#5](https://github.com/pranavkumaarofficial/venvy/issues/5) |
| **Scale unbenchmarked** | The dedup optimization is proven at small scale but not yet measured at 50–100 environments. | [#6](https://github.com/pranavkumaarofficial/venvy/issues/6) |

Also worth knowing:
- **No scanner catches a novel supply-chain 0-day.** venvy matches against *known* advisories. Pair it with dependency cooldowns and least-privilege dev environments.
- **Advisory data ages between refreshes.** venvy prints the database age on every run and degrades the exit code when it is stale, rather than silently presenting old data as current.
- **Brand-new or already-yanked malicious packages** may not appear in the feeds yet.

---

## Contributing

```bash
git clone https://github.com/pranavkumaarofficial/venvy
cd venvy
pip install -e ".[dev]"
pytest            # run the test suite
venvy audit       # try it locally
```

Issues and pull requests are welcome. If you find a false positive or a false negative in the matcher, please open an issue with the package, version, and advisory ID — those become permanent regression tests.

**Looking for something to work on?** The known gaps in [Coverage & limitations](#coverage--limitations) are filed as issues tagged `help wanted` — each one includes the context, the proposed approach, and exactly which files to start in:

- [#3 Expand malicious-package coverage](https://github.com/pranavkumaarofficial/venvy/issues/3) — highest impact
- [#4 Speed up `--scan` discovery](https://github.com/pranavkumaarofficial/venvy/issues/4)
- [#5 Audit Conda-channel packages](https://github.com/pranavkumaarofficial/venvy/issues/5)
- [#6 Benchmark at 50–100 environments](https://github.com/pranavkumaarofficial/venvy/issues/6)

CI runs the full suite on Windows, macOS, and Linux across Python 3.8–3.13 for every push and PR.

---

## License

[MIT](LICENSE) © Pranav Kumaar
