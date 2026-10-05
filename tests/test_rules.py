import pytest

from sweeper.rules import (
    CLEAR, LIMIT, REPEATING, STOPPED, PassRecord, RunClock, RunPolicy,
    fingerprint, format_duration, manual_estimate_seconds,
)


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def policy(preset, **kw):
    ft = FakeTime()
    return RunPolicy(preset=preset, clock=RunClock(ft), **kw), ft


def p(i, applied, conclusive=True, text=None):
    return PassRecord(i, applied, conclusive, fingerprint(text) if text is not None else None)


def test_two_clean_passes_end_thorough():
    pol, _ = policy("thorough")
    assert pol.end_of_pass(p(1, 40, text="a")).go_on
    assert pol.end_of_pass(p(2, 3, text="b")).go_on
    assert pol.end_of_pass(p(3, 0)).go_on
    d = pol.end_of_pass(p(4, 0))
    assert not d.go_on and d.outcome.result == CLEAR


def test_thorough_has_no_pass_limit():
    pol, _ = policy("thorough")
    for i in range(1, 30):
        assert pol.end_of_pass(p(i, 1, text=f"t{i}")).go_on


def test_standard_stops_at_four_with_limit_result():
    pol, _ = policy("standard")
    for i in range(1, 4):
        assert pol.end_of_pass(p(i, 5, text=f"t{i}")).go_on
    d = pol.end_of_pass(p(4, 2, text="t4"))
    assert not d.go_on and d.outcome.result == LIMIT
    assert d.outcome.remaining == "may remain"
    assert d.outcome.last_applied == 2


def test_standard_stops_early_on_two_clean():
    pol, _ = policy("standard")
    pol.end_of_pass(p(1, 5, text="x"))
    pol.end_of_pass(p(2, 0))
    d = pol.end_of_pass(p(3, 0))
    assert d.outcome.result == CLEAR and d.outcome.passes == 3


def test_quick_never_claims_clear():
    pol, _ = policy("quick")
    d = pol.end_of_pass(p(1, 0))
    assert not d.go_on and d.outcome.result == LIMIT
    assert "Standard" in d.outcome.reason


def test_inconclusive_pass_is_not_clean_and_resets_count():
    pol, _ = policy("thorough")
    pol.end_of_pass(p(1, 0))
    assert pol.end_of_pass(p(2, 0, conclusive=False)).go_on
    assert pol.consecutive_clean == 0
    assert pol.end_of_pass(p(3, 0)).go_on
    assert pol.end_of_pass(p(4, 0)).outcome.result == CLEAR


def test_repetition_guard_catches_return_to_earlier_text():
    pol, _ = policy("thorough")
    pol.end_of_pass(p(1, 10, text="alpha"))
    pol.end_of_pass(p(2, 4, text="beta"))
    d = pol.end_of_pass(p(3, 4, text="alpha"))
    assert not d.go_on
    assert d.outcome.result == REPEATING
    assert d.outcome.matched_passes == (1, 3)
    assert d.outcome.remaining == "remain"


def test_repetition_ignored_when_pass_applied_nothing():
    pol, _ = policy("thorough")
    pol.end_of_pass(p(1, 3, text="same"))
    assert pol.end_of_pass(p(2, 0, text="same")).go_on


def test_time_limit_counts_running_time_only():
    pol, ft = policy("thorough")
    pol.clock.pause()
    ft.t += 3 * 3600
    pol.clock.resume()
    pol.clock.progress()
    assert pol.interrupt() is None
    ft.t += 2 * 3600 + 1
    pol.clock.progress()
    out = pol.interrupt()
    assert out.result == STOPPED and "2 hour" in out.reason


def test_idle_limit_five_minutes_excludes_pause():
    pol, ft = policy("standard")
    ft.t += 200
    pol.clock.pause()
    ft.t += 1000
    pol.clock.resume()
    ft.t += 90
    assert pol.interrupt() is None  # 290 s of running idle
    ft.t += 20
    out = pol.interrupt()
    assert out.result == STOPPED and "5 minutes" in out.reason


def test_progress_resets_idle():
    pol, ft = policy("standard")
    ft.t += 290
    pol.clock.progress()
    ft.t += 290
    assert pol.interrupt() is None


def test_unknown_preset_rejected():
    with pytest.raises(ValueError):
        RunPolicy(preset="eight")


def test_estimate_and_duration():
    assert manual_estimate_seconds(1284) == 10272
    assert format_duration(10272) == "2 h 51 min"
    assert format_duration(75) == "1 min 15 s"
    assert format_duration(9) == "9 s"


def test_partial_range_flagged():
    pol, _ = policy("standard", whole_document=False)
    pol.end_of_pass(p(1, 0))
    assert pol.end_of_pass(p(2, 0)).outcome.complete_range is False
