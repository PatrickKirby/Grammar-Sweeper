"""Thread-safe handle between the engine thread and an interface.

The engine calls in (emit, hold, wait_while_blocked); the interface calls
request_stop, request_pause and request_resume. Nothing here touches Word."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .rules import RunClock

RUNNING = "running"
RECONNECTING = "reconnecting"
NEEDS_USER = "needs_user"
PAUSED = "paused"


class RunControl:
    def __init__(
        self,
        clock: RunClock,
        on_event: Callable[..., None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clock = clock
        self.on_event = on_event
        self._sleep = sleep
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.stop_reason = "stopped by the user"
        self.state = RUNNING
        self.message = ""
        self._held = False

    # Interface side ------------------------------------------------------

    def request_stop(self, how: str = "Stop") -> None:
        self.stop_reason = f"stopped by the user ({how})"
        self._stop.set()

    def request_pause(self) -> None:
        self._pause.set()
        self.set_state(PAUSED, "Paused")

    def request_resume(self) -> None:
        self._pause.clear()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    @property
    def user_paused(self) -> bool:
        return self._pause.is_set()

    # Engine side ---------------------------------------------------------

    def emit(self, kind: str, **data) -> None:
        if self.on_event is not None:
            try:
                self.on_event(kind, **data)
            except Exception:  # noqa: BLE001 - a broken listener must not stop a run
                pass

    def set_state(self, state: str, message: str = "") -> None:
        if state != self.state or message != self.message:
            self.state = state
            self.message = message
            self.emit("state", state=state, message=message)

    def wait_while_blocked(self, tick: float = 0.25) -> bool:
        """Block while the user has paused. The clock stops for the duration.
        True when it actually waited, so the caller can recover on resume."""
        if not self._pause.is_set() or self._stop.is_set():
            return False
        self.clock.pause()
        try:
            while self._pause.is_set() and not self._stop.is_set():
                self._sleep(tick)
        finally:
            self.clock.resume()
            if not self._stop.is_set():
                self.set_state(RUNNING)
        return True

    def hold(
        self,
        resolved: Callable[[], bool],
        message: str,
        state: str = NEEDS_USER,
        tick: float = 0.5,
    ) -> bool:
        """Pause the run until `resolved()` is true. Paused time is not counted.
        Returns False if the user stopped the run instead."""
        self.clock.pause()
        self.set_state(state, message)
        try:
            while not self._stop.is_set():
                if resolved():
                    return True
                self._sleep(tick)
            return False
        finally:
            self.clock.resume()
            if not self._stop.is_set():
                self.set_state(RUNNING)
