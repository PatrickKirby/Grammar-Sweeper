"""Housekeeping for the files a run leaves behind: screenshots, logs, reports, rule files and the
diagnostic bundles made by Copy diagnostics.

Plain functions over the settings folder, so they are tested without a window. Backups of your
documents, your settings and the run history are never touched here."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

DAY = 86400

# Category key -> (label, glob patterns relative to the settings folder, empty the file instead of
# deleting it). A log is one file written by every run, so cleaning it empties it.
CATEGORIES: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "screenshots": ("Screenshots", ("logs/shots/*.png",), False),
    "audit": ("Audit log", ("logs/audit.log",), True),
    "runlog": ("Run logs", ("logs/grammar-sweeper.log", "logs/grammar-sweeper-unclassified.log"), True),
    "reports": ("Reports", ("logs/report-*.html",), False),
    "changes": (
        "Change records and rule files",
        ("logs/changes-*.jsonl", "logs/rules-*.json", "logs/postprocess-*.json", "logs/fewshot-*.jsonl"),
        False,
    ),
    "diagnostics": ("Diagnostic bundles", ("diagnostics/*",), False),
}

GROUP_KEYS = [key for key in CATEGORIES if key != "changes"]  # change records and rule files have their own button

AGES: dict[str, int | None] = {"All time": None, "Older than 7 days": 7, "Older than 30 days": 30, "Older than 90 days": 90}


@dataclass
class Found:
    files: int = 0
    bytes: int = 0


@dataclass
class Result:
    files: int = 0
    bytes: int = 0
    errors: list[str] = field(default_factory=list)


def _paths(root: Path, key: str) -> list[Path]:
    patterns = CATEGORIES[key][1]
    return sorted({path for pattern in patterns for path in root.glob(pattern) if path.is_file() or path.is_dir()})


def _size(path: Path) -> int:
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return path.stat().st_size


def _mtime(path: Path) -> float:
    if path.is_dir():
        times = [child.stat().st_mtime for child in path.rglob("*") if child.is_file()]
        return max(times) if times else path.stat().st_mtime
    return path.stat().st_mtime


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} GB"


def scan(root: Path) -> dict[str, Found]:
    """What each category holds now."""
    found = {}
    for key in CATEGORIES:
        paths = _paths(root, key)
        if CATEGORIES[key][2]:  # an emptied log has nothing left to clean
            paths = [path for path in paths if _size(path) > 0]
        found[key] = Found(len(paths), sum(_size(path) for path in paths))
    return found


def clean(
    root: Path, keys: list[str], older_than_days: int | None, now: float | None = None, dry_run: bool = False
) -> Result:
    """Remove the chosen categories. `older_than_days` of None means everything. A file counts as old
    by its last write, so a log still being written is never counted as old. Anything that cannot be
    removed is listed in `errors` and the rest carries on. `dry_run` counts what would go and
    removes nothing, so the person can be shown the number before they agree."""
    result = Result()
    cutoff = None if older_than_days is None else (now if now is not None else time.time()) - older_than_days * DAY
    for key in keys:
        if key not in CATEGORIES:
            continue
        truncate = CATEGORIES[key][2]
        for path in _paths(root, key):
            try:
                size = _size(path)
                if cutoff is not None and _mtime(path) > cutoff:
                    continue
                if truncate and size == 0:
                    continue
                if dry_run:
                    pass
                elif truncate:
                    path.open("w", encoding="utf-8").close()
                elif path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                result.files += 1
                result.bytes += size
            except OSError as exc:
                result.errors.append(f"{path.name}: {exc.strerror or exc}")
    return result


def summary_line(found: Found) -> str:
    if not found.files:
        return "Empty"
    return f"{found.files:,} item{'s' if found.files != 1 else ''}, {human_size(found.bytes)}"
