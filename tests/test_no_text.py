"""No text available: the recovery ladder, the hold, and the online-document warning."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as ba  # noqa: E402
from sweeper import runner  # noqa: E402


class Audit:
    def __init__(self):
        self.events = []

    def write(self, event, **data):
        self.events.append(event)


class Session:
    def __init__(self):
        self.clicks = []
        self.nudges = 0
        self.available = True

    def click_into_page(self, page, skip=0):
        self.clicks.append((page, skip))
        return True

    def nudge(self):
        self.nudges += 1
        return True

    def scroll_to_page(self, page):
        return True

    def caret_context(self):
        return "inside a table"


class Budget:
    control = None
    page = 5
    no_text_run = 0

    def exhausted(self):
        return False


def setup(monkeypatch, states, reset=False):
    audit = Audit()
    monkeypatch.setattr(ba, "AUDIT", audit)
    monkeypatch.setattr(ba, "log", lambda *a, **k: None)
    monkeypatch.setattr(ba.time, "sleep", lambda s: None)
    monkeypatch.setattr(ba, "reset_panel", lambda window, handle=None: reset)
    monkeypatch.setattr(ba, "foreground_window", lambda: (1, "Notepad", "Notepad"))
    monkeypatch.setattr(ba, "activate", lambda window: audit.events.append("activate"))
    monkeypatch.setattr(ba, "ensure_root", lambda *a, **k: "root")
    feed = iter(states)
    monkeypatch.setattr(ba, "feed_state", lambda *a, **k: next(feed))
    return audit


ARGS = SimpleNamespace(empty_probe=1.5)


def test_refocusing_word_is_tried_first(monkeypatch):
    audit = setup(monkeypatch, ["cards"])
    session = Session()
    state, _root = ba.recover_no_text("root", ARGS, session, Budget(), object(), None, 12)
    assert state == "cards"
    assert session.clicks == [(12, 0)]  # the page's own first paragraph, after the window is in front
    assert audit.events == ["NO_TEXT_SEEN", "activate", "NO_TEXT_RECOVERED"]


def test_a_different_paragraph_can_recover_the_page(monkeypatch):
    audit = setup(monkeypatch, ["no-text", "cards"])
    session = Session()
    state, _root = ba.recover_no_text("root", ARGS, session, Budget(), None, None, 12)
    assert state == "cards"
    assert session.clicks == [(12, 0), (12, 1)]
    assert audit.events == ["NO_TEXT_SEEN", "NO_TEXT_RECOVERED"]


def test_every_rung_is_tried_before_giving_up(monkeypatch):
    audit = setup(monkeypatch, ["no-text"] * 4, reset=False)
    session = Session()
    state, _root = ba.recover_no_text("root", ARGS, session, Budget(), None, None, 12)
    assert state == "no-text"
    assert session.clicks == [(12, 0), (12, 1), (12, 2)]
    assert session.nudges == 1
    assert audit.events == ["NO_TEXT_SEEN", "NO_TEXT_FAILED"]


def test_a_panel_restart_is_the_last_rung(monkeypatch):
    audit = setup(monkeypatch, ["no-text"] * 4 + ["clean"], reset=True)
    session = Session()
    state, _root = ba.recover_no_text("root", ARGS, session, Budget(), None, None, 12)
    assert state == "clean"
    assert audit.events == ["NO_TEXT_SEEN", "NO_TEXT_RECOVERED"]


def test_hold_does_nothing_without_a_control(monkeypatch):
    setup(monkeypatch, [])
    budget = Budget()
    budget.no_text_run = 3
    ba.hold_for_text("root", budget, Session(), None, 12)
    assert budget.no_text_run == 3  # left as it was, a command line run has nobody to wait for


def test_hold_waits_then_resumes_by_itself(monkeypatch):
    setup(monkeypatch, ["no-text", "cards"])
    calls = []
    clock = SimpleNamespace(pause=lambda: calls.append("pause"), resume=lambda: calls.append("resume"))
    control = SimpleNamespace(
        clock=clock, stop_requested=False, set_state=lambda state, message="": calls.append(state)
    )
    budget = Budget()
    budget.control = control
    budget.no_text_run = 3
    ba.hold_for_text("root", budget, Session(), None, 12)
    assert calls == ["pause", ba.NEEDS_USER, "resume", "running"]
    assert budget.no_text_run == 0


def test_online_documents_are_warned_about():
    assert "stored online" in runner.online_note("https://apahk.sharepoint.com/sites/x/doc.docx")
    assert runner.online_note(r"C:\docs\a.docx") is None
