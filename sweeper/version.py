"""The version this program is running, and the build it came from.

A built exe carries `_build_info.py`, written by build.py. Run from source, the
version is read from VERSION and the commit from git, so a source run is stamped
the same way and `-dirty` marks work not yet committed."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _from_source() -> dict:
    info = {"version": "unknown", "commit": "unknown", "built": "source run"}
    try:
        info["version"] = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        flags = {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5, **flags
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=5, **flags
        ).stdout.strip()
        if sha:
            info["commit"] = sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return info


try:
    from sweeper import _build_info

    INFO = {"version": _build_info.VERSION, "commit": _build_info.COMMIT, "built": _build_info.BUILT}
except ImportError:
    INFO = _from_source()

VERSION = INFO["version"]
COMMIT = INFO["commit"]
BUILT = INFO["built"]
LABEL = f"{VERSION} ({COMMIT})"
TITLE = f"Grammar Sweeper {LABEL}, built {BUILT}"
