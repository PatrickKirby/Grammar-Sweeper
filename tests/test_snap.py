"""Pane placement: the border arithmetic and the keeper's states, with no real windows."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sweeper.gui import snap  # noqa: E402


def test_compensate_adds_the_invisible_border():
    outer = (0, 0, 108, 208)  # 8 px of border left, right and bottom, none on top
    frame = (8, 0, 100, 200)
    assert snap.compensate(outer, frame, (500, 0, 1000, 800)) == (492, 0, 1008, 808)


def test_compensate_is_a_no_op_without_a_border():
    rect = (10, 10, 110, 110)
    assert snap.compensate(rect, rect, (0, 0, 50, 50)) == (0, 0, 50, 50)


def test_within_allows_the_tolerance_and_no_more():
    target = (100, 0, 500, 400)
    assert snap.within((100 + snap.TOLERANCE, 0, 500, 400), target)
    assert not snap.within((100 + snap.TOLERANCE + 1, 0, 500, 400), target)


def test_layout_is_app_left_and_word_right(monkeypatch):
    monkeypatch.setattr(snap, "work_area", lambda: (0, 0, 1920, 1032))
    assert snap.app_target(600) == (0, 0, 600, 1032)
    assert snap.word_target(600) == (600, 0, 1920, 1032)


def test_toaster_docks_above_grammarly_at_its_width(monkeypatch):
    placed = []
    monkeypatch.setattr(snap, "work_area", lambda: (0, 0, 1920, 1000))
    monkeypatch.setattr(snap, "grammarly_window", lambda: 9)
    monkeypatch.setattr(snap, "frame_rect", lambda hwnd: (1465, 272, 1917, 1004))
    monkeypatch.setattr(snap, "place", lambda hwnd, target: placed.append(target) or True)
    assert snap.dock_above_grammarly(400) == (1465, 0, 1917, 400)
    assert placed == [(1465, 400, 1917, 1000)]  # the panel moves down and shortens to fit


def test_toaster_has_no_dock_without_the_panel(monkeypatch):
    monkeypatch.setattr(snap, "grammarly_window", lambda: 0)
    assert snap.dock_above_grammarly(400) is None


def test_keeper_reports_a_state_once(monkeypatch):
    notes = []
    keeper = snap.PaneKeeper(lambda: 300, lambda: None, lambda: 0, lambda event, **data: notes.append((event, data)))
    assert keeper.tick() == "no-document"
    assert keeper.tick() == "no-document"
    assert len(notes) == 1


def test_keeper_does_not_start_word_unless_asked(monkeypatch):
    started = []
    monkeypatch.setattr(snap, "find_word", lambda fragment: 0)
    monkeypatch.setattr(snap.os, "startfile", started.append, raising=False)
    keeper = snap.PaneKeeper(lambda: 300, lambda: "C:/docs/a.docx", lambda: 0, lambda *a, **k: None)
    assert keeper.tick() == "no-window"
    assert started == []
    assert keeper.tick(start=True) == "starting"
    assert started == ["C:/docs/a.docx"]
    assert keeper.tick() == "starting"  # once started, later ticks keep waiting and do not start again
    assert started == ["C:/docs/a.docx"]


def test_keeper_says_so_when_word_will_not_start(monkeypatch):
    def refuse(path):
        raise OSError("no association")

    monkeypatch.setattr(snap, "find_word", lambda fragment: 0)
    monkeypatch.setattr(snap.os, "startfile", refuse, raising=False)
    keeper = snap.PaneKeeper(lambda: 300, lambda: "C:/docs/a.docx", lambda: 0, lambda *a, **k: None)
    assert keeper.tick(start=True) == "cannot-start"
    assert keeper.tick() == "cannot-start"


def test_keeper_reports_off_target_when_placement_fails(monkeypatch):
    notes = []
    monkeypatch.setattr(snap, "find_word", lambda fragment: 77)
    monkeypatch.setattr(snap, "frame_rect", lambda hwnd: (0, 0, 10, 10))
    monkeypatch.setattr(snap, "place", lambda hwnd, target: False)
    keeper = snap.PaneKeeper(lambda: 300, lambda: "C:/docs/a.docx", lambda: 0, lambda event, **data: notes.append(data))
    assert keeper.tick() == "off-target"
    assert notes[0]["state"] == "off-target"
    assert notes[0]["frame"] == (0, 0, 10, 10)
