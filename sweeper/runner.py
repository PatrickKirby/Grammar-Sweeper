"""Bridge between the interface and the engine: build arguments, run on a
worker thread, report events and the final summary."""

from __future__ import annotations

import threading
import time

import bulk_accept as engine

from .control import RunControl
from .rules import RunClock
from .settings import log_dir


def build_args(
    preset: str,
    document: str | None,
    start_page: int = 1,
    end_page: int = 0,
    track_changes: str = "on",
    force_focus: bool = False,
):
    """Reuse the command line parser so the interface and the CLI share defaults."""
    argv = [
        "--preset", preset,
        "--track-changes", track_changes,
        "--log", str(log_dir() / "grammar-sweeper.log"),
    ]
    if force_focus:
        argv.append("--force-focus")
    if document:
        argv += ["--document", document]
    if start_page > 1:
        argv += ["--start-page", str(start_page)]
    if end_page > 0:
        argv += ["--end-page", str(end_page)]
    return engine.parse_args(argv)


LARGE_PAGES = 300  # beyond this a run takes hours; say so before it starts


def online_note(path: str) -> str | None:
    """A document opened from SharePoint or OneDrive has a web address, not a file path. No
    backup copy can be made from that, and Word may be unable to upload a save."""
    if path.lower().startswith(("http://", "https://")):
        return (
            "is stored online, so no backup copy can be made from here and Word may block saving it. "
            "Edits stay in the open window until you use Save a Copy."
        )
    return None


def preflight() -> dict:
    """What the Ready screen needs: open documents, elevation, panel presence."""
    result = {"paths": [], "elevated": engine.is_elevated(), "panel": None, "warnings": {}, "pages": {}}
    try:
        found = engine.WordSession.documents_in_rot()
        result["paths"] = [p for p, _ in found]
        for path, doc in found:
            notes = []
            online = online_note(path)
            if online:
                notes.append(online)
            try:
                if not doc.Saved:
                    notes.append("has unsaved changes. Save first so the backup matches what you see.")
                if doc.ReadOnly:
                    notes.append("is read-only. Accepted suggestions cannot be saved to it.")
                pages = int(doc.ComputeStatistics(2))
                result["pages"][path] = pages
                if pages > LARGE_PAGES:
                    notes.append(f"is {pages} pages. Expect a long run.")
            except Exception:  # noqa: BLE001 - a check that fails says nothing
                pass
            if notes:
                result["warnings"][path] = notes
    except Exception:  # noqa: BLE001 - COM can fail in many ways; the screen says "none found"
        pass
    try:
        with engine.auto.UIAutomationInitializerInThread():
            window = engine.find_word_window(None)
            result["panel"] = engine.find_pane(window, 6, 3.0) is not None
    except Exception:  # noqa: BLE001
        result["panel"] = None
    return result


def grammarly_ready(document: str | None, seconds: float = 20.0) -> bool:
    """True once Grammarly's assistant is found and showing its feed. The panel only
    exists while Word is in front, so the caller brings Word forward first."""
    deadline = time.monotonic() + seconds
    try:
        with engine.auto.UIAutomationInitializerInThread():
            window = engine.find_word_window(document)
            while time.monotonic() < deadline:
                pane = engine.find_pane(window, 6, 1.5)
                if pane is not None and engine.pane_is_open(pane, 2.0):
                    return True
                time.sleep(0.5)
    except (Exception, SystemExit):  # noqa: BLE001 - find_word_window exits when Word has no such window
        return False
    return False


class Job:
    """One run on a background thread. `on_event(kind, **data)` is called from
    that thread; the interface must hand it to its own thread."""

    def __init__(self, args, on_event, on_done) -> None:
        self.args = args
        self.control = RunControl(RunClock(), on_event)
        self._on_done = on_done
        self._thread = threading.Thread(target=self._run, name="sweep", daemon=True)
        self.summary = None
        self.crashed: str | None = None

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            self.summary = engine.execute(self.args, self.control)
        except Exception as exc:  # noqa: BLE001 - never a raw traceback on screen
            self.crashed = f"{type(exc).__name__}: {exc}"
        finally:
            self._on_done(self)
