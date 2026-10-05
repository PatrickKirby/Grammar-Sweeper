"""Render the interface offscreen to PNG files for a visual check.
Usage: python tests/render_screens.py [light|dark]. Output goes to docs/shots/."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtWidgets import QApplication

import test_gui_smoke as t
from sweeper import rules
from sweeper.gui import style
from sweeper.gui.hud import Hud
from sweeper.gui.main_window import MainWindow
from sweeper.settings import Settings

theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
dark = theme == "dark"
app = QApplication.instance()
app.setStyleSheet(style.sheet(style.DARK if dark else style.LIGHT))
out = ROOT / "docs" / "shots"
out.mkdir(parents=True, exist_ok=True)

import tempfile
from sweeper import runner

runner.preflight = lambda: {"paths": ["C:/docs/Delivery Plan vB.docx", "C:/docs/Board Paper.docx"], "elevated": False, "panel": True}
_tmp = Path(tempfile.mkdtemp())
from sweeper import history

history._path = lambda: _tmp / "history.json"
settings = Settings(_tmp / "s.json")
win = MainWindow(settings, dark)
win.resize(600, 900)
win.show()
app.processEvents()
win.grab().save(str(out / f"{theme}-consent.png"))
settings["consent_accepted"] = True
win._show_ready()
app.processEvents()
win.grab().save(str(out / f"{theme}-ready.png"))
for name, outcome in {
    "clear": t.outcome(rules.CLEAR, passes=5),
    "limit": t.outcome(rules.LIMIT),
    "repeat": t.outcome(rules.REPEATING, matched_passes=(1, 3)),
}.items():
    win._show_finished(t.summary_for(outcome))
    app.processEvents()
    win.grab().save(str(out / f"{theme}-finished-{name}.png"))
hud = Hud(lambda: 4321, None, dark)
hud.set_progress(1284, 37, 109, 2, 62.0, 252.0, {"Correctness": 640, "Clarity": 410, "Engagement": 150, "Delivery": 84}, 4, {p: {"Correctness": (p * 7) % 5, "Clarity": (p * 3) % 4, "Engagement": p % 2, "Delivery": (p // 5) % 2, "Unclassified": 1 if p % 3 == 0 else 0} for p in range(1, 110, 5)}, 1, 109, 5,
    {"noeffect": 12, "caret": 94, "passes_done": [46], "eta_run": (1320.0, 2)})
hud.tick()
hud.grab().save(str(out / f"{theme}-hud.png"))
hud.set_state("needs_user", "You switched to another app. Return to Word to continue.")
hud.grab().save(str(out / f"{theme}-hud-needs.png"))
print("rendered to", out)
