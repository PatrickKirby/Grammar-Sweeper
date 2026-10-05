"""Rephrase is an accept; tone cards never are."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as ba  # noqa: E402


def test_rephrase_is_an_accept_name_and_ranks_last():
    assert ba.ACCEPT_NAMES[-1] == "rephrase"
    assert ba.matches_label("rephrase", "rephrase")
    assert not ba.matches_label("rephrased text", "rephrase")


def test_the_friendlier_tone_card_is_recognised():
    heading = "Want to sound friendlier? Adjusting tone may improve connections | Friendly | Rephrase"
    assert ba.is_tone_card(heading)


def test_a_rewrite_card_is_not_a_tone_card():
    assert not ba.is_tone_card("Rewrite in active voice | Legitimate Interests: processing is necessary for")


def test_prose_that_says_user_friendly_is_not_a_tone_card():
    assert not ba.is_tone_card("Rewrite in active voice | the user-friendly portal lets staff sign in")


def test_a_tone_row_is_skipped_by_find_row(monkeypatch):
    rows = {
        "want to sound friendlier? adjusting tone may improve connections open suggestion card": "tone",
        "rewrite in active voice the consent open suggestion card": "rewrite",
    }
    monkeypatch.setattr(ba, "walk", lambda root, depth, deadline: iter([(label, 0) for label in rows]))
    monkeypatch.setattr(ba, "name_of", lambda node: node)
    monkeypatch.setattr(ba, "type_of", lambda node: ba.auto.ControlType.ButtonControl)
    monkeypatch.setattr(ba, "is_clickable_rect", lambda node: True)
    node, label = ba.find_row(None, 1.0)
    assert rows[node] == "rewrite"
