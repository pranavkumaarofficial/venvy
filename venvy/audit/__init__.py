"""
venvy.audit — deterministic supply-chain audit across Python environments.

Design invariants (see ideas/venvy-audit-architecture.md):
  1. No false all-clears. Anything we cannot confidently evaluate is UNKNOWN, never
     folded into "clean".
  2. No code execution from scanned envs. Metadata is read as text only.
  3. Deterministic & reproducible. No network in the scan path, no randomness.
  4. Offline by default; staleness surfaced loudly.
  5. Fail closed, not silent.
"""
