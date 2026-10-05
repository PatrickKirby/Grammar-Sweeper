"""Offscreen smoke test: every screen builds, and the finished screen follows
the result state. Does not touch Word or Grammarly."""

import datetime as dt
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLabel

import bulk_accept as engine
from sweeper import rules, runner
from sweeper.gui import style
from sweeper.gui.hud import Hud
from sweeper.gui.main_window import MainWindow
from sweeper.settings import Settings

APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(style.sheet(style.DARK))


@pytest.fixture
def window(tmp_path, monkeypatch):
    from sweeper import history
    monkeypatch.setattr(history, "_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(runner, "preflight", lambda: {"paths": ["C:/docs/Plan.docx"], "elevated": False, "panel": True})
    settings = Settings(tmp_path / "s.json")
    settings["consent_accepted"] = True
    win = MainWindow(settings, dark=True)
    APP.processEvents()
    return win


def texts(widget):
    return " | ".join(item.text() for item in widget.findChildren(QLabel))


def summary_for(outcome, applied=1284):
    args = runner.build_args(outcome.preset, None)
    budget = engine.Budget(args)
    budget.accepted = applied
    budget.outcome = outcome
    out = engine.RunSummary()
    out.budget = budget
    out.document = "C:/docs/Plan.docx"
    out.finished = dt.datetime.now()
    return out


def outcome(result, **kw):
    base = dict(result=result, reason="r", passes=3, last_applied=4, preset="standard")
    base.update(kw)
    return rules.Outcome(**base)


def test_consent_gate_when_not_accepted(tmp_path):
    win = MainWindow(Settings(tmp_path / "x.json"), dark=False)
    assert win.stack.currentWidget() is win.consent_page


def test_ready_lists_document(window):
    assert window.doc_box.count() == 1
    assert window.start_button.isEnabled()


def test_clear_finished_screen(window):
    window._show_finished(summary_for(outcome(rules.CLEAR)))
    text = texts(window.finished_page)
    assert "Done" in text and "1,284" in text and "2 h 51 min" in text


def test_limit_finished_screen_never_says_nothing_left(window):
    window._show_finished(summary_for(outcome(rules.LIMIT)))
    text = texts(window.finished_page)
    assert "Suggestions may remain" in text and "Nothing left" not in text


def test_repeating_finished_screen(window):
    window._show_finished(summary_for(outcome(rules.REPEATING, matched_passes=(1, 3))))
    assert "started repeating" in texts(window.finished_page)


def test_partial_range_clear_says_so(window):
    window._show_finished(summary_for(outcome(rules.CLEAR, complete_range=False)))
    assert "chosen pages only" in texts(window.finished_page)


def test_hud_tracks_progress_and_states():
    hud = Hud(lambda: 75, None, True)
    hud.set_progress(1284, 37, 109, 2, None)
    hud.tick()
    hud.set_state("needs_user", "Grammarly was closed. Open it in Word to continue.")
    assert hud.applied.text() == "1,284"
    assert "1 min 15 s" in hud.running.text()
    assert hud.ring.percent is None  # unknown stays unknown, never invented
    assert "closed" in hud.message.text()
