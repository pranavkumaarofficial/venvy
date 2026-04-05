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
    GEMMA_NOT_AVAILABLE = 6
    PERMISSION_DENIED = 7
    INIT_FAILED = 8
