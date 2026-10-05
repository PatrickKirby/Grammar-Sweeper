"""Stopping rules and result states, as written in docs/spec.md.

Pure logic with an injectable clock, so every rule is testable without Word,
Grammarly or a screen. The engine reports what happened; this module decides
whether to go on and what to tell the user."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable

TIME_LIMIT_SECONDS = 2 * 60 * 60
IDLE_LIMIT_SECONDS = 5 * 60
CLEAN_PASSES_TO_FINISH = 2

# Preset name to pass limit. None means no limit.
PRESETS: dict[str, int | None] = {"quick": 1, "standard": 4, "thorough": None}

CLEAR = "clear"
LIMIT = "limit"
STOPPED = "stopped"
REPEATING = "repeating"


def fingerprint(text: str) -> str:
    """Whole-document fingerprint used by the repetition guard."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class RunClock:
    """Running time with a pause. Paused time counts toward neither the time
    limit nor the idle limit. Reaching a new page is progress."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._started = now()
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._progress_at = self._started
        self._progress_paused_mark = 0.0

    def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = self._now()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += self._now() - self._paused_at
            self._paused_at = None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def _paused_so_far(self) -> float:
        extra = 0.0 if self._paused_at is None else self._now() - self._paused_at
        return self._paused_total + extra

    def running_seconds(self) -> float:
        return self._now() - self._started - self._paused_so_far()

    def progress(self) -> None:
        self._progress_at = self._now()
        self._progress_paused_mark = self._paused_so_far()

    def idle_seconds(self) -> float:
        waited = self._now() - self._progress_at
        return waited - (self._paused_so_far() - self._progress_paused_mark)


@dataclass
class PassRecord:
    index: int
    applied: int
    conclusive: bool
    text_hash: str | None = None

    @property
    def clean(self) -> bool:
        return self.conclusive and self.applied == 0


@dataclass
class Outcome:
    result: str
    reason: str
    passes: int
    last_applied: int
    preset: str
    matched_passes: tuple[int, int] | None = None
    complete_range: bool = True

    @property
    def remaining(self) -> str:
        """Plain answer to "is anything left", never stronger than the evidence."""
        return "none" if self.result == CLEAR else "may remain" if self.result == LIMIT else "remain"


@dataclass
class Decision:
    go_on: bool
    outcome: Outcome | None = None


@dataclass
class RunPolicy:
    preset: str = "standard"
    time_limit: float = TIME_LIMIT_SECONDS
    idle_limit: float = IDLE_LIMIT_SECONDS
    whole_document: bool = True
    limit_override: int | None = None  # command-line --max-passes
    clock: RunClock = field(default_factory=RunClock)
    passes: list[PassRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.preset not in PRESETS:
            raise ValueError(f"unknown preset {self.preset!r}")

    @property
    def pass_limit(self) -> int | None:
        if self.limit_override:
            return self.limit_override
        return PRESETS[self.preset]

    @property
    def consecutive_clean(self) -> int:
        count = 0
        for record in reversed(self.passes):
            if not record.clean:
                break
            count += 1
        return count

    def _outcome(self, result: str, reason: str, matched=None) -> Outcome:
        last = self.passes[-1].applied if self.passes else 0
        return Outcome(
            result, reason, len(self.passes), last, self.preset, matched, self.whole_document
        )

    def interrupt(self) -> Outcome | None:
        """Checked mid-pass. Returns an outcome when a hard brake applies."""
        if self.clock.running_seconds() > self.time_limit:
            hours = self.time_limit / 3600
            return self._outcome(STOPPED, f"the {hours:g} hour time limit was reached")
        if self.clock.idle_seconds() > self.idle_limit:
            minutes = int(self.idle_limit // 60)
            return self._outcome(STOPPED, f"no progress for {minutes} minutes")
        return None

    def stopped_by_user(self, how: str = "Stop") -> Outcome:
        return self._outcome(STOPPED, f"stopped by the user ({how})")

    def failed(self, reason: str) -> Outcome:
        return self._outcome(STOPPED, reason)

    def end_of_pass(self, record: PassRecord) -> Decision:
        """Record a finished pass and decide whether another is needed."""
        self.passes.append(record)

        if record.applied > 0 and record.text_hash is not None:
            for earlier in self.passes[:-1]:
                if earlier.text_hash == record.text_hash:
                    return Decision(
                        False,
                        self._outcome(
                            REPEATING,
                            "the changes started repeating",
                            (earlier.index, record.index),
                        ),
                    )

        if self.consecutive_clean >= CLEAN_PASSES_TO_FINISH:
            return Decision(False, self._outcome(CLEAR, "two clean passes in a row"))

        brake = self.interrupt()
        if brake is not None:
            return Decision(False, brake)

        limit = self.pass_limit
        if limit is not None and len(self.passes) >= limit:
            if record.applied == 0 and record.conclusive and self.preset == "quick":
                return Decision(
                    False,
                    self._outcome(LIMIT, "one pass found nothing; run Standard to confirm"),
                )
            return Decision(
                False, self._outcome(LIMIT, f"the {self.preset} limit of {limit} pass(es) was reached")
            )
        return Decision(True)


def manual_estimate_seconds(applied: int, seconds_each: int = 8) -> int:
    """What the same work would have taken by hand, at a flat rate per accept."""
    return max(0, applied) * seconds_each


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"
