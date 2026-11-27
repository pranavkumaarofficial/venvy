# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security → Report a vulnerability** on this repository. Do not open a public issue.

Include the venvy version (`venvy --version`), your OS and Python version, and the
smallest environment or command that reproduces the problem.

You should get a first reply within 7 days. Fixes ship as a patch release, with credit
in the CHANGELOG unless you ask otherwise.

## What counts as a security issue here

- venvy executes, imports or spawns code from an environment it scans.
- A scan opens a network connection while a usable advisory database exists.
- A scan reports clean (exit `0`) for an installed version the database marks affected
  or malicious. This is a false all-clear and the worst bug venvy can have.
- A crafted feed, zip or `dist-info` directory crashes venvy, hangs it, or writes
  outside venvy's data directory.
- `venvy dedup --apply` corrupts or removes a file in an environment.

A missing advisory (a known-bad package the upstream feeds don't list) is a coverage
gap, not a vulnerability. Please file it as a normal issue; see
[#3](https://github.com/pranavkumaarofficial/venvy/issues/3).

## Supported versions

Only the latest release on PyPI gets fixes.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for what venvy trusts and what it does
not defend against.
