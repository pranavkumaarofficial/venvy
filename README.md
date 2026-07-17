# venvy — Offline Python Supply-Chain Security Audit for Every Virtual Environment

**venvy** scans **every Python virtual environment on your machine** for **known-vulnerable and malicious packages** — fully **offline**, deterministic, and in a form your **CI pipelines and AI coding agents** can trust. It also doubles as a lightweight virtual-environment manager (registry, checkpoints, safe installs).

[![PyPI version](https://img.shields.io/pypi/v/venvy.svg)](https://pypi.org/project/venvy/)
[![Python versions](https://img.shields.io/pypi/pyversions/venvy.svg)](https://pypi.org/project/venvy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Scan: offline](https://img.shields.io/badge/scan-100%25%20offline-brightgreen.svg)](#how-it-works)
[![Detects: CVEs + malicious](https://img.shields.io/badge/detects-CVEs%20%2B%20malicious-critical.svg)](#what-venvy-detects)
[![Agent & CI ready](https://img.shields.io/badge/output-JSON%20%2B%20exit%20codes-informational.svg)](#json-output-for-ci--ai-agents)

> **Keywords:** python security audit · vulnerable package scanner · malicious PyPI package detection · offline CVE scanner · supply-chain security · typosquatting detection · pip-audit alternative · virtual environment manager · OSV database · CI dependency scanning.

---

## Table of Contents

- [Why venvy](#why-venvy)
- [What venvy detects](#what-venvy-detects)
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

## Installation

```bash
pip install venvy
```

Requires **Python 3.8+**. Works on **Windows, macOS, and Linux**. No compiler, no heavyweight dependencies.

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

- Detection is only as complete as its public data feeds (OSV + DataDog + typosquat lists). venvy **does not claim** to know every vulnerable or malicious package.
- The malicious-package feeds catch confirmed, published bad actors; brand-new or already-yanked packages may not appear.
- Advisory data ages between refreshes. venvy surfaces the database age on every run and downgrades the exit code when the database is stale.

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

---

## License

[MIT](LICENSE) © Pranav Kumaar
