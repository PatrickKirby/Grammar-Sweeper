"""Run history and the diagnostics bundle. Both live under %APPDATA%."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from .settings import log_dir, settings_dir

KEEP = 50


def _path() -> Path:
    return settings_dir() / "history.json"


def load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add(entry: dict) -> None:
    entries = (load() + [entry])[-KEEP:]
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except OSError:
        pass  # history is a convenience


def diagnostics_bundle(report: Path | None = None) -> Path:
    """Copy the audit log, run log, settings, the newest screenshots and the
    report into one folder, so it can be sent or inspected in a single place."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = settings_dir() / "diagnostics" / stamp
    target.mkdir(parents=True, exist_ok=True)
    logs = log_dir()
    for name in ("audit.log", "grammar-sweeper.log", "grammar-sweeper-unclassified.log"):
        if (logs / name).exists():
            shutil.copy2(logs / name, target / name)
    if (settings_dir() / "settings.json").exists():
        shutil.copy2(settings_dir() / "settings.json", target / "settings.json")
    shots = sorted((logs / "shots").glob("*.png"))[-10:] if (logs / "shots").exists() else []
    if shots:
        (target / "shots").mkdir(exist_ok=True)
        for shot in shots:
            shutil.copy2(shot, target / "shots" / shot.name)
    if report and report.exists():
        shutil.copy2(report, target / report.name)
    return target
