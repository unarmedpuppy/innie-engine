"""TTY and textual availability detection."""

import sys


def is_interactive() -> bool:
    """Return True if stdout+stdin are TTYs and textual is importable."""
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        return False
    try:
        import textual  # noqa: F401

        return True
    except ImportError:
        return False
