"""The independent check on the applied counter."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as ba  # noqa: E402


class Text:
    def __init__(self, after):
        self.after = after

    def text(self):
        return self.after


class Budget:
    measured_changed = 0
    undercount = 0


def test_unchanged_text_counts_nothing():
    assert ba.changed_paragraphs("a\rb\rc", "a\rb\rc") == 0


def test_one_edit_is_one_paragraph():
    assert ba.changed_paragraphs("a\rb\rc", "a\rB\rc") == 1


def test_two_edits_in_one_paragraph_count_once():
    assert ba.changed_paragraphs("a\rtest and test\rc", "a\rtests and tests\rc") == 1


def test_an_insertion_counts():
    assert ba.changed_paragraphs("a\rc", "a\rb\rc") == 1


def test_watch_flags_a_counter_that_is_behind(monkeypatch):
    monkeypatch.setattr(ba, "AUDIT", type("A", (), {"write": lambda self, *a, **k: None})())
    budget = Budget()
    ba.watch_count(Text("a\rB\rC\rd"), budget, "a\rb\rc\rd", 5, 1, 0, None)
    assert budget.measured_changed == 2
    assert budget.undercount == 1


def test_watch_is_quiet_when_the_counter_keeps_up(monkeypatch):
    monkeypatch.setattr(ba, "AUDIT", type("A", (), {"write": lambda self, *a, **k: None})())
    budget = Budget()
    ba.watch_count(Text("a\rB\rc"), budget, "a\rb\rc", 5, 1, 0, None)
    assert budget.undercount == 0
