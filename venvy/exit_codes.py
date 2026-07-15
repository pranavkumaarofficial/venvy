"""
Semantic exit codes for agent-friendly CLI operation.

AI coding agents parse these exit codes to understand what happened
and decide how to self-correct without guessing.
"""


class ExitCode:
    SUCCESS = 0
    GENERAL_ERROR = 1
    ENV_NOT_FOUND = 2
    DEPENDENCY_CONFLICT = 3
    PYTHON_VERSION_NOT_FOUND = 4
    CHECKPOINT_NOT_FOUND = 5
    # 6 retired (was GEMMA_NOT_AVAILABLE; the on-device LLM was removed)
    PERMISSION_DENIED = 7
    INIT_FAILED = 8

    # Audit results (parse these to gate CI / drive agent decisions).
    # Precedence when several apply: MALICIOUS > VULNERABLE > STALE_OR_PARTIAL > SUCCESS.
    AUDIT_VULNERABLE = 20        # one or more known-vulnerable packages found
    AUDIT_MALICIOUS = 21         # one or more known-malicious packages found (dominates)
    AUDIT_STALE_OR_PARTIAL = 22  # completed, but DB is stale or some envs/versions unknown
    AUDIT_DB_MISSING = 23        # no advisory database — run `venvy audit --refresh`
