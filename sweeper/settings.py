"""Per-user settings, kept in %APPDATA%. Never in the program folder, so an
upgrade or a reinstall cannot wipe them and a read-only install still works."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "consent_accepted": False,
    "preset": "standard",
    "track_changes": "on",  # on, off or leave
    "force_focus": False,  # always take Word back, even after a deliberate switch
    "theme": "system",  # system, light or dark
    "hud_position": None,  # [x, y] once the user has dragged it
    "coffee_dismissed": False,
    "open_report": True,  # open the HTML report when a run ends
    "layouts": {},  # per monitor setup: {"hud": [x, y]}
}


def settings_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Grammar Sweeper"


COFFEE_URL = "https://buymeacoffee.com/preceperi"
REPO_URL = "https://github.com/PatrickKirby/GrammarSweeper"
APERTURA_URL = "https://theapertura.substack.com"
COMPANY = "Preceperi Limited"


def log_dir() -> Path:
    return settings_dir() / "logs"


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_dir() / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass  # first launch, or a damaged file: fall back to defaults

    def __getitem__(self, key: str):
        return self.data[key]

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            tmp.replace(self.path)  # atomic: never leave half a file
        except OSError:
            pass  # a setting not saved is not worth interrupting anyone
