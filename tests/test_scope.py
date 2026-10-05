"""Grammarly's scope: reading it, and waiting for it to follow the sweep."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as ba  # noqa: E402


class Session:
    def __init__(self):
        self.clicks = []

    def click_into_page(self, page):
        self.clicks.append(page)
        return True

    def nudge(self):
        self.nudges = getattr(self, "nudges", 0) + 1
        return True


def labels(monkeypatch, texts):
    monkeypatch.setattr(ba, "walk", lambda root, depth, deadline: iter([(t, 0) for t in texts]))
    monkeypatch.setattr(ba, "name_of", lambda node: node)


def test_a_short_document_needs_no_page_range(monkeypatch):
    labels(monkeypatch, [])  # Grammarly names no pages for a three page document
    session = Session()
    assert ba.scope_for_stop(None, 1, 3, session, 5.0) == (1, 3)
    assert session.clicks == []


def test_a_long_document_waits_for_the_page_range(monkeypatch):
    labels(monkeypatch, ["3 review suggestions pages 57-66"])
    assert ba.scope_for_stop(None, 60, 111, Session(), 5.0) == (57, 66)


def test_read_scope_takes_the_pages_the_panel_names(monkeypatch):
    labels(monkeypatch, ["3 review suggestions pages 57-66"])
    assert ba.read_scope(None, 1.0) == (57, 66)


def test_read_scope_ignores_card_rows(monkeypatch):
    labels(monkeypatch, ["correctness: see pages 3-4 open suggestion card"])
    assert ba.read_scope(None, 1.0) is None


def test_wait_returns_at_once_when_the_scope_holds_the_page(monkeypatch):
    labels(monkeypatch, ["no unresolved suggestions for pages 24-33"])
    session = Session()
    assert ba.wait_for_scope(None, 26, session, 5.0) == (24, 33)
    assert session.clicks == []


def test_wait_clicks_again_then_gives_up_on_a_stale_panel(monkeypatch):
    labels(monkeypatch, ["no unresolved suggestions for pages 58-67"])
    session = Session()
    assert ba.wait_for_scope(None, 26, session, 1.5) is None
    assert session.clicks == [26]  # once only: a second click restarts Grammarly's delay
    assert session.nudges == 1  # with one key nudge beside it
