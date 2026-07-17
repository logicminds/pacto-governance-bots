"""Version and commit metadata for bosun."""

from __future__ import annotations

import os
import subprocess
from importlib.metadata import PackageNotFoundError, version


def _get_commit() -> str:
    """Return the short git commit id, or the env override, or 'unknown'."""
    commit = os.environ.get("BOSUN_COMMIT")
    if commit:
        return commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def _get_version() -> str:
    """Return the package version from installed metadata, or the fallback."""
    try:
        return version("bosun")
    except PackageNotFoundError:
        return "0.1.0"


VERSION = _get_version()
COMMIT = _get_commit()


def full_version() -> str:
    """Return a human-readable version string including the git commit id."""
    return f"bosun v{VERSION} (commit {COMMIT})"
