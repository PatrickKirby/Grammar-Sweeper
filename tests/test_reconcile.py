"""Counts that must reconcile with the document, the card type reader, the clean-page
signal and the whole-run estimate. No Word needed."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as engine
from sweeper import rules
from sweeper.gui.hud import Hud


def test_category_read_from_card_header_not_the_document_sentence():
    card = "suggestions | correctness correct punctuation | correctness · correct punctuation | learn more | the delivery plan"
    assert engine.category_from_card(card) == "Correctness"
    assert engine.category_from_card("suggestions | improve wording | learn more | delivery of the plan") == "Clarity"
    assert engine.category_from_card("suggestions | something new | learn more | clarity matters") == "Unclassified"


def _fake_tree(monkeypatch, labels):
    monkeypatch.setattr(engine, "walk", lambda root, depth, deadline: [(label, 0) for label in labels])
    monkeypatch.setattr(engine, "name_of", lambda node: node)


def test_clean_message_trusted_only_for_its_own_pages(monkeypatch):
    _fake_tree(monkeypatch, ["no unresolved suggestions for pages 19-28"])
    assert engine.feed_state(None, 1.0, page=21) == "clean"
    assert engine.feed_state(None, 1.0, page=40) != "clean"  # the previous stop's message


def test_cards_beat_a_clean_message(monkeypatch):
    _fake_tree(monkeypatch, ["no unresolved suggestions for pages 19-28", "improve your text open suggestion card"])
    assert engine.feed_state(None, 1.0, page=21) == "cards"


def _budget(preset="standard", elapsed=60.0):
    args = engine.parse_args([])
    now = [1000.0]
    pol = rules.RunPolicy(preset=preset, clock=rules.RunClock(lambda: now[0]))
    b = engine.Budget(args, pol)
    b.pages, b.page, b.sweep_first, b.sweep_last, b.sweep_t0 = 109, 56, 1, 109, 0.0
    now[0] += elapsed
    return b


def test_eta_run_adds_the_passes_still_needed():
    b = _budget()
    b.accepted = 12  # this pass has applied things, so two clean passes must follow
    total, further = b.eta_run()
    assert further == 2 and total > b.eta_seconds()


def test_eta_run_has_no_further_passes_on_the_last_allowed_pass():
    b = _budget("quick")
    b.accepted = 12
    assert b.eta_run()[1] == 0


def test_clean_pass_cost_comes_from_measured_clean_stops():
    b = _budget()
    b.accepted = 5
    default_total, _ = b.eta_run()
    b.clean_stops = [20.0, 20.0, 20.0]
    slower_total, _ = b.eta_run()
    assert slower_total > default_total


def test_hud_notes_unclassified_and_no_effect_clicks():
    hud = Hud(lambda: 0, None, True)
    hud.set_progress(
        10, 5, 100, 1, 10.0, None, {"Correctness": 4, "Unclassified": 6}, 4,
        extra={"noeffect": 3, "caret": 94, "passes_done": [7]},
    )
    assert "3" in hud.note_label.text()
    assert hud.tiles["Unclassified"].text() == "6"
    assert hud.where.text() == "Page 94 of 100"
    assert "Applied per pass" in hud.passes_label.text()


def test_hud_shows_whole_run_estimate():
    hud = Hud(lambda: 0, None, True)
    hud.set_progress(10, 5, 100, 1, 10.0, 120.0, {}, 4, extra={"eta_run": (900.0, 2)})
    text = hud.eta_label.text()
    assert "This pass" in text and "Whole run" in text and "2 more passes" in text


def test_heat_accepts_counts_by_type():
    hud = Hud(lambda: 0, None, True)
    hud.set_progress(3, 6, 20, 1, 5.0, None, {}, 4, {6: {"Clarity": 2, "Delivery": 1}}, 1, 20, 5)
    assert hud.heat.cells[1] == (6, {"Clarity": 2, "Delivery": 1})


def test_interface_brings_word_forward_with_the_forced_method(monkeypatch):
    from sweeper import winfocus
    from sweeper.gui import snap

    seen = []
    monkeypatch.setattr(snap, "work_area", lambda: (0, 0, 1920, 1000))
    monkeypatch.setattr(snap, "find_word", lambda document: 77)
    monkeypatch.setattr(snap, "place", lambda *a: True)
    monkeypatch.setattr(winfocus, "force_foreground", lambda hwnd: seen.append(hwnd) or True)
    assert snap.place_word("doc", 600, front=True) is True
    assert seen == [77]


def test_hud_resume_while_held_asks_for_word_not_a_pause():
    hud = Hud(lambda: 0, None, True)
    asked, toggled = [], []
    hud.front_requested.connect(lambda: asked.append(1))
    hud.pause_toggled.connect(toggled.append)
    hud.set_state("needs_user", "Return to Word to continue.")
    assert hud.pause_button.text() == "Resume"
    hud.pause_button.click()
    assert asked == [1] and toggled == []
    hud.set_state("running", "")
    assert hud.pause_button.text() == "Pause"
