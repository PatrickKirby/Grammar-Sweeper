"""Engine pieces that need neither Word nor a screen."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as engine
from sweeper.rules import RunClock, RunPolicy


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def budget_at(page, first=1, last=111, elapsed=60.0, sweep_t0=0.0):
    ft = FakeTime()
    args = engine.parse_args([])
    pol = RunPolicy(preset="thorough", clock=RunClock(ft))
    b = engine.Budget(args, pol)
    b.pages, b.page, b.sweep_first, b.sweep_last, b.sweep_t0 = last, page, first, last, sweep_t0
    ft.t += elapsed
    return b


def test_percent_is_page_position_not_accepts():
    b = budget_at(page=11)
    b.accepted = 21
    b.outstanding = 1  # the old formula read this as 95%
    assert round(b.percent()) == 9


def test_percent_none_before_sweep_starts():
    b = budget_at(page=0)
    b.pages = 0
    assert b.percent() is None


def test_eta_from_sweep_pace():
    b = budget_at(page=56, elapsed=300.0)  # 55 of 111 pages in 300 s
    eta = b.eta_seconds()
    assert 280 < eta < 320


def test_eta_withheld_when_too_early():
    assert budget_at(page=2, elapsed=300.0).eta_seconds() is None  # under 5% done
    assert budget_at(page=30, elapsed=10.0).eta_seconds() is None  # under 20 s of data


def test_own_input_is_not_the_person(monkeypatch):
    monkeypatch.setattr(engine, "seconds_since_user_input", lambda: 0.4)
    engine._own_input_at = time.monotonic() - 0.2  # we activated 0.2 s ago
    assert engine.person_used_input() is False


def test_real_input_after_ours_is_the_person(monkeypatch):
    engine._own_input_at = time.monotonic() - 5.0
    monkeypatch.setattr(engine, "seconds_since_user_input", lambda: 0.4)
    assert engine.person_used_input() is True


def test_old_input_is_not_recent(monkeypatch):
    engine._own_input_at = 0.0
    monkeypatch.setattr(engine, "seconds_since_user_input", lambda: 30.0)
    assert engine.person_used_input() is False


def test_audit_writes_lines(tmp_path):
    audit = engine.Audit(tmp_path / "audit.log")
    audit.write("HOLD", kind="other-app")
    audit.close()
    text = (tmp_path / "audit.log").read_text()
    assert "RUN" in text and "HOLD kind='other-app'" in text and "END" in text


def test_new_flags_parse():
    a = engine.parse_args(["--track-changes", "off", "--force-focus"])
    assert a.track_changes == "off" and a.force_focus is True
    assert engine.parse_args([]).track_changes == "on"


def test_percent_uses_words_when_known():
    b = budget_at(page=11)
    b.words_first, b.words_last, b.words_done = 0, 50000, 20000  # few pages, many words
    assert round(b.percent()) == 40


def test_percent_respects_partial_range():
    b = budget_at(page=20, first=10, last=30)
    b.words_first, b.words_last, b.words_done = 4000, 9000, 6500
    assert round(b.percent()) == 50


def test_percent_falls_back_to_pages_without_word_counts():
    b = budget_at(page=11)
    assert b.words_first == -1
    assert round(b.percent()) == 9


def test_executable_names_match_this_machine():
    # Seen live: the Grammarly process is Grammarly.Desktop.exe, Word is WINWORD.EXE.
    for exe in ("grammarly.desktop.exe", "grammar sweeper.exe", "python.exe"):
        assert exe.startswith(("grammarly", "grammar sweeper")) or exe in ("python.exe", "pythonw.exe")
