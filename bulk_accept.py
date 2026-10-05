"""Bulk-accept Grammarly suggestions for a document open in Microsoft Word.

Grammarly ships no public API for applying suggestions and no universal
"accept everything" control, so this drives the review panel's own UI. The
panel is a top-level window named "Grammarly" owned by Grammarly.Desktop; it is
not a child of Word's window tree. The loop locates the primary accept button
on the suggestion card, invokes it, waits for the panel to render the next
card, and repeats, sweeping the document page by page.

Two engines:

  uia    UI Automation. Finds the button by accessible name inside the panel.
         Preferred: it follows the button when the card changes height.
  click  Records one button position relative to the Word window, then clicks
         that offset repeatedly. Fallback for when the panel exposes no
         accessibility tree. It has no document sweep and cannot read card types.

Safety, because a hundred accepted rewrites is not something you want to undo by
hand: the document is copied to a timestamped backup before the first click.
Track Changes is switched on too, but Grammarly's edits are not reliably
recorded as revisions, so the backup is the undo path, and progress is measured
by document length. Press ESC at any time to stop the loop.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import json
import re
import shutil
import sys
import threading
import time
from collections import Counter
from pathlib import Path

try:
    import uiautomation as auto
except ImportError:  # pragma: no cover - dependency guard
    sys.exit("Missing dependency. Run: pip install uiautomation pywin32")

try:
    import pythoncom
    import pywintypes
    import win32com.client
except ImportError:  # pragma: no cover - dependency guard
    sys.exit("Missing dependency. Run: pip install uiautomation pywin32")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweeper.analysis import enrich  # noqa: E402
from sweeper.changes import ChangeLog, build_report, locate_change, write_exports  # noqa: E402
from sweeper import winfocus  # noqa: E402
from sweeper.control import NEEDS_USER, RECONNECTING, RunControl  # noqa: E402
from sweeper.rules import (  # noqa: E402
    PassRecord, RunPolicy, Outcome, fingerprint,
)

# COM refuses a call while Word sits in a modal dialog or is busy.
COM_BUSY = {-2147418111, -2147417846}  # RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER


WORD_WINDOW_CLASS = "OpusApp"

# Accessible names the add-in has used for the primary accept control on a
# suggestion card. Matched case-insensitively, most specific first so that
# "use this version" wins over a bare "accept". The card wording varies by
# suggestion category: correctness cards tend to say Accept, rewrite cards say
# Use this version, and there are certainly others neither documented nor seen.
# Unknown wording is handled structurally instead, see find_accept_by_card().
ACCEPT_NAMES = [
    "accept and open next suggestion",
    "use this version",
    "accept suggestion",
    "apply suggestion",
    "use this suggestion",
    "use version",
    "accept",
    "apply",
    "use this",
    # Rewrite cards, such as "rewrite in active voice", offer Rephrase as their one button. It is
    # an accept, last in rank so any plainer wording on a card wins. Tone cards also carry it
    # and are never accepted: see is_tone_card.
    "rephrase",
]

# The review panel is a top-level Tauri window named simply "Grammarly". It is
# not a child of the Word window and not the Grammarly.Desktop widget, which is
# a separate always-collapsed window carrying AutomationId
# GrammarlyAssistantWindow and only a handful of nodes. Distinguishing them
# matters: rooting the search at the review panel is what keeps Word's own
# Review ribbon, which has its own Accept controls, permanently out of scope.
PANE_WINDOW_NAME = "grammarly"
PANE_AUTOMATION_ID = "GrammarlyAssistantWindow"  # the widget, deliberately not used

# The panel only renders its feed while Word is the foreground window. Out of
# focus it falls back to "start editing text to get help from proofreader".
IDLE_MARKER = "start editing text"

# Collapsed feed entries carry this at the end of their accessible name. The
# card's accept control does not exist until the row has been opened.
ROW_MARKER = "open suggestion card"
OPEN_ASSISTANT = "open grammarly assistant"

# Controls that must never be clicked even if a name match is close, and that
# can never be learned as an accept label by the structural strategy.
BLOCKED_NAMES = {
    "dismiss",
    "ignore",
    "ignore all",
    "delete",
    "close",
    "reject",
    "cancel",
    "undo",
    "show less",
    "show more",
    "see more",
    "learn more",
    "check for plagiarism and ai text",
    "more",
    "settings",
    "correctness",
    "clarity",
    "engagement",
    "delivery",
    "all suggestions",
}

# Word's own Review ribbon, which is full of controls called Accept. Searching
# the whole window once matched "Accept and Move to Next" and applied two of
# Word's tracked changes instead of a Grammarly suggestion. The real defence is
# scoping the search to the Grammarly panel; this list is the second line of it.
BLOCKED_SUBSTRINGS = (
    "dismiss",
    # "accept and open previous suggestion" exists alongside the forward form.
    # Matching it walks the feed backwards and the loop stops making progress.
    "previous suggestion",
    "move to next",
    "all changes",
    "stop tracking",
    "track changes",
    "next change",
    "previous change",
    "reviewing pane",
    "new comment",
    "compare",
)

# The control every suggestion card pairs with its primary button. Used as the
# anchor for structural discovery when the primary button's wording is unknown.
DISMISS_NAMES = ("dismiss", "ignore")

# Tone cards ("Want to sound friendlier?") change the voice of the document and are never
# accepted. Matched against the card's heading only, never its quoted prose, so a document that
# says "user-friendly" is not skipped. "friendlier" is the marker, not "friendly".
TONE_MARKERS = ("want to sound", "friendlier", "adjusting tone", "tone may improve")


def is_tone_card(text: str) -> bool:
    heading = text.lower()[:160]
    return any(marker in heading for marker in TONE_MARKERS)

# Card headers, as the pane writes them, mapped to the four categories its tabs
# use. Matched as a prefix against the text nodes inside the card being
# accepted, so the running tally can report what kind of thing it just applied.
CATEGORY_HINTS = [
    # The card names its own category first, as "correctness · add a period".
    ("correctness", "Correctness"),
    ("clarity", "Clarity"),
    ("engagement", "Engagement"),
    ("delivery", "Delivery"),
    ("add a period", "Correctness"),
    ("insert period", "Correctness"),
    ("check wording", "Clarity"),
    ("rephrase", "Clarity"),
    ("correct your spelling", "Correctness"),
    ("correct your grammar", "Correctness"),
    ("correct your punctuation", "Correctness"),
    ("correct the", "Correctness"),
    ("correct ", "Correctness"),
    ("add a missing", "Correctness"),
    ("remove the", "Correctness"),
    ("improve your text", "Clarity"),
    ("rewrite for clarity", "Clarity"),
    ("make it concise", "Clarity"),
    ("shorten", "Clarity"),
    ("engagement", "Engagement"),
    ("use a more expressive", "Engagement"),
    ("vary your", "Engagement"),
    ("delivery", "Delivery"),
    ("sound more confident", "Delivery"),
    ("adjust the tone", "Delivery"),
]

CONFIG_PATH = Path(__file__).with_name("click_target.json")
LEARNED_PATH = Path(__file__).with_name("learned_names.json")
CHECKPOINT_PATH = Path(__file__).with_name("checkpoint.json")
DEFAULT_LOG_DIR = Path(__file__).with_name("logs")
VK_ESCAPE = 0x1B

# SetThreadExecutionState flags. ES_CONTINUOUS makes the state stick until
# cleared instead of applying to one call; ES_SYSTEM_REQUIRED blocks sleep,
# ES_DISPLAY_REQUIRED blocks the display turning off. Neither blocks an
# idle-triggered screen lock, which is a separate Windows policy and breaks
# foreground automation the same way sleep would.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def now() -> dt.datetime:
    """Local time with the UTC offset attached. No naive datetime crosses an IO
    boundary here: the run log has to stay readable against the UTC timestamps
    Word writes into revision metadata."""
    return dt.datetime.now().astimezone()


SWALLOWED: Counter = Counter()  # errors caught and carried past, by kind


def swallow(kind: str, exc: BaseException) -> None:
    """Record an error that is caught on purpose. The first of each kind goes to
    the audit log in full; the rest are counted and totalled at the end of the run."""
    SWALLOWED[kind] += 1
    if SWALLOWED[kind] == 1:
        try:
            AUDIT.write("SWALLOWED", kind=kind, error=f"{type(exc).__name__}: {str(exc)[:160]}")
        except NameError:  # no audit log yet
            pass


def log(message: str, handle=None) -> None:
    """One JSON object per line in the file, so the log can be queried; the
    console keeps the readable form."""
    stamp = now().strftime("%H:%M:%S%z")
    print(f"[{stamp}] {message}", flush=True)
    if handle:
        text = message.strip()
        level = "warning" if text.startswith("WARNING") else "error" if text.startswith(("CRASHED", "Refusing")) else "info"
        handle.write(json.dumps({"t": stamp, "level": level, "msg": message.rstrip()}, ensure_ascii=False) + "\n")
        handle.flush()


def is_elevated() -> bool:
    """Whether this process is running as administrator.

    It matters twice. The Running Object Table is partitioned by integrity
    level, so an elevated process cannot see a normal Word's documents and COM
    binding fails with MK_E_UNAVAILABLE. UI Automation is partitioned the same
    way, so an elevated process also cannot drive a normal Word's windows."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - shell32 unavailable
        return False


def escape_pressed() -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def prevent_sleep() -> None:
    """Block system sleep and display-off for the life of this process.
    Does not block an idle screen lock; that is a separate Windows policy."""
    ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    )


def allow_sleep() -> None:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def write_checkpoint(budget: "Budget", session: "WordSession", where: str) -> None:
    """Best-effort progress snapshot so a crash's blast radius is known without
    reconstructing it from console scrollback."""
    payload = {
        "accepted": budget.accepted,
        "where": where,
        "char_count": session.char_count() if session.available else -1,
        "by_type": dict(budget.by_type),
        "timestamp": now().isoformat(timespec="seconds"),
    }
    try:
        tmp = CHECKPOINT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(CHECKPOINT_PATH)
    except OSError:
        pass  # a missed checkpoint is not worth stopping the run over


# ---------------------------------------------------------------------------
# Word COM
# ---------------------------------------------------------------------------


class WordSession:
    """Thin COM wrapper. Every call is optional: the loop still runs if Word's
    automation interface is unavailable, it just loses progress reporting."""

    def __init__(self, wanted: str | None = None) -> None:
        self.app = None
        self.doc = None
        self.attach(wanted)

    def attach(self, wanted: str | None = None) -> None:
        """Bind to the Word document, not merely to a Word process.

        GetActiveObject returns whichever Word instance registered itself first,
        and a Word process holding no documents is a normal thing to find: the
        first attempt on this machine bound to an empty instance while the
        document sat in a second one. So the Running Object Table is enumerated
        for a document moniker instead, which finds the file whoever has it."""
        candidates = self.documents_in_rot()
        if candidates:
            chosen = None
            if wanted:
                for path, doc in candidates:
                    if wanted.lower() in path.lower():
                        chosen = (path, doc)
                        break
                if chosen is None:
                    log(f"WARNING: no open document matches '{wanted}'. Using the first one found.")
            if chosen is None:
                chosen = candidates[0]
            path, self.doc = chosen
            try:
                self.app = self.doc.Application
            except Exception as exc:  # noqa: BLE001
                log(f"WARNING: document found but its Application is unreachable ({exc}).")
                self.doc = None
                return
            if len(candidates) > 1:
                others = ", ".join(Path(p).name for p, _ in candidates if p != path)
                log(f"NOTE: {len(candidates)} documents open. Working on {Path(path).name}; ignoring {others}.")
                log("      Use --document <fragment of filename> to pick a different one.")
            log(f"Attached to {path}")
            return

        # Nothing in the ROT. Fall back to the old path so a document that has
        # never been saved is still reachable, then say plainly if it is not.
        try:
            self.app = win32com.client.GetActiveObject("Word.Application")
            self.doc = self.app.ActiveDocument
            log("Attached to the active document via the running Word instance.")
        except Exception as exc:  # noqa: BLE001 - COM raises broadly
            self.app = None
            self.doc = None
            log(f"WARNING: could not attach to a Word document ({exc}).")
            log("         No backup, no Track Changes, no revision counting.")

    @staticmethod
    def documents_in_rot() -> list[tuple[str, object]]:
        """Every Word document currently registered in the Running Object Table,
        across every Word process."""
        found: list[tuple[str, object]] = []
        try:
            pythoncom.CoInitialize()
            table = pythoncom.GetRunningObjectTable()
            context = pythoncom.CreateBindCtx(0)
        except Exception as exc:  # noqa: BLE001 - COM unavailable entirely
            log(f"WARNING: could not read the Running Object Table ({exc}).")
            return found

        for moniker in table:
            try:
                display = moniker.GetDisplayName(context, None)
            except Exception:  # noqa: BLE001 - moniker refuses to name itself
                continue
            if not display.lower().endswith((".docx", ".docm", ".doc", ".dotx")):
                continue
            try:
                raw = table.GetObject(moniker)
                doc = win32com.client.Dispatch(raw.QueryInterface(pythoncom.IID_IDispatch))
                identity = str(doc.FullName)  # proves it is a document and gives the dedupe key
            except Exception as exc:  # noqa: BLE001 - not a document, or gone
                log(f"NOTE: skipped a running object that would not open as a document ({exc}).")
                continue
            found.append((display, identity, doc))

        # One document can register several monikers, including Word's own
        # temporary-file forms. Collapse them by the document's real path, and
        # keep the moniker that names a file actually on disk.
        best: dict[str, tuple[str, object]] = {}
        for display, identity, doc in found:
            readable = Path(display).exists()
            if identity not in best or (readable and not Path(best[identity][0]).exists()):
                best[identity] = (display if readable else identity, doc)
        return [(display, doc) for display, doc in best.values()]

    @property
    def available(self) -> bool:
        return self.doc is not None

    def full_name(self) -> str | None:
        try:
            return self.doc.FullName
        except Exception:  # noqa: BLE001
            return None

    def health(self) -> str:
        """ok, busy (Word is in a dialog), or gone (document or Word closed)."""
        try:
            self.doc.FullName
            return "ok"
        except pywintypes.com_error as exc:
            return "busy" if exc.hresult in COM_BUSY else "gone"
        except Exception:  # noqa: BLE001
            return "gone"

    def active_document_name(self) -> str | None:
        try:
            return str(self.app.ActiveDocument.FullName)
        except Exception:  # noqa: BLE001
            return None

    def text(self) -> str | None:
        """Whole body text, for the repetition guard. Cost is unmeasured."""
        try:
            return str(self.doc.Content.Text)
        except Exception:  # noqa: BLE001
            return None

    def backup(self) -> Path | None:
        path_text = self.full_name()
        if not path_text:
            return None
        source = Path(path_text)
        if not source.exists():
            log(f"WARNING: document path not readable on disk: {source}")
            return None
        stamp = now().strftime("%Y%m%d-%H%M%S")
        target = source.with_name(f"{source.stem}.backup-{stamp}{source.suffix}")
        try:
            self.doc.Save()
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: could not save before backup ({exc}).")
        shutil.copy2(source, target)
        return target

    def save_now(self, handle=None) -> bool:
        """Best-effort periodic save, so a crash's undo path is the last save,
        not the run-start backup alone. Never fatal: a read-only prompt or a
        transient lock should not end an otherwise-healthy run."""
        try:
            self.doc.Save()
            return True
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: periodic save failed ({exc}).", handle)
            return False

    def set_track_changes(self, wanted: bool) -> bool:
        try:
            self.doc.TrackRevisions = wanted
            return bool(self.doc.TrackRevisions) == wanted
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: could not set Track Changes ({exc}).")
            return False

    def hide_markup(self) -> bool:
        """Show the document with no markup. Grammarly misreads a page that is
        full of tracked changes, so the view is cleared for the run and put back
        afterwards. Only the view changes; Track Changes itself is untouched."""
        try:
            view = self.app.ActiveWindow.View
            self._saved_view = (int(view.RevisionsFilter.Markup), bool(view.ShowRevisionsAndComments))
            view.RevisionsFilter.Markup = 0  # wdRevisionsMarkupNone
            view.ShowRevisionsAndComments = False
            return True
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: could not hide markup ({exc}).")
            return False

    def restore_markup(self) -> None:
        saved = getattr(self, "_saved_view", None)
        if saved is None:
            return
        try:
            view = self.app.ActiveWindow.View
            view.RevisionsFilter.Markup = saved[0]
            view.ShowRevisionsAndComments = saved[1]
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: could not restore the markup view ({exc}).")
        self._saved_view = None

    def window_span(self, page: int, behind: int = 3, ahead: int = 10) -> tuple[int, int] | None:
        """Character span around a page stop, wide enough to hold every card
        Grammarly offers there (it reviews about ten pages at a time). Reading
        this span costs a fraction of reading the whole document."""
        try:
            start = int(self.doc.GoTo(1, 1, max(1, page - behind)).Start)
            last = int(self.doc.ComputeStatistics(2))
            end = int(self.doc.Content.End) if page + ahead > last else int(self.doc.GoTo(1, 1, page + ahead).Start)
            return (start, max(start, end))
        except Exception:  # noqa: BLE001
            return None

    def range_text(self, start: int, end: int) -> str | None:
        try:
            return str(self.doc.Range(start, end).Text)
        except Exception:  # noqa: BLE001
            return None

    def heading_path(self, index: int) -> list[str]:
        """Headings above a position, outermost first, such as ['2. Plan', '2.5 Cutover']."""
        path: list[str] = []
        try:
            here = self.doc.Range(index, index)
            level_seen = 10
            for _ in range(6):
                found = here.GoTo(11, 3)  # wdGoToHeading, wdGoToPrevious
                start = int(found.Start)
                para = found.Paragraphs(1)
                level = int(para.OutlineLevel)
                if level < level_seen:
                    path.insert(0, str(para.Range.Text).strip()[:80])
                    level_seen = level
                if level <= 1 or start <= 0:
                    break
                here = self.doc.Range(start, start)
        except Exception as exc:  # noqa: BLE001 - no headings, or a protected range
            swallow("heading-path", exc)
        return path

    def custom_property(self, name: str):
        """A custom document property a generator may have set, such as GS_Draft."""
        try:
            return self.doc.CustomDocumentProperties(name).Value
        except Exception:  # noqa: BLE001 - absent is the normal case
            return None

    def caret_page(self) -> int:
        """Page the insertion point is on now, which is what Word's status bar shows."""
        try:
            return int(self.app.Selection.Information(3))
        except Exception:  # noqa: BLE001
            return -1

    def page_of(self, index: int) -> int:
        """Page that holds a character position, -1 when Word will not say."""
        try:
            return int(self.doc.Range(index, index).Information(3))  # wdActiveEndPageNumber
        except Exception:  # noqa: BLE001
            return -1

    def revision_count(self) -> int:
        try:
            return int(self.doc.Revisions.Count)
        except Exception:  # noqa: BLE001
            return -1

    def char_count(self) -> int:
        """Length of the document body, as the end position of its range.

        Measured at 5ms against Characters.Count at 1505ms on this document,
        and it answers the same question: did anything actually change.

        The honest progress signal. Grammarly's add-in applies edits that Word
        does not always record as revisions even with TrackRevisions on, so a
        revision count can sit at zero through a run that is changing the text.
        A character count moves whenever anything is actually applied."""
        try:
            return int(self.doc.Content.End)
        except Exception:  # noqa: BLE001 - document closed
            return -1

    def words_total(self) -> int:
        """wdStatisticWords for the body. Progress is measured in words, since
        pages hold very different amounts of text."""
        try:
            return int(self.doc.ComputeStatistics(0))
        except Exception:  # noqa: BLE001
            return -1

    def words_before_page(self, page: int) -> int:
        """Words in the document ahead of the start of `page`. Cost per call is
        unmeasured; it runs once per page stop, never per accept."""
        try:
            start = int(self.doc.GoTo(1, 1, page).Start)
            if start <= 0:
                return 0
            return int(self.doc.Range(0, start).ComputeStatistics(0))
        except Exception:  # noqa: BLE001
            return -1

    def click_into_page(self, page: int, skip: int = 0) -> bool:
        """Click into the text at the top of `page`, as a person would.

        Grammarly re-reads the document on a real click, and does not always on
        a caret moved through COM. Seen live: pages judged empty here had five
        or more suggestions once the person clicked into the document."""
        try:
            target = self.doc.GoTo(1, 1, page)
            target.Collapse(1)
            # Seen live: Grammarly often ignored a click inside a table, which is how many
            # pages open. Prefer the first ordinary paragraph that is on screen.
            target = self._visible_prose(page, skip) or target
            left, top, width, height = self.app.ActiveWindow.GetPoint(0, 0, 0, 0, target)
            if width <= 0 and height <= 0 and left <= 0 and top <= 0:
                return False
            note_own_input()
            auto.Click(int(left) + 4, int(top) + max(2, int(height) // 2), waitTime=0)
            note_own_input()
            return True
        except Exception as exc:  # noqa: BLE001 - range off screen or window busy
            log(f"WARNING: could not click into page {page} ({exc}).")
            return False

    def caret_context(self) -> str:
        """Where the caret is, in words, for the audit log when Grammarly reports no text."""
        try:
            selection = self.app.Selection
            story = int(selection.StoryType)  # 1 is the main text
            if story != 1:
                return f"outside the main text (story {story}), such as a header, footer or note"
            if selection.Information(12):  # wdWithInTable
                return "inside a table"
            para = selection.Range.Paragraphs(1).Range
            if int(para.End) - int(para.Start) <= 1:
                return "on an empty paragraph"
            return "in body text"
        except Exception as exc:  # noqa: BLE001 - Word busy or a dialog is open
            return f"unreadable ({type(exc).__name__}), Word may have a dialog open"

    def nudge(self) -> bool:
        """Right then Left: moves nothing, but gives Word and Grammarly a real caret event.
        Sent only while Word is the foreground window, so the keys cannot reach Grammarly."""
        try:
            if ctypes.windll.user32.GetForegroundWindow() != int(self.app.ActiveWindow.Hwnd):
                return False
            note_own_input()
            auto.SendKeys("{Right}{Left}", waitTime=0.05)
            note_own_input()
            return True
        except Exception:  # noqa: BLE001 - window busy; the next stop tries again
            return False

    def _visible_prose(self, page: int, skip: int = 0):
        """Start of the first non-table paragraph on `page` that has a screen position, or None."""
        try:
            start = int(self.doc.GoTo(1, 1, page).Start)
            end = int(self.doc.GoTo(1, 1, page + 1).Start)
            for number, para in enumerate(self.doc.Range(start, end).Paragraphs):
                if number > 40:
                    break
                found = para.Range
                if found.Information(12) or len(found.Text.strip()) < 20:  # wdWithInTable
                    continue
                found.Collapse(1)
                try:
                    left, top, width, height = self.app.ActiveWindow.GetPoint(0, 0, 0, 0, found)
                except Exception:  # noqa: BLE001 - off screen
                    continue
                if height > 0 and left > 0:
                    if skip > 0:
                        skip -= 1  # a later paragraph, when the first one did not make Grammarly read
                        continue
                    return found
        except Exception:  # noqa: BLE001 - range gone after a reflow; the page top is used
            return None
        return None

    def page_count(self) -> int:
        """wdStatisticPages. Recomputed per pass: applied edits reflow the
        document, so a page count cached at the start goes wrong by the end."""
        try:
            return int(self.doc.ComputeStatistics(2))
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: could not read page count ({exc}).")
            return -1

    def scroll_to_page(self, page: int) -> bool:
        """Bring a page into view without moving the insertion point.

        doc.GoTo returns a Range and leaves the selection alone, so the Grammarly
        pane re-scopes its feed to the new region while the cursor stays put.
        Moving the selection instead would fight the add-in as it applies edits."""
        try:
            target = self.doc.GoTo(1, 1, page)  # wdGoToPage, wdGoToAbsolute
            # The caret has to move, not just the viewport. Grammarly proofreads
            # around the insertion point, so a scrolled-but-unselected page
            # leaves the panel reporting "No text available" and the sweep walks
            # the rest of the document finding nothing.
            # Collapse before selecting. Selecting the whole page range hands
            # Grammarly a page-sized selection, and accepts then register in the
            # panel while the document stays unchanged: four applied, nought
            # revisions recorded.
            target.Collapse(1)  # wdCollapseStart
            target.Select()
            self.app.ActiveWindow.ScrollIntoView(target, True)
            return True
        except Exception as exc:  # noqa: BLE001 - page gone after reflow
            log(f"WARNING: could not scroll to page {page} ({exc}).")
            return False


# ---------------------------------------------------------------------------
# UI Automation
# ---------------------------------------------------------------------------


def find_word_window(title_fragment: str | None) -> auto.WindowControl:
    window = auto.WindowControl(searchDepth=1, ClassName=WORD_WINDOW_CLASS)
    if title_fragment:
        window = auto.WindowControl(
            searchDepth=1,
            ClassName=WORD_WINDOW_CLASS,
            SubName=title_fragment,
        )
    if not window.Exists(maxSearchSeconds=5):
        sys.exit("Word window not found. Open the document with the Grammarly pane showing.")
    return window


def walk(root: auto.Control, max_depth: int, deadline: float):
    """Depth-first walk with a depth cap and a wall-clock budget. The panel
    sits deep inside Word's window tree and an unbounded walk on a long document
    is slow enough to outlast the pane's own re-render."""
    stack = [(root, 0)]
    while stack:
        if time.monotonic() > deadline:
            return
        node, depth = stack.pop()
        yield node, depth
        if depth >= max_depth:
            continue
        try:
            children = node.GetChildren()
        except Exception:  # noqa: BLE001 - stale element during re-render
            continue
        for child in reversed(children):
            stack.append((child, depth + 1))


def find_pane(window: auto.Control, max_depth: int, budget_seconds: float, handle=None):
    """Locate the Grammarly assistant window and return it as the search root.

    This is the whole safety story for matching. Word's Review ribbon carries
    controls named Accept and Accept and Move to Next, and a search rooted at
    the Word window once invoked one of those instead of a suggestion card.
    Rooting every search at the assistant window instead means a control named
    Accept can only ever belong to Grammarly.

    The assistant is a top-level window of Grammarly.Desktop, not a child of
    Word, so it is found from the desktop root. Its Name alternates between a
    live status string and blank, which leaves the AutomationId as the only
    stable handle."""
    del window, max_depth  # the pane is not inside Word's tree
    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        try:
            children = auto.GetRootControl().GetChildren()
        except Exception as exc:  # noqa: BLE001 - desktop enumeration raced a close
            log(f"  could not enumerate top-level windows ({exc}).", handle)
            children = []
        for child in children:
            try:
                if (child.Name or "").strip().lower() != PANE_WINDOW_NAME:
                    continue
                rect = child.BoundingRectangle
                if rect.width() < 200 or rect.height() < 250:
                    continue  # the desktop widget, not the review panel
            except Exception:  # noqa: BLE001 - window closed mid-enumeration
                continue
            if handle is not None:
                # Silent when called from a polling loop, which would otherwise
                # print this once per second for the length of the wait.
                log(f"Assistant window found at ({rect.left},{rect.top}) {rect.width()}x{rect.height()}", handle)
            return child
        time.sleep(0.4)
    return None


def pane_is_open(pane: auto.Control, budget_seconds: float) -> bool:
    """Whether the suggestion feed is actually showing.

    The window name is checked first because it is free and definitive: expanded
    it reads like 'Assistant card opened / 20 suggestions', collapsed it is
    blank. The tree walk is the fallback, and it is not cheap, because the feed
    rows sit around twenty levels deep inside the WebView2. The subtree also
    empties entirely when the assistant is not being displayed, which is why a
    walk can return instantly having seen nothing."""
    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        try:
            name = (pane.Name or "").lower()
            if "suggestion" in name or "card opened" in name:
                return True
        except Exception:  # noqa: BLE001 - window went away
            return False

        for node, _ in walk(pane, 32, deadline):
            label = name_of(node)
            if not label:
                continue
            if ROW_MARKER in label or label in DISMISS_NAMES:
                return True
            if any(candidate in label for candidate in ACCEPT_NAMES):
                return True
        # An empty subtree means the panel has torn its content down, which it
        # does whenever Word is not foreground. The walk returns instantly in
        # that state, so without this pause the budget would be spent in
        # microseconds and a panel that is merely slow would read as closed.
        time.sleep(0.75)
    return False


def find_row(pane: auto.Control, budget_seconds: float):
    """A collapsed suggestion in the feed. Its label leads with the suggestion
    type, which is where the running tally gets its categories from."""
    deadline = time.monotonic() + budget_seconds
    for node, _ in walk(pane, 32, deadline):
        if type_of(node) != auto.ControlType.ButtonControl:
            continue
        label = name_of(node)
        if ROW_MARKER in label and is_clickable_rect(node) and not is_tone_card(label.replace(ROW_MARKER, "")):
            return node, label
    return None


def read_pane_counter(pane: auto.Control, budget_seconds: float) -> int:
    """Suggestions remaining, taken from the assistant's own header.

    The window title carries strings like '20 suggestions', and the feed header
    carries '23 suggestions pages 33-42'. Both count the region Grammarly is
    currently looking at, not the document, so this is a lower bound."""
    texts = []
    try:
        texts.append(pane.Name or "")
    except Exception:  # noqa: BLE001 - window gone
        return -1
    deadline = time.monotonic() + budget_seconds
    for node, _ in walk(pane, 32, deadline):
        label = name_of(node)
        if "suggestion" in label:
            texts.append(label)
            if len(texts) > 12:
                break
    for text in texts:
        match = re.search(r"(\d+)\s+(?:review\s+)?suggestion", text.lower())
        if match:
            return int(match.group(1))
    return -1


def matches_label(label: str, candidate: str) -> bool:
    """Whether a control's name really carries this accept wording.

    Word boundaries, not substrings. Card labels quote the surrounding prose,
    so a plain "accept" test matches "acceptance", "apply" matches "applying",
    and the loop then hammers a control that applies nothing."""
    return re.search(rf"\b{re.escape(candidate)}\b", label) is not None


def type_of(control: auto.Control) -> int:
    """Control type, or -1 when the element has gone stale.

    Reading ControlType on an element the panel has just re-rendered raises
    COMError, which killed a run at its hundred and nineteenth accept. Every
    read of it goes through here."""
    try:
        return control.ControlType
    except Exception:  # noqa: BLE001 - stale element, window closing, RPC gone
        return -1


def name_of(control: auto.Control) -> str:
    try:
        return (control.Name or "").strip().lower()
    except Exception:  # noqa: BLE001
        return ""


def is_clickable_rect(control: auto.Control) -> bool:
    try:
        rect = control.BoundingRectangle
    except Exception:  # noqa: BLE001
        return False
    return rect.width() > 0 and rect.height() > 0


def is_actionable(control: auto.Control) -> bool:
    """Drawn on screen and not disabled. A rect can be nonzero while the
    control is greyed out mid card-transition, which invokes cleanly and
    changes nothing, the same silent failure as a stale label match."""
    if not is_clickable_rect(control):
        return False
    try:
        return bool(control.IsEnabled)
    except Exception:  # noqa: BLE001 - property absent on this node type
        return True


def safe_left(control: auto.Control) -> int:
    try:
        return control.BoundingRectangle.left
    except Exception:  # noqa: BLE001 - stale element mid-sort
        return 0


def runtime_id(control: auto.Control) -> tuple | None:
    """Stable identity for a control across searches. Name is not reliable for
    this: row labels quote surrounding prose, so two different rows can share
    a Name. Rect position is not reliable either: it moves as cards resize."""
    try:
        return tuple(control.GetRuntimeId())
    except Exception:  # noqa: BLE001 - stale element
        return None


def find_accept_control(
    root: auto.Control,
    max_depth: int,
    budget_seconds: float,
    exclude: set | None = None,
) -> tuple[auto.Control, str] | None:
    deadline = time.monotonic() + budget_seconds
    best: tuple[int, auto.Control, str] | None = None
    for node, _ in walk(root, max_depth, deadline):
        label = name_of(node)
        if not label or label in BLOCKED_NAMES:
            continue
        if any(bad in label for bad in BLOCKED_SUBSTRINGS):
            continue
        if ROW_MARKER in label:
            # A collapsed feed row, not a button that applies anything. These
            # carry the suggestion's surrounding prose in their label, and one
            # ending "terminates at final acceptance." matched a bare "accept"
            # thirty-four times in a row, applying nothing each time.
            continue
        if exclude and runtime_id(node) in exclude:
            # Blacklisted this drain: clicked repeatedly and changed nothing.
            continue
        for rank, candidate in enumerate(ACCEPT_NAMES):
            if not matches_label(label, candidate):
                continue
            # A card's body text can contain the phrase; only take controls
            # that are actually invokable, drawn on screen, and enabled.
            if not is_actionable(node):
                continue
            if type_of(node) not in (
                auto.ControlType.ButtonControl,
                auto.ControlType.HyperlinkControl,
                auto.ControlType.MenuItemControl,
                auto.ControlType.ListItemControl,
            ):
                continue
            if best is None or rank < best[0]:
                best = (rank, node, label)
            break
        if best and best[0] == 0:
            break
    if best is None:
        return None
    return best[1], best[2]


def load_learned_names(handle=None) -> None:
    """Merge previously learned accept labels into the lexical list. The pane
    uses different wording per suggestion category, so the list grows as the
    structural strategy meets card types this machine has not seen before."""
    if not LEARNED_PATH.exists():
        return
    try:
        learned = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"WARNING: could not read learned names ({exc}); using built-in list.", handle)
        return
    added = [n for n in learned if n not in ACCEPT_NAMES and n not in BLOCKED_NAMES]
    ACCEPT_NAMES.extend(added)
    if added:
        log(f"Loaded {len(added)} previously learned accept label(s): {added}", handle)


def remember_name(label: str, handle=None) -> None:
    if not label or label in ACCEPT_NAMES or label in BLOCKED_NAMES:
        return
    ACCEPT_NAMES.append(label)
    existing = []
    if LEARNED_PATH.exists():
        try:
            existing = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log(f"WARNING: learned-names file unreadable ({exc}); rewriting it.", handle)
    if label not in existing:
        existing.append(label)
    tmp = LEARNED_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    tmp.replace(LEARNED_PATH)  # atomic: a truncated list would silently narrow matching
    log(f"Learned a new accept label: '{label}'", handle)


def find_accept_by_card(
    root: auto.Control,
    max_depth: int,
    budget_seconds: float,
    handle=None,
    exclude: set | None = None,
) -> tuple[auto.Control, str] | None:
    """Structural discovery, for card wording the name list does not know.

    Every suggestion card carries a Dismiss control next to its primary button.
    Find Dismiss, climb until the container holds a second invokable control,
    and that sibling is the accept button whatever it happens to be called."""
    deadline = time.monotonic() + budget_seconds
    dismiss_nodes = []
    for node, _ in walk(root, max_depth, deadline):
        if name_of(node) in DISMISS_NAMES and is_clickable_rect(node):
            dismiss_nodes.append(node)

    for dismiss in dismiss_nodes:
        node = dismiss
        exhausted = True
        for _ in range(4):  # the card container is within a few levels of Dismiss
            try:
                parent = node.GetParentControl()
                siblings = parent.GetChildren() if parent else []
            except Exception as exc:  # noqa: BLE001 - card re-rendered under us
                log(f"  card structure went stale while climbing ({exc}).", handle)
                exhausted = False
                break
            if parent is None:
                exhausted = False
                break
            candidates = [
                s
                for s in siblings
                if name_of(s)
                and name_of(s) not in BLOCKED_NAMES
                and not any(bad in name_of(s) for bad in BLOCKED_SUBSTRINGS)
                and ROW_MARKER not in name_of(s)
                and is_actionable(s)
                and (not exclude or runtime_id(s) not in exclude)
                and type_of(s)
                in (auto.ControlType.ButtonControl, auto.ControlType.HyperlinkControl)
            ]
            if candidates:
                # The primary button sits left of Dismiss on these cards, so the
                # leftmost candidate is the one to take.
                candidates.sort(key=lambda c: safe_left(c))
                winner = candidates[0]
                return winner, name_of(winner)
            node = parent
        if exhausted:
            log(
                f"  card structure: no accept sibling found within 4 levels of "
                f"Dismiss {name_of(dismiss)[:40]!r}.",
                handle,
            )
    return None


def ancestor(control: auto.Control, levels: int) -> auto.Control | None:
    """Climb a few levels from the accept button to get a cheap search scope for
    the next card. Walking the whole Word tree ninety-five times is slow enough
    that the search budget can expire mid re-render and read as an empty feed."""
    node = control
    for _ in range(levels):
        try:
            parent = node.GetParentControl()
        except Exception:  # noqa: BLE001 - node went stale during re-render
            return None
        if parent is None:
            break
        node = parent
    return node


def scope_is_live(control: auto.Control | None) -> bool:
    if control is None:
        return False
    try:
        return control.Exists(maxSearchSeconds=0.2)
    except Exception:  # noqa: BLE001 - cached scope no longer in the tree
        return False


def invoke(control: auto.Control, handle=None) -> str:
    """Invoke pattern where the control supports it, mouse click otherwise.
    Invoke is preferable: it does not move the cursor, so the pane does not
    re-render a hover state mid-loop. Each fallback step is reported, because a
    silent demotion to synthetic clicking is the failure that later looks like
    the tool clicking the wrong button."""
    try:
        pattern = control.GetInvokePattern()
        if pattern:
            pattern.Invoke()
            return "invoke"
    except Exception as exc:  # noqa: BLE001 - pattern unsupported by WebView2 node
        swallow("invoke-pattern", exc)
        log(f"  invoke pattern unavailable ({exc}); trying legacy accessible.", handle)
    try:
        pattern = control.GetLegacyIAccessiblePattern()
        if pattern:
            pattern.DoDefaultAction()
            return "legacy"
    except Exception as exc:  # noqa: BLE001 - no legacy bridge on this node
        swallow("legacy-accessible", exc)
        log(f"  legacy accessible unavailable ({exc}); falling back to mouse click.", handle)
    try:
        # uiautomation reads ControlTypeName inside Click for its debug output,
        # which raises COMError on an element that has just been re-rendered.
        # That killed a run at its sixty-third accept.
        note_own_input()
        control.Click(waitTime=0)
        note_own_input()
        return "click"
    except Exception as exc:  # noqa: BLE001 - stale element, panel repainting
        swallow("click-stale-element", exc)
        log(f"  click failed against a stale element ({exc}).", handle)
        return "failed"


def scroll_pane(control: auto.Control, wheel_steps: int = 3, handle=None) -> None:
    """Wheel-scroll the panel. uiautomation scrolls wherever the cursor
    happens to be, so the cursor is parked over the pane first. The pane is the
    right-hand third of the Word window."""
    try:
        rect = control.BoundingRectangle
        x = rect.left + int(rect.width() * 0.85)
        y = rect.top + int(rect.height() * 0.5)
        note_own_input()
        auto.SetCursorPos(x, y)
        auto.WheelDown(wheel_steps)
        note_own_input()
    except Exception as exc:  # noqa: BLE001 - window went away mid-scroll
        log(f"  could not scroll the pane ({exc}).", handle)


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


def card_category(control: auto.Control, handle=None) -> str:
    """Name the suggestion type from the card's own header text. Read before the
    button is invoked, because the card is gone immediately afterwards."""
    container = ancestor(control, levels=5)
    if container is None:
        return "Unclassified"
    deadline = time.monotonic() + 1.2  # runs once per accepted card, keep it cheap
    for node, _ in walk(container, 10, deadline):
        label = name_of(node)
        if not label:
            continue
        for prefix, category in CATEGORY_HINTS:
            if label.startswith(prefix):
                return category
    return "Unclassified"


TYPE_WORDS = ("correctness", "clarity", "engagement", "delivery")
EXTRA_HINTS = (
    ("improve wording", "Clarity"),
    ("improve your text", "Clarity"),
    ("punctuation problem", "Correctness"),
    ("change preposition", "Correctness"),
    ("agreement", "Correctness"),
)


def category_from_card(text: str) -> str:
    """Type from the card's header, which sits before its 'learn more' link.
    The document's own sentence follows that link and must not be read, or a
    paragraph about delivery would classify every card beside it."""
    head = text.lower().split("learn more")[0]
    for word in TYPE_WORDS:
        if word in head:
            return word.title()
    for hint, category in EXTRA_HINTS:
        if hint in head:
            return category
    return "Unclassified"


def card_text(control: auto.Control) -> str:
    """The card's own wording, for the change record. Best effort and short."""
    container = ancestor(control, levels=5)
    if container is None:
        return ""
    parts: list[str] = []
    try:
        for node, _ in walk(container, 10, time.monotonic() + 0.6):
            label = name_of(node)
            if label and label not in DISMISS_NAMES and label != "rephrase" and not any(
                a in label for a in ACCEPT_NAMES if a != "rephrase"
            ):
                if label not in parts:
                    parts.append(label)
    except Exception:  # noqa: BLE001 - card re-rendered mid-read
        pass
    return " | ".join(parts)[:400]


def read_outstanding(root: auto.Control, budget_seconds: float) -> int:
    """The pane's own remaining-suggestions count.

    It is reported for the region currently in view, not the whole document, so
    it is a lower bound on what is left rather than a total. Returns -1 when the
    counter cannot be read, and the caller then reports the percentage as
    unavailable rather than inventing one."""
    deadline = time.monotonic() + budget_seconds
    try:
        bounds = root.BoundingRectangle
        pane_left = bounds.left + int(bounds.width() * 0.55)
    except Exception:  # noqa: BLE001 - window went away
        return -1

    fallback = -1
    for node, _ in walk(root, 24, deadline):
        label = name_of(node)
        if not label:
            continue
        if label.startswith("review suggestions"):
            tail = label.replace("review suggestions", "").strip()
            if tail.isdigit():
                return int(tail)
        # Bare digits are the pane's badge, but digits also appear all over
        # Word's own chrome. Only trust one drawn inside the panel, and
        # keep the largest, since the badge outnumbers any stray control index.
        if label.isdigit() and len(label) <= 4 and is_clickable_rect(node):
            try:
                if node.BoundingRectangle.left < pane_left:
                    continue
            except Exception:  # noqa: BLE001 - node went stale mid-walk
                continue
            fallback = max(fallback, int(label))
    return fallback


def policy_from_args(args) -> RunPolicy:
    """Zero or less means no limit, for the two time limits and the pass cap."""
    inf = float("inf")
    return RunPolicy(
        preset=args.preset,
        time_limit=args.time_limit if args.time_limit > 0 else inf,
        idle_limit=args.max_idle_seconds if args.max_idle_seconds > 0 else inf,
        whole_document=args.start_page <= 1 and args.end_page < 1,
        limit_override=args.max_passes if args.max_passes > 0 else None,
    )


def foreground_window() -> tuple[int, str, str]:
    """Handle, title and class of the window in front."""
    user32 = ctypes.windll.user32
    handle = user32.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(256)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(handle, title, 256)
    user32.GetClassNameW(handle, cls, 256)
    return handle, title.value, cls.value


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def seconds_since_user_input() -> float:
    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 9999.0
    return max(0, ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


# Our own activations and clicks register as input in GetLastInputInfo, so the
# engine would read its own SetActive as the person touching the keyboard. This
# stamp lets the check tell the two apart.
_own_input_at = 0.0


def note_own_input() -> None:
    global _own_input_at
    _own_input_at = time.monotonic()


def activate(window) -> None:
    note_own_input()
    try:
        hwnd = window.NativeWindowHandle
    except Exception:  # noqa: BLE001 - control without a handle
        hwnd = 0
    if not (hwnd and winfocus.force_foreground(hwnd)):
        window.SetActive()  # the old route, kept as the fallback
    note_own_input()


def person_used_input(within: float = 3.0) -> bool:
    """True only when input arrived recently and was not ours."""
    since = seconds_since_user_input()
    if since >= within:
        return False
    return (time.monotonic() - since) > _own_input_at + 1.0


def process_of(hwnd: int) -> str:
    """Executable name that owns a window, for the audit trail."""
    try:
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return f"pid {pid.value}"
        try:
            size = ctypes.c_ulong(512)
            buffer = ctypes.create_unicode_buffer(512)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return f"pid {pid.value}"
    except Exception:  # noqa: BLE001
        return "?"


class Audit:
    """One line per focus change and per focus decision, in audit.log beside the
    run log. Written so a person can answer "what stole the focus" afterwards."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.handle = path.open("a", encoding="utf-8") if path else None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: tuple | None = None
        self._shot_at: dict[str, float] = {}
        if self.handle:
            self.write("RUN", at=now().isoformat(timespec="seconds"))

    def write(self, event: str, **data) -> None:
        if not self.handle:
            return
        fields = " ".join(f"{k}={v!r}" for k, v in data.items())
        self.handle.write(f"[{now().strftime('%H:%M:%S.%f')[:-3]}] {event} {fields}\n")
        self.handle.flush()

    def snapshot(self, reason: str) -> None:
        """Save the whole screen to shots/ beside the log, so a person can see
        what the engine saw. At most one per reason every 20 seconds, 200 kept."""
        if not self.path:
            return
        stamp = time.monotonic()
        if stamp - self._shot_at.get(reason, -1e9) < 20:
            return
        self._shot_at[reason] = stamp
        try:
            from PIL import ImageGrab

            folder = self.path.with_name("shots")
            folder.mkdir(exist_ok=True)
            old = sorted(folder.glob("*.png"))
            for stale in old[: max(0, len(old) - 199)]:
                stale.unlink(missing_ok=True)
            from PIL import ImageDraw

            moment = now()
            name = f"{moment.strftime('%Y%m%d-%H%M%S')}-{reason}.png"
            image = ImageGrab.grab(all_screens=True).convert("RGB")
            # Burn the time into the picture so it survives being copied or renamed.
            stamp_text = f"{moment.strftime('%Y-%m-%d %H:%M:%S')}  {reason}"
            draw = ImageDraw.Draw(image)
            box = draw.textbbox((8, 8), stamp_text)
            draw.rectangle((box[0] - 6, box[1] - 4, box[2] + 6, box[3] + 4), fill=(0, 0, 0))
            draw.text((8, 8), stamp_text, fill=(255, 221, 0))
            image.save(folder / name)
            self.write("SHOT", file=name, reason=reason)
        except Exception as exc:  # noqa: BLE001 - a missed picture must never stop a run
            self.write("SHOT_FAILED", reason=reason, error=str(exc)[:80])

    def describe_front(self) -> dict:
        front, title, cls = foreground_window()
        return {
            "hwnd": front, "class": cls, "title": title[:60], "exe": process_of(front),
            "since_input": round(seconds_since_user_input(), 1),
            "own_input_ago": round(time.monotonic() - _own_input_at, 1) if _own_input_at else None,
            "person": person_used_input(),
        }

    def watch(self, interval: float = 0.4) -> None:
        """Log every change of the foreground window, even while the engine is busy."""
        if not self.handle or self._thread:
            return

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    info = self.describe_front()
                    key = (info["hwnd"], info["title"])
                    if key != self._last:
                        self._last = key
                        self.write("FRONT", **info)
                except Exception:  # noqa: BLE001 - never break a run for the audit
                    pass
                self._stop.wait(interval)

        self._thread = threading.Thread(target=loop, name="audit", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self.handle:
            self.write("END")
            self.handle.close()
            self.handle = None


AUDIT = Audit(None)


class Problem:
    def __init__(self, kind: str, text: str, fatal: bool = False, state: str = NEEDS_USER) -> None:
        self.kind = kind
        self.text = text
        self.fatal = fatal
        self.state = state


def front_problem(hwnd: int | None, session: WordSession, expected: str | None) -> Problem | None:
    """Why it is not safe to accept right now, or None. Grammarly follows
    whichever document has focus, so an accept with the wrong one in front lands
    in the wrong document, and the length check would read it as barren."""
    if hwnd and not ctypes.windll.user32.IsWindow(hwnd):
        return Problem("word-closed", "Word was closed.", fatal=True)
    if session.available:
        health = session.health()
        if health == "busy":
            return Problem("busy", "Word is waiting for you. Close its dialog to continue.")
        if health == "gone":
            return Problem("doc-closed", "The document was closed. Reopen it to continue.")
    front, title, cls = foreground_window()
    if hwnd and front != hwnd:
        if cls == WORD_WINDOW_CLASS:
            shown = title.split(" - ")[0] or "another document"
            return Problem(
                "other-doc",
                f"Word is showing {shown}. Nothing was changed there. Bring back the document being swept.",
            )
        exe = process_of(front).lower()
        # Grammarly's own panel and this program's windows take the foreground
        # as a side effect of the run. Neither is the person switching away.
        ours = (
            exe.startswith("grammarly")
            or exe.startswith("superhuman")  # Grammarly's panel host, seen live
            or exe.startswith("grammar sweeper")
            or exe in ("python.exe", "pythonw.exe")
            or title.lower().startswith("grammarly")
        )
        if not ours and person_used_input():
            return Problem("other-app", "You switched to another app. Return to Word to continue.")
        return Problem("stolen", "", state=RECONNECTING)
    if session.available and expected:
        active = session.active_document_name()
        if active and active != expected:
            return Problem(
                "other-doc",
                f"Word is showing {Path(active).name}. Bring back the document being swept.",
            )
    return None


def check_target(window, hwnd, session, budget, handle) -> str:
    """ok when it is safe to click, held after a pause that cleared (the panel
    must be searched again), or stop. With no interface attached the old
    behaviour stands: pull Word back and carry on."""
    control = budget.control
    expected = session.full_name() if session.available else None
    problem = front_problem(hwnd, session, expected)
    if problem is None:
        return "ok"
    AUDIT.write("PROBLEM", kind=problem.kind, **AUDIT.describe_front())
    AUDIT.snapshot(f"problem-{problem.kind}")
    if control is None:
        try:
            activate(window)
        except Exception:  # noqa: BLE001 - window gone
            pass
        return "ok"
    # A notification takes the focus back with no input from the person. Force
    # mode (--force-focus) treats every switch that way and always returns to Word.
    forced = bool(getattr(budget.args, "force_focus", False))
    for attempt in range(4):
        if problem is None or problem.fatal:
            break
        if problem.kind not in ("stolen", "other-app", "other-doc") or (
            problem.kind != "stolen" and not forced
        ):
            break
        try:
            activate(window)
        except Exception:  # noqa: BLE001
            pass
        AUDIT.write("TOOK_BACK", attempt=attempt + 1, kind=problem.kind, forced=forced)
        time.sleep(0.6)
        problem = front_problem(hwnd, session, expected)
    if problem is None:
        return "ok"
    if problem.fatal:
        budget.abort(problem.text)
        return "stop"
    if problem.kind == "stolen":
        problem = Problem("other-app", "Another window keeps taking focus. Return to Word to continue.")
    AUDIT.write("HOLD", kind=problem.kind, text=problem.text)
    log(f"  holding: {problem.text}", handle)
    def resolved() -> bool:
        now_problem = front_problem(hwnd, session, expected)
        return now_problem is None or now_problem.fatal

    if not control.hold(resolved, problem.text, problem.state):
        return "stop"
    after = front_problem(hwnd, session, expected)
    if after is not None and after.fatal:
        budget.abort(after.text)
        return "stop"
    return "held"


class Budget:
    """Shared stop conditions. The drain loop and the sweep both have to respect
    the same ceilings, or a multi-pass run has no bound at all."""

    def __init__(self, args, policy: RunPolicy | None = None, control: RunControl | None = None) -> None:
        self.args = args
        self.policy = policy or policy_from_args(args)
        self.control = control
        self.accepted = 0
        self.stop_reason: str | None = None
        self.outcome: Outcome | None = None
        self.by_type: Counter[str] = Counter()
        self.by_method: Counter[str] = Counter()
        self.outstanding = -1
        self.baseline = -1  # suggestions visible at the first reading
        self.page = 0
        self.pages = 0
        self.sweep = 0
        self.sweep_first = 1
        self.sweep_last = 0
        self.sweep_t0 = 0.0
        self.words_first = -1  # words ahead of the pass's first page
        self.words_last = -1  # words up to the end of the pass's last page
        self.words_done = -1  # words ahead of the page now being read
        self.session = None
        self.unread: list[str] = []  # page stops where the panel showed no text
        self.inconclusive: list[str] = []  # why the current pass cannot count as clean
        self.strays: list[str] = []  # accepts made while the wrong document was in front
        self.changes: ChangeLog | None = None  # per-accept record of what changed
        self.window: tuple[int, int] | None = None  # character span read around this page stop
        self.noeffect = 0  # clicks that changed nothing; never counted as applied
        self.no_text_run = 0  # stops in a row where Grammarly said it has no text to read
        self.measured_changed = 0  # paragraphs the document itself shows changed, read per stop
        self.undercount = 0  # how far the counter fell behind them
        self.total_words = 0
        self.heat: dict[int, dict[str, int]] = {}  # applied per page stop, by type, whole run
        self.clean_stops: list[float] = []  # seconds spent on stops that applied nothing
        self.resumed = False  # set when a pause ended; the panel must be found afresh
        self.resume_t: float | None = None
        self.on_resume = None
        self.capture_seconds = 0.0  # time spent recording before and after text

    def abort(self, reason: str) -> None:
        self.stop_reason = self.stop_reason or reason
        self.outcome = self.outcome or self.policy.failed(reason)

    def mark_inconclusive(self, why: str) -> None:
        if why not in self.inconclusive:
            self.inconclusive.append(why)

    def eta_run(self) -> tuple[float, int] | None:
        """(seconds for the whole run, passes still to come after this one).
        This pass's remainder, plus the passes the stop rule still needs: two
        clean ones in a row, capped by the preset's limit. A clean pass costs
        what stops that applied nothing have cost so far, 8 seconds a stop
        until some have been seen. It is a floor: passes that apply things run longer."""
        this_pass = self.eta_seconds()
        if this_pass is None:
            return None
        applied_now = self.accepted - sum(r.applied for r in self.policy.passes)
        streak = self.policy.consecutive_clean + (1 if applied_now == 0 else 0)
        need = max(0, 2 - streak)
        limit = self.policy.pass_limit
        if limit is not None:
            need = max(0, min(need, limit - (len(self.policy.passes) + 1)))
        stops = max(1, len(range(self.sweep_first, max(self.sweep_first, self.sweep_last) + 1, max(1, self.args.page_step))))
        per_stop = sorted(self.clean_stops)[len(self.clean_stops) // 2] if self.clean_stops else 8.0
        return this_pass + need * stops * per_stop, need

    def publish(self) -> None:
        if self.control is not None:
            self.control.emit(
                "progress",
                applied=self.accepted,
                page=self.page,
                pages=self.pages,
                sweep=self.sweep,
                limit=self.policy.pass_limit,
                heat={k: dict(v) for k, v in self.heat.items()},
                noeffect=self.noeffect,
                caret=self.session.caret_page() if self.session is not None and self.session.available else -1,
                scope=getattr(self, "scope", None),
                measured=self.measured_changed,
                behind=self.undercount,
                eta_run=self.eta_run(),
                passes_done=[r.applied for r in self.policy.passes],
                first=self.sweep_first,
                last=self.sweep_last,
                step=self.args.page_step,
                percent=self.percent(),
                eta=self.eta_seconds(),
                outstanding=self.outstanding,
                running=self.policy.clock.running_seconds(),
                by_type=dict(self.by_type),
            )

    def note(self, category: str) -> None:
        self.by_type[category] += 1

    def breakdown(self) -> str:
        if not self.by_type:
            return "none yet"
        parts = [f"{name} {count}" for name, count in sorted(self.by_type.items())]
        return ", ".join(parts)

    def percent(self) -> float | None:
        """Share of the current sweep done, by page position. The earlier
        estimate divided accepts by the suggestions visible so far, which read
        95% at page 11 of 111 because the panel only counts what is in view.
        Page position is the one honest measure, and it covers one sweep only:
        how many sweeps follow is not knowable in advance."""
        if self.pages <= 0 or self.sweep_last < self.sweep_first or self.page <= 0:
            return None
        # Words first: the share of the pass's text already reviewed.
        if self.words_last > self.words_first >= 0 and self.words_done >= 0:
            done = max(0, self.words_done - self.words_first)
            return min(100.0, 100.0 * done / (self.words_last - self.words_first))
        # Word statistics unavailable: fall back to page position.
        span = self.sweep_last - self.sweep_first + 1
        done = max(0, self.page - self.sweep_first)
        return min(100.0, 100.0 * done / span)

    def eta_seconds(self) -> float | None:
        """Running seconds left in this sweep, from this sweep's pace so far.
        None until enough of the sweep has gone by to say anything useful."""
        fraction = (self.percent() or 0.0) / 100.0
        elapsed = self.policy.clock.running_seconds() - self.sweep_t0
        if fraction < 0.05 or elapsed < 20:
            return None
        return elapsed * (1.0 - fraction) / fraction

    def status_line(self) -> str:
        elapsed = int(self.policy.clock.running_seconds())
        left = "unknown" if self.outstanding < 0 else str(self.outstanding)
        pct = self.percent()
        pct_text = "sweep --%" if pct is None else f"sweep {pct:4.0f}%"
        return (
            f"{pct_text} | applied {self.accepted} | visible outstanding {left} "
            f"| {self.breakdown()} | {elapsed}s"
        )

    def exhausted(self) -> bool:
        if self.stop_reason:
            return True
        if escape_pressed():
            self.stop_reason = "ESC pressed"
            self.outcome = self.policy.stopped_by_user("Esc")
            return True
        if self.control is not None:
            if self.control.wait_while_blocked():
                self.resumed = True
                self.resume_t = time.monotonic()
                AUDIT.write("RESUME")
                if self.on_resume is not None:
                    self.on_resume()
            if self.control.stop_requested:
                self.stop_reason = self.control.stop_reason
                self.outcome = self.policy.failed(self.control.stop_reason)
                return True
        # A ceiling of zero or less means none, as the spec says.
        if self.args.max_accepts > 0 and self.accepted >= self.args.max_accepts:
            self.stop_reason = f"max-accepts ceiling of {self.args.max_accepts} reached"
            self.outcome = self.policy.failed(self.stop_reason)
            return True
        brake = self.policy.interrupt()
        if brake is not None:
            self.stop_reason = brake.reason
            self.outcome = brake
            return True
        return False


def show_status(budget: Budget, handle=None) -> None:
    """Live counter on the console, full history in the log file. The console
    line is rewritten in place so the accept lines stay readable above it."""
    line = budget.status_line()
    print(f"  {line}".ljust(110), end="\r", flush=True)


def resolve_search_root(window, args, handle):
    """The Grammarly panel, or nothing. Never silently the Word window.

    The panel renders its feed only while Word holds focus, and it tears the
    subtree down the moment focus leaves, so a check run too soon after
    activating Word sees an empty tree and reads as collapsed. Hence: activate,
    wait, look, and try again a few times before concluding anything."""
    pane = None
    for attempt in range(1, args.pane_attempts + 1):
        try:
            activate(window)
        except Exception as exc:  # noqa: BLE001 - Word refused focus
            log(f"  could not bring Word to the foreground ({exc}).", handle)
        time.sleep(args.focus_settle)

        pane = find_pane(window, args.max_depth, args.search_budget, handle)
        if pane is None:
            log(f"  attempt {attempt}: panel window not present.", handle)
            continue
        if pane_is_open(pane, args.pane_budget):
            return pane
        log(f"  attempt {attempt}: panel found but feed not rendered yet.", handle)

    if pane is None:
        log("Grammarly's review panel was not found.", handle)
        log("  It is a top-level window named 'Grammarly', separate from Word,", handle)
        log("  and it is only present while Word is the foreground window.", handle)
        log("  Check Grammarly is running and attached to this document, then rerun.", handle)
        return None

    log("The panel is present but is not showing the suggestion feed.", handle)
    log("  Open the Grammarly panel in Word so the suggestion list is visible,", handle)
    log("  and leave that document focused. Nothing will be clicked until it is.", handle)
    return None


def ensure_root(window, args, budget, handle, current=None):
    """Return a live search root, recovering when the panel goes away.

    Long runs lose the panel: Word drops focus, Grammarly tears the WebView2
    down, the panel gets closed. Exiting on the first such event wastes hours of
    a sweep, so this keeps re-acquiring until it succeeds, the accept ceiling is
    reached, or ESC is pressed. It cannot click the panel open, since Grammarly
    ignores synthetic clicks on that control, so if a person has closed it this
    waits for them to open it again."""
    if current is not None and scope_is_live(current):
        return current

    attempt = 0
    announced = False
    control = budget.control
    try:
        while not budget.exhausted():
            attempt += 1
            if control is not None and announced:
                # Word may have been closed while the panel was gone.
                gone = front_problem(window.NativeWindowHandle, budget.session, None) if budget.session else None
                if gone is not None and gone.fatal:
                    budget.abort(gone.text)
                    return None
            root = resolve_search_root(window, args, handle)
            if root is not None:
                if announced:
                    log(f"Panel recovered after {attempt} attempt(s). Continuing.", handle)
                return root
            if not announced:
                log("Waiting for the Grammarly panel. The run continues once it returns.", handle)
                log("  If it was closed, open it in Word and leave that document focused.", handle)
                announced = True
                if control is not None:
                    # Time spent waiting for the person does not count toward the limits.
                    control.clock.pause()
                    control.set_state(NEEDS_USER, "Grammarly was closed. Open it in Word to continue.")
            # Back off geometrically so a permanently-gone panel does not spin at
            # the base interval for the rest of the time budget.
            wait = min(args.recover_wait * (2 ** min(attempt - 1, 4)), args.recover_wait_max)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if control is not None and control.stop_requested:
                    break
                time.sleep(0.25)
    finally:
        if control is not None and announced:
            control.clock.resume()
            if not control.stop_requested:
                control.set_state("running")
    return None


def category_from_row(label: str) -> str:
    """The row label leads with the suggestion type, so the tally does not have
    to climb an expanded card to find out what it just applied."""
    text = label.replace(ROW_MARKER, "").strip()
    for prefix, category in CATEGORY_HINTS:
        if text.startswith(prefix):
            return category
    if text.startswith("check wording"):
        return "Clarity"
    return "Unclassified"


def open_a_card(pane, args, handle) -> str | None:
    """Expand the next collapsed suggestion. Returns the category of whatever
    was opened, or None when the feed has nothing left to open."""
    found = find_row(pane, args.search_budget)
    if found is None:
        return None
    row, label = found
    category = category_from_row(label)
    method = invoke(row, handle)
    time.sleep(args.settle)
    log(f"  opened card [{category}] via {method}: {label[:60]!r}", handle)
    return category


def locate_accept(root, scope, args, handle, exclude: set | None = None):
    """Lexical match first because it is cheap, structural second because it
    works on wording we have never seen. A label found structurally is learned,
    so the next card of that type is caught by the cheap path."""
    if scope_is_live(scope):
        found = find_accept_control(scope, args.max_depth, args.search_budget / 3, exclude)
        if found:
            return found, scope
    found = find_accept_control(root, args.max_depth, args.search_budget, exclude)
    if found:
        return found, None
    if args.no_structural:
        return None, None
    found = find_accept_by_card(root, args.max_depth, args.search_budget, handle, exclude)
    if found:
        remember_name(found[1], handle)
        return found, None
    return None, None


def feed_state(root, seconds: float, depth: int = 32, page: int | None = None) -> str:
    """cards, no-text or empty, decided within `seconds`. Meant for pages that
    have nothing to accept: the full search budgets (six seconds a tree, three
    empty rounds) made a blank page cost close to a minute, so a quick look
    comes first and only a page that shows cards earns the slow path."""
    deadline = time.monotonic() + seconds
    saw_idle = False
    saw_clean = False
    try:
        for node, _ in walk(root, depth, deadline):
            label = name_of(node)
            if not label:
                continue
            if ROW_MARKER in label or label in DISMISS_NAMES:
                return "cards"
            if any(candidate in label for candidate in ACCEPT_NAMES):
                return "cards"
            if "no text available" in label or IDLE_MARKER in label:
                saw_idle = True
            if "no unresolved suggestions" in label or "nothing to see yet" in label:
                # The panel states the pages it has cleared, such as "for pages 19-28".
                # Only trust it when those pages include this one; otherwise it is
                # the previous stop's message, not yet replaced.
                found = re.search(r"pages? (\d+)(?:\s*(?:-|to)\s*(\d+))?", label)
                if page is not None and found:
                    low, high = int(found.group(1)), int(found.group(2) or found.group(1))
                    saw_clean = low <= page <= high
                else:
                    saw_clean = page is None
    except Exception:  # noqa: BLE001 - panel re-rendered mid-walk
        return "cards"  # unsure: take the careful path rather than skip a page
    if saw_clean:
        return "clean"
    return "no-text" if saw_idle else "empty"


ASSISTANT_HOTKEY = "{Ctrl}{Shift}{Alt}g"  # Grammarly's own: opens the assistant, and closes it when open


def wait_panel(showing: bool, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if winfocus.panel_visible() == showing:
            return True
        time.sleep(0.25)
    return winfocus.panel_visible() == showing


def reset_panel(window, handle=None) -> bool:
    """Close and reopen Grammarly's assistant, which makes it re-read the document at the
    caret. Seen live: the hotkey toggles, so a showing panel needs it twice. Word has to be
    in front for the key to reach Grammarly. True once the panel is showing again."""
    activate(window)
    time.sleep(0.4)
    if winfocus.panel_visible():
        note_own_input()
        auto.SendKeys(ASSISTANT_HOTKEY, waitTime=0.1)
        note_own_input()
        if not wait_panel(False, 3.0):
            log("  could not close Grammarly's panel to reset it.", handle)
            return False
        time.sleep(0.5)
    note_own_input()
    auto.SendKeys(ASSISTANT_HOTKEY, waitTime=0.1)
    note_own_input()
    opened = wait_panel(True, 6.0)
    AUDIT.write("PANEL_RESET", opened=opened)
    return opened


def read_scope(root, seconds: float) -> tuple[int, int] | None:
    """The pages Grammarly says it is reviewing, from the panel's own text such as
    '3 review suggestions pages 57-66' or 'No unresolved suggestions for pages 24-33'.
    It reviews ten pages at a time around the caret and only re-scopes after a real
    click, so this is the one honest sign that the panel has followed the sweep."""
    try:
        for node, _ in walk(root, 32, time.monotonic() + seconds):
            label = name_of(node)
            if not label or ROW_MARKER in label:
                continue
            found = re.search(r"pages? (\d+)(?:\s*(?:-|to)\s*(\d+))?", label)
            if found:
                return int(found.group(1)), int(found.group(2) or found.group(1))
    except Exception:  # noqa: BLE001 - panel re-rendered mid-walk
        return None
    return None


def wait_for_scope(root, page: int, session: WordSession, wait: float) -> tuple[int, int] | None:
    """Poll until the panel's scope holds `page`, then return it at once. Clicks into
    the page once, late (60% of the way), because a click is sometimes ignored. Seen
    live: Grammarly follows in one to eight seconds, and clicking again earlier
    restarts its delay, so three clicks failed where one click and a wait worked.
    None when the panel never followed."""
    start = time.monotonic()
    retries = [wait * 0.6]
    while time.monotonic() - start < wait:
        scope = read_scope(root, 1.0)
        if scope and scope[0] - 1 <= page <= scope[1] + 1:
            return scope
        if retries and time.monotonic() - start > retries[0]:
            retries.pop(0)
            session.click_into_page(page)
            session.nudge()  # a real key event, in case the click alone was ignored
        time.sleep(0.25)
    return None


def _version() -> str:
    """Version, commit and build time of the running program, for the audit log."""
    try:
        from sweeper import version

        return f"{version.LABEL} built {version.BUILT}"
    except Exception:  # noqa: BLE001 - a stamp must never stop a run
        return "unknown"


NO_TEXT_HOLD = 3  # stops in a row with no text before the run waits for the person


def refocus_word(window, session, page: int) -> None:
    """Put the Word document back in front and the caret in its text. "No text available" most
    often means the document is not the focused window, so this is the first thing tried."""
    if window is not None:
        activate(window)
        time.sleep(0.8)
    session.scroll_to_page(page)
    session.click_into_page(page)


def recover_no_text(root, args, session, budget, window, handle, page: int):
    """Grammarly said "No text available" at this page. Try, in order: put the Word document
    back in focus, click a different paragraph (the first may be somewhere it cannot read),
    a key nudge, then a panel restart.
    Each rung is followed by a look at the panel. Returns (state, root); the state is
    "no-text" only when every rung failed."""
    try:
        _hwnd, front_title, front_class = foreground_window()
    except Exception:  # noqa: BLE001 - diagnostics only
        front_title, front_class = "unknown", "unknown"
    AUDIT.write("NO_TEXT_SEEN", page=page, front_title=front_title[:60], front_class=front_class)
    rungs = (
        ("refocus-word", lambda: refocus_word(window, session, page)),
        ("other-paragraph-1", lambda: session.click_into_page(page, skip=1)),
        ("other-paragraph-2", lambda: session.click_into_page(page, skip=2)),
        ("nudge", session.nudge),
        ("panel-reset", None),
    )
    for name, act in rungs:
        if budget.exhausted():
            break
        if act is None:
            if not reset_panel(window, handle):
                continue
            root = ensure_root(window, args, budget, handle)
            if root is None:
                break
            session.scroll_to_page(page)
            session.click_into_page(page)
        else:
            act()
        time.sleep(1.0)
        state = feed_state(root, max(args.empty_probe, 3.0), page=page)
        if state != "no-text":
            AUDIT.write("NO_TEXT_RECOVERED", page=page, rung=name, state=state)
            log(f"  p{page}: Grammarly could read the page after '{name}'.", handle)
            return state, root
    AUDIT.write("NO_TEXT_FAILED", page=page, caret=session.caret_context())
    return "no-text", root


def hold_for_text(root, budget, session, handle, page: int) -> None:
    """Several stops in a row have no text to read, so the problem is the document or Word, not
    one page. The run waits for the person, up to five minutes, and carries on by itself the
    moment Grammarly can read text again."""
    where = session.caret_context() if session.available else "unknown"
    log(f"  {NO_TEXT_HOLD} stops in a row have no text for Grammarly (caret {where}).", handle)
    control = budget.control
    if control is None:
        return
    control.clock.pause()
    control.set_state(
        NEEDS_USER,
        "Grammarly says it has no text to read. Click into the body text in Word and close any "
        "dialog or banner. The run continues by itself.",
    )
    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not control.stop_requested:
            time.sleep(2.0)
            if feed_state(root, 2.0, page=page) != "no-text":
                break
    finally:
        control.clock.resume()
        control.set_state("running")
    budget.no_text_run = 0


def changed_paragraphs(before: str, after: str) -> int:
    """How many paragraphs of the document differ between two readings of its text.
    One accepted suggestion changes one paragraph, so this is a floor on what was applied:
    two accepts in one paragraph count once here, and none can count less than it did."""
    import difflib

    old, new = before.split("\r"), after.split("\r")
    if old == new:
        return 0
    total = 0
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            total += max(a1 - a0, b1 - b0)
    return total


def watch_count(session, budget, text_before, page, counted: int, noeffect: int, handle) -> None:
    """Independent check on the applied counter. The document's own text is read before and
    after each stop. More paragraphs changed than the counter says were applied means the
    counter is behind the document, and the stop is written to the audit log with both
    figures. Seen live: more suggestions changed than the counter showed."""
    if text_before is None:
        return
    began = time.monotonic()
    text_after = session.text()
    if text_after is None:
        return
    changed = changed_paragraphs(text_before, text_after)
    chars = len(text_after) - len(text_before)
    budget.measured_changed += changed
    behind = max(0, changed - counted)
    budget.undercount += behind
    AUDIT.write(
        "STOP_DELTA", page=page, counted=counted, clicks_no_effect=noeffect, paragraphs_changed=changed,
        chars=chars, behind=behind, check_seconds=round(time.monotonic() - began, 2),
    )
    if behind:
        log(f"  p{page}: the document changed in {changed} paragraph(s) but the counter shows {counted}.", handle)


SCOPE_WINDOW = 10  # pages Grammarly reviews at a time


def scope_for_stop(root, page: int, pages: int, session: WordSession, wait: float):
    """The pages Grammarly is reviewing for this stop. A document of ten pages or fewer fits in
    one window and Grammarly shows no page range for it (seen live on a three page document), so
    its scope is the whole document and nothing is waited for."""
    if 0 < pages <= SCOPE_WINDOW:
        return 1, pages
    return wait_for_scope(root, page, session, wait)


def where_page(where: str, budget) -> int:
    """The page stop a drain belongs to; the current page for the visible-only case."""
    return int(where[1:]) if where.startswith("p") and where[1:].isdigit() else budget.page


def drain_feed(
    root,
    args,
    session: WordSession,
    budget: Budget,
    handle,
    where: str,
    window=None,
    hwnd: int | None = None,
    uhandle=None,
) -> int:
    """Accept every card the pane is currently offering, then return."""
    drained = 0
    misses = 0
    opens = 0  # cards opened in a row with no accept button found
    scope: auto.Control | None = None

    pending_category: str | None = None
    barren = 0
    barren_resets = 0  # counts re-searches forced by a stuck control, not misses
    reopened: set = set()  # controls whose card has been reopened once already
    blacklist: set = set()  # runtime ids clicked barren args.barren_limit times

    barren_streak_label: str | None = None
    barren_streak_count = 0

    # Quick look first. Two probes a second apart, because a panel that has
    # just re-scoped can render late, and one early blank must not read as clean.
    if args.empty_probe > 0 and where != "visible":
        stop_page = int(where[1:]) if where.startswith("p") and where[1:].isdigit() else None
        state = feed_state(root, args.empty_probe, page=stop_page)
        if state not in ("cards", "clean"):
            time.sleep(1.0)
            state = feed_state(root, args.empty_probe, page=stop_page)
        if state == "clean":
            log(f"  {where}: the panel reports nothing unresolved here, moving on.", handle)
            AUDIT.write("CLEAN_PAGE", where=where)
            return 0
        if state == "no-text" and where.startswith("p") and session.available:
            state, root = recover_no_text(root, args, session, budget, window, handle, int(where[1:]))
        if state == "no-text":
            # Every rung failed and the panel still says it has nothing to read: the one verdict
            # trusted enough to skip a page, recorded with where the caret was.
            log(f"  {where}: the panel shows no text, moving on.", handle)
            AUDIT.write("EMPTY_PAGE", where=where, state=state)
            AUDIT.snapshot("no-text-page")
            budget.unread.append(where)  # judged at the end of the pass
            budget.no_text_run += 1
            if budget.no_text_run >= NO_TEXT_HOLD:
                hold_for_text(root, budget, session, handle, stop_page or budget.page)
            return 0
        budget.no_text_run = 0
        if state == "empty":
            # Seen live: pages full of suggestions read as "empty" here. No cards
            # and no "no text" notice proves nothing, so take the full search.
            AUDIT.write("EMPTY_UNCONFIRMED", where=where)
            AUDIT.snapshot("empty-page")

    def flush_barren_streak() -> None:
        nonlocal barren_streak_label, barren_streak_count
        if barren_streak_count > 1:
            log(
                f"  (suppressed {barren_streak_count - 1} further identical "
                f"barren-click line(s) for {barren_streak_label[:60]!r})",
                handle,
            )
        barren_streak_label = None
        barren_streak_count = 0

    while not budget.exhausted():
        if budget.resumed:
            budget.resumed = False
            scope = None  # the panel was idle while paused; look for it afresh
            misses = 0
        # A long unattended run can lose foreground focus to a notification or
        # another window. Force it back before searching rather than waiting
        # for the next scroll or panel-recovery to notice.
        if budget.control is None and hwnd is not None and window is not None:
            try:
                if ctypes.windll.user32.GetForegroundWindow() != hwnd:
                    activate(window)
            except Exception:  # noqa: BLE001 - window gone, let the loop's own checks catch it
                pass

        try:
            found, scope = locate_accept(root, scope, args, handle, blacklist)
        except Exception as exc:  # noqa: BLE001 - panel re-rendered mid-search
            swallow("search-stale-element", exc)
            # A stale element ends a four-hour run otherwise. Drop the cached
            # scope, count it as a miss, and carry on.
            log(f"  search failed against a stale element ({exc}); retrying.", handle)
            scope = None
            misses += 1
            if misses >= args.idle_rounds:
                flush_barren_streak()
                return drained
            time.sleep(args.settle)
            continue
        if not found:
            # No accept control means no card is expanded. The feed lists
            # suggestions as rows, and a card's accept button does not exist
            # until its row has been opened, so open the next one and re-look.
            pending_category = open_a_card(root, args, handle)
            if pending_category is not None:
                # Seen live: two cards that never showed an accept button were
                # opened in turn for five minutes, ending the whole run. Give
                # up on the page instead and carry on to the next.
                opens += 1
                if opens > max(8, args.idle_rounds * 3):
                    flush_barren_streak()
                    log(f"  {where}: cards open but offer no accept button; moving on.", handle)
                    AUDIT.write("PAGE_ABANDONED", where=where, reason="cards-no-accept")
                    AUDIT.snapshot("no-accept-button")
                    budget.mark_inconclusive(f"{where} had cards that could not be accepted")
                    return drained
                continue
            misses += 1
            if misses >= args.idle_rounds:
                flush_barren_streak()
                if drained == 0:
                    AUDIT.write("NO_ACCEPT_FOUND", where=where)
                    AUDIT.snapshot("no-accept-found")
                return drained
            scroll_pane(root, handle=handle)
            time.sleep(args.settle)
            continue

        misses = 0
        opens = 0
        control, label = found
        control_id = runtime_id(control)
        if is_tone_card(card_text(control)):
            blacklist.add(control_id)  # never clicked, and not looked at again this page
            AUDIT.write("TONE_SKIPPED", where=where, label=label[:60])
            log(f"  {where}: left a tone card alone, tone changes are never accepted: '{label[:60]}'", handle)
            continue
        if scope is None:
            scope = ancestor(control, levels=6)
        # Read the card's type before invoking: the card is destroyed by the click.
        category = pending_category or card_category(control, handle)
        pending_category = None
        if budget.control is not None and hwnd is not None:
            verdict = check_target(window, hwnd, session, budget, handle)
            if verdict == "stop":
                flush_barren_streak()
                return drained
            if verdict == "held":
                scope = None  # the panel was rebuilt while paused; look again
                continue
        text_before = None
        record_card = ""
        span = budget.window if (budget.changes is not None and session.available) else None
        if span is not None:
            began = time.monotonic()
            text_before = session.range_text(*span)
            record_card = card_text(control)
            budget.capture_seconds += time.monotonic() - began
        before = session.char_count()
        method = invoke(control, handle)
        if method == "failed":
            # The element went stale between finding it and clicking it. Look again
            # once and click what the panel shows now, before counting a failure.
            AUDIT.write("INVOKE_RETRY", where=where, label=label[:60])
            try:
                again, scope = locate_accept(root, None, args, handle, blacklist)
            except Exception as exc:  # noqa: BLE001 - still repainting
                swallow("retry-search", exc)
                again = None
            if again:
                control = again[0]
                method = invoke(control, handle)
                AUDIT.write("INVOKE_RETRY_RESULT", method=method)
        budget.by_method[method] += 1
        time.sleep(args.settle)
        after = session.char_count()
        delta = "" if after < 0 else f" chars {before:+d}->{after} ({after - before:+d})"
        text_after = None
        if text_before is not None:
            began = time.monotonic()
            grown = after - before if after >= 0 and before >= 0 else 0
            text_after = session.range_text(span[0], max(span[0], span[1] + grown))
            budget.capture_seconds += time.monotonic() - began
        # Changed nothing only when the length and the text near the card agree.
        is_barren = after >= 0 and after == before and (
            text_before is None or text_after is None or text_before == text_after
        )
        if category == "Unclassified" and record_card:
            category = category_from_card(record_card)
        if budget.resume_t is not None:
            AUDIT.write("RESUME_FIRST_ACCEPT", seconds=round(time.monotonic() - budget.resume_t, 1))
            budget.resume_t = None
        if is_barren:
            budget.noeffect += 1  # clicked, but the document did not change: not applied
        else:
            budget.accepted += 1
            budget.note(category)
            drained += 1
            stop = where_page(where, budget)
            by_type = budget.heat.setdefault(stop, {})
            by_type[category] = by_type.get(category, 0) + 1
            if category == "Unclassified" and uhandle is not None:
                uhandle.write(f"[{now().strftime('%H:%M:%S%z')}] [{where}] {label!r}\n")
                uhandle.flush()
            if text_before is not None and text_after is not None:
                found = locate_change(text_before, text_after)
                absolute = span[0] + found["index"]
                extra = enrich(found, text_before, text_after, category, record_card)
                budget.changes.add(
                    run=getattr(args, "run_id", ""), doc=getattr(args, "doc_hash", ""), draft=getattr(args, "draft", None),
                    n=budget.accepted, time=now().strftime('%H:%M:%S'), page=session.page_of(absolute),
                    stop=budget.page, section=session.heading_path(absolute), category=category,
                    label=label, card=record_card,
                    **{**found, "index": absolute}, **extra,
                )
                budget.window = (span[0], max(span[0], span[1] + grown))

        if is_barren and label == barren_streak_label:
            barren_streak_count += 1
        else:
            flush_barren_streak()
            if is_barren:
                barren_streak_label = label
                barren_streak_count = 1

        if not is_barren or barren_streak_count == 1:
            tag = f"Accepted #{budget.accepted}" if not is_barren else "Clicked, no change"
            log(f"{tag} [{where}] {category} via {method}: '{label}'{delta}", handle)

        count = (
            read_pane_counter(root, 1.5)
            if budget.accepted % args.counter_every == 0 or budget.baseline < 0
            else -1
        )
        if count >= 0:
            budget.outstanding = count
            if budget.baseline < 0:
                budget.baseline = count + 1  # this card was one of them
        show_status(budget, handle)

        if budget.accepted % args.counter_every == 0:
            write_checkpoint(budget, session, where)
            if not args.no_periodic_save and session.available:
                session.save_now(handle)

        budget.publish()

        if is_barren:
            # The click landed but the document did not change. One of these is
            # normal mid re-render. A run of them means the control does not
            # apply anything: reopen its card once, and only then stop trusting it.
            barren += 1
            time.sleep(args.settle)
            if barren >= args.barren_limit:
                flush_barren_streak()
                if control_id is not None and control_id not in reopened:
                    reopened.add(control_id)
                    log(f"  {barren} accepts changed nothing; reopening the card before giving up on it.", handle)
                    AUDIT.write("CARD_REOPENED", where=where, label=label[:60])
                    scope = None
                    barren = 0
                    pending_category = open_a_card(root, args, handle)
                    continue
                log(f"  {barren} accepts changed nothing; blacklisting and re-searching.", handle)
                budget.mark_inconclusive("accepts that changed nothing, repeatedly")
                if control_id is not None:
                    blacklist.add(control_id)
                scope = None
                barren = 0
                barren_resets += 1
                if barren_resets >= args.idle_rounds:
                    log(f"  {barren_resets} barren-reset(s); giving up on this feed.", handle)
                    return drained
        else:
            barren = 0
            barren_resets = 0
            budget.policy.clock.progress()
            reopened.discard(control_id)

    flush_barren_streak()
    return drained


def run_uia(args, session: WordSession, handle, uhandle=None, control: RunControl | None = None) -> Budget:
    # The panel scopes itself to whichever document has focus, so the right Word
    # window has to be activated. With several documents open, picking the first
    # one leaves the panel idle for a document nobody asked about.
    title = args.window or args.document
    window = find_word_window(title)
    activate(window)
    time.sleep(0.4)
    try:
        hwnd = window.NativeWindowHandle
    except Exception:  # noqa: BLE001 - handle unavailable on this control type
        hwnd = None
    policy = policy_from_args(args)
    if control is not None:
        control.clock = policy.clock
    budget = Budget(args, policy, control)
    budget.session = session
    budget.changes = ChangeLog(getattr(args, "changes_path", None))
    budget.on_resume = lambda: (activate(window), time.sleep(0.3))
    if session.available and not args.keep_markup:
        if session.hide_markup():
            log("Word's markup is hidden for the run. It is restored at the end.", handle)

    root = ensure_root(window, args, budget, handle)
    if root is None:
        budget.abort("panel never became available")
        return budget

    if not session.available or args.no_sweep:
        # No COM, so the document cannot be scrolled from here. This drains only
        # what the pane currently offers, which on a long document is a subset.
        if not args.no_sweep:
            log("WARNING: no COM connection, so the document cannot be swept.", handle)
            log("         Only suggestions for the visible region will be applied.", handle)
        drain_feed(root, args, session, budget, handle, "visible", window, hwnd, uhandle)
        if budget.stop_reason:
            log(f"Stopped: {budget.stop_reason}.", handle)
        return budget

    # Sweep until the policy says stop: two consecutive clean passes, the preset's
    # pass limit, the repetition guard, or a hard brake. See docs/spec.md.
    sweep = 0
    while True:
        sweep += 1
        budget.sweep = sweep
        if budget.exhausted():
            break
        pages = session.page_count()
        if pages < 1:
            log("Page count unavailable; draining the visible region only.", handle)
            drain_feed(root, args, session, budget, handle, "visible", window, hwnd, uhandle)
            break

        limit = policy.pass_limit
        limit_text = "" if limit is None else f" of up to {limit}"
        log(f"--- pass {sweep}{limit_text}: {pages} page(s) ---", handle)
        budget.pages = pages
        budget.inconclusive = []
        budget.unread = []
        before_pass = budget.accepted

        first = max(1, args.start_page)
        last = pages if args.end_page < 1 else min(pages, args.end_page)
        budget.sweep_first, budget.sweep_last = first, last
        budget.sweep_t0 = policy.clock.running_seconds()
        budget.page = first
        total_words = session.words_total()
        budget.words_first = session.words_before_page(first) if first > 1 else 0
        budget.words_last = (
            total_words if last >= pages else session.words_before_page(last + 1)
        )
        budget.words_done = budget.words_first
        budget.total_words = total_words
        log(f"  {total_words} word(s); this pass covers words {budget.words_first} to {budget.words_last}.", handle)
        if first > last:
            log(f"Start page {first} is past the end of the document ({last}).", handle)
            budget.abort(f"start page {first} is past the end of the document")
            break
        visited = 0
        expected_stops = len(range(first, last + 1, args.page_step))
        stops = list(range(first, last + 1, args.page_step))
        retried: set[int] = set()
        reset_tried: set[int] = set()
        current_chunk = 0
        position = 0
        while position < len(stops):
            page = stops[position]
            position += 1
            if budget.exhausted():
                break
            budget.page = page
            budget.words_done = session.words_before_page(page)
            policy.clock.progress()  # reaching a new page is progress
            budget.window = session.window_span(page) if budget.changes is not None else None
            budget.publish()
            if args.save_before_scroll and session.available:
                session.save_now(handle)
            if not session.scroll_to_page(page):
                budget.mark_inconclusive(f"page {page} could not be reached")
                continue
            # A caret moved through COM does not make Grammarly re-scope; a real click does.
            session.click_into_page(page)

            # Re-acquire the panel if it went away, and treat a long run of
            # pages that yield nothing as a stall worth re-acquiring for: the
            # panel can stay present while having quietly stopped proofreading.
            root = ensure_root(window, args, budget, handle, root)
            if root is None:
                break
            stalled = policy.clock.idle_seconds()
            if stalled > args.stall_seconds:
                log(f"No accepts for {int(stalled)}s. Re-acquiring the panel.", handle)
                if control is not None:
                    control.set_state(RECONNECTING, "Reconnecting to Grammarly")
                root = ensure_root(window, args, budget, handle)
                if root is None:
                    break
                policy.clock.progress()
                if control is not None:
                    control.set_state("running")

            chunk = (page - first) // max(1, args.chunk_pages)
            if chunk != current_chunk:
                # Grammarly's own advice for long documents is sections of about fifty pages.
                # Each new chunk starts with a fresh panel, and the caret is put back after.
                current_chunk = chunk
                if chunk > 0:
                    log(f"  p{page}: new {args.chunk_pages}-page section, restarting Grammarly's panel.", handle)
                    if reset_panel(window, handle):
                        root = ensure_root(window, args, budget, handle)
                        if root is None:
                            break
                        session.scroll_to_page(page)
                        session.click_into_page(page)

            scope = scope_for_stop(root, page, pages, session, args.scope_wait)
            if scope is None and page not in reset_tried:
                # Stuck: restart the panel once for this page, then click, nudge and wait again.
                reset_tried.add(page)
                log(f"  p{page}: Grammarly did not follow; restarting its panel.", handle)
                if reset_panel(window, handle):
                    root = ensure_root(window, args, budget, handle)
                    if root is None:
                        break
                    session.scroll_to_page(page)
                    session.click_into_page(page)
                    session.nudge()
                    scope = wait_for_scope(root, page, session, args.scope_wait)
            budget.scope = scope
            budget.publish()  # after the move, so the HUD shows the page Word is on now
            if scope is None:
                # A stale panel reads as "nothing here" and would pass a page unreviewed.
                AUDIT.write("SCOPE_STALE", page=page, seen=read_scope(root, 1.0), retry=page not in retried)
                if page not in retried:
                    retried.add(page)
                    stops.append(page)  # one more try at the end of the pass, when Grammarly has had time
                    log(f"  p{page}: Grammarly did not follow to this page; will try it again at the end of the pass.", handle)
                    continue
                log(f"  p{page}: Grammarly did not follow to this page twice; not counted as clean.", handle)
                budget.mark_inconclusive(f"Grammarly did not follow to page {page}")
                continue

            before_page = budget.accepted
            noeffect_before = budget.noeffect
            text_before = session.text() if session.available else None
            page_start = time.monotonic()
            drain_feed(root, args, session, budget, handle, f"p{page}", window, hwnd, uhandle)
            visited += 1
            took = time.monotonic() - page_start
            if budget.accepted == before_page:
                budget.clean_stops.append(took)
            counted = budget.accepted - before_page
            log(f"  p{page}: {took:.1f}s, {counted} accepted", handle)
            watch_count(session, budget, text_before, page, counted, budget.noeffect - noeffect_before, handle)

        if budget.stop_reason:
            break  # interrupted mid-pass: not a pass, and never clean
        if visited < expected_stops:
            budget.mark_inconclusive("not every page stop was reached")
        # A few pages with no text (pictures, blank pages) are normal. Many
        # means the panel was not reading the document, so the pass proves nothing.
        if len(budget.unread) > max(2, expected_stops // 10):
            budget.mark_inconclusive(f"the panel showed no text on {len(budget.unread)} page stops")

        gained = budget.accepted - before_pass
        record = PassRecord(sweep, gained, conclusive=not budget.inconclusive)
        if gained > 0:
            text = session.text()
            record.text_hash = fingerprint(text) if text is not None else None
        note = "" if record.conclusive else f" (inconclusive: {'; '.join(budget.inconclusive)})"
        log(f"--- pass {sweep} accepted {gained}{note} ---", handle)
        decision = policy.end_of_pass(record)
        if control is not None:
            control.emit("pass", index=sweep, applied=gained, conclusive=record.conclusive)
        if not decision.go_on:
            budget.outcome = decision.outcome
            budget.stop_reason = decision.outcome.reason
            break

    if budget.outcome is None:
        budget.outcome = policy.failed(budget.stop_reason or "the sweep ended")
    if budget.stop_reason:
        log(f"Stopped: {budget.stop_reason}.", handle)
    return budget


def teach_click_target(args) -> None:
    window = find_word_window(args.window)
    activate(window)
    print()
    print("Coordinate teaching mode.")
    print("  1. Make sure a suggestion card is showing in the Grammarly pane.")
    print("  2. Put the mouse pointer on the accept button ('Use this version').")
    print("  3. Do not click. Hold still and wait for the countdown to finish.")
    print()
    for remaining in range(args.teach_delay, 0, -1):
        print(f"  capturing in {remaining}s ", end="\r", flush=True)
        time.sleep(1)
    print(" " * 40, end="\r")

    x, y = auto.GetCursorPos()
    rect = window.BoundingRectangle
    payload = {
        "offset_x": x - rect.left,
        "offset_y": y - rect.top,
        "window_width": rect.width(),
        "window_height": rect.height(),
        "captured": now().isoformat(timespec="seconds"),
    }
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)  # atomic: a half-written target would click into empty space
    print(f"Captured offset ({payload['offset_x']}, {payload['offset_y']}) -> {CONFIG_PATH}")
    print("Re-run teaching if you move or resize the Word window.")


def run_click(args, session: WordSession, handle) -> Budget:
    if not CONFIG_PATH.exists():
        sys.exit("No taught click target. Run with --teach first.")
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    window = find_word_window(args.window)
    activate(window)
    time.sleep(0.4)
    rect = window.BoundingRectangle
    if (rect.width(), rect.height()) != (payload["window_width"], payload["window_height"]):
        log("WARNING: Word window has been resized since teaching.", handle)
        log("         The taught offset may no longer land on the button.", handle)

    budget = Budget(args)
    stalls = 0

    while not budget.exhausted():
        rect = window.BoundingRectangle
        x = rect.left + payload["offset_x"]
        y = rect.top + payload["offset_y"]

        before = session.revision_count()
        auto.Click(x, y, waitTime=0)
        budget.accepted += 1
        time.sleep(args.settle)
        after = session.revision_count()

        if after >= 0 and after == before:
            stalls += 1
            log(f"Click {budget.accepted} produced no revision (stall {stalls}/{args.idle_rounds}).", handle)
            if stalls >= args.idle_rounds:
                log("Document stopped changing. Stopping to avoid blind clicking.", handle)
                break
        else:
            stalls = 0
            # Coordinate mode cannot read the card, so the type is not known here.
            budget.note("Unclassified")
            log(f"Accepted #{budget.accepted} at ({x}, {y}) revisions {before}->{after}", handle)

        count = read_outstanding(window, 1.0)
        if count >= 0:
            budget.outstanding = count
            if budget.baseline < 0:
                budget.baseline = count + 1
        show_status(budget, handle)

    if budget.stop_reason:
        log(f"Stopped: {budget.stop_reason}.", handle)
    return budget


def run_probe(args) -> None:
    """Dump the accessible tree under the Word window. Use this when the uia
    engine finds nothing: the dump shows what the pane actually exposes."""
    window = find_word_window(args.window)
    activate(window)
    time.sleep(0.5)
    out = Path(args.probe_out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.search_budget * 4
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        for node, depth in walk(window, args.max_depth, deadline):
            try:
                rect = node.BoundingRectangle
                geometry = f"({rect.left},{rect.top},{rect.width()}x{rect.height()})"
            except Exception:  # noqa: BLE001
                geometry = "(no rect)"
            try:
                type_name = node.ControlTypeName
            except Exception:  # noqa: BLE001
                type_name = "?"
            handle.write(f"{'  ' * depth}{type_name} '{name_of(node)}' {geometry}\n")
            count += 1
    print(f"Wrote {count} nodes to {out}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Bulk-accept Grammarly suggestions for a document open in Word.",
    )
    parser.add_argument(
        "--engine",
        choices=["uia", "click"],
        default="uia",
        help="uia finds the button by name; click replays a taught position.",
    )
    parser.add_argument("--teach", action="store_true", help="Record the click target and exit.")
    parser.add_argument("--probe", action="store_true", help="Dump the accessible tree and exit.")
    parser.add_argument(
        "--probe-out",
        default=str(DEFAULT_LOG_DIR / "uia-tree.txt"),
        help="Where the probe dump is written.",
    )
    parser.add_argument("--window", default=None, help="Substring of the Word window title.")
    parser.add_argument("--preset", choices=["quick", "standard", "thorough"], default="standard", help="quick is one pass, standard up to four, thorough runs until two clean passes.")
    parser.add_argument("--max-accepts", type=int, default=0, help="Hard cap on accepted cards; 0 means none.")
    parser.add_argument("--time-limit", type=float, default=7200.0, help="Running seconds before the loop stops (paused time excluded); 0 means no limit.")
    parser.add_argument("--barren-limit", type=int, default=4, help="Accepts that change nothing before re-searching.")
    parser.add_argument("--stall-seconds", type=float, default=120.0, help="Running seconds without progress before re-acquiring the panel. Keep below --max-idle-seconds.")
    parser.add_argument("--recover-wait", type=float, default=15.0, help="Seconds between attempts to re-acquire a missing panel.")
    parser.add_argument("--recover-wait-max", type=float, default=120.0, help="Ceiling for the recover-wait backoff.")
    parser.add_argument("--max-idle-seconds", type=float, default=300.0, help="Hard stop after this many running seconds without a real accept or a new page; 0 disables.")
    parser.add_argument("--no-periodic-save", action="store_true", help="Do not save the document every --counter-every accepts.")
    parser.add_argument("--save-before-scroll", action="store_true", help="Also save before every page scroll. Expensive on long documents.")
    parser.add_argument("--keep-markup", action="store_true", help="Leave Word's markup view as it is instead of hiding it for the run.")
    parser.add_argument("--no-wake-lock", action="store_true", help="Do not block system sleep/display-off for the run.")
    parser.add_argument("--counter-every", type=int, default=5, help="Read the panel counter every N accepts.")
    parser.add_argument("--settle", type=float, default=0.7, help="Seconds to wait for the pane to re-render.")
    parser.add_argument("--idle-rounds", type=int, default=3, help="Consecutive empty rounds before stopping.")
    parser.add_argument("--document", default=None, help="Filename fragment picking which open document to work on.")
    parser.add_argument(
        "--allow-window-scope",
        action="store_true",
        help="Search the whole Word window when the pane cannot be found. Unsafe: Word's Review ribbon comes into scope.",
    )
    parser.add_argument(
        "--force-without-com",
        action="store_true",
        help="Run even when Word's automation interface is unreachable, which means no backup and no Track Changes.",
    )
    parser.add_argument("--max-passes", type=int, default=0, help="Override the preset's pass limit; 0 uses the preset.")
    parser.add_argument("--page-step", type=int, default=8, help="Pages advanced per scroll stop. Grammarly reviews ten pages around the caret, so eight overlaps by two.")
    parser.add_argument("--chunk-pages", type=int, default=40, help="Pages per section; Grammarly's panel is restarted between sections.")
    parser.add_argument("--scope-wait", type=float, default=14.0, help="Seconds to wait for Grammarly's panel to follow to a new page.")
    parser.add_argument("--start-page", type=int, default=1, help="First page of the sweep.")
    parser.add_argument("--end-page", type=int, default=0, help="Last page of the sweep; 0 means the end of the document.")
    parser.add_argument("--scroll-settle", type=float, default=1.5, help="Seconds for the pane to re-scope after scrolling.")
    parser.add_argument("--no-sweep", action="store_true", help="Only drain the visible region, do not scroll the document.")
    parser.add_argument("--no-structural", action="store_true", help="Disable Dismiss-sibling discovery of unknown buttons.")
    parser.add_argument("--search-budget", type=float, default=6.0, help="Seconds per tree search.")
    parser.add_argument("--pane-budget", type=float, default=25.0, help="Seconds allowed to confirm the feed is showing.")
    parser.add_argument("--pane-attempts", type=int, default=3, help="Times to activate Word and look for the feed.")
    parser.add_argument("--focus-settle", type=float, default=2.5, help="Seconds after activating Word before reading the panel.")
    parser.add_argument("--max-depth", type=int, default=28, help="Tree depth cap for the search.")
    parser.add_argument("--teach-delay", type=int, default=8, help="Countdown before capturing the cursor.")
    parser.add_argument("--no-backup", action="store_true", help="Skip the backup copy.")
    parser.add_argument("--no-track-changes", action="store_true", help="Same as --track-changes leave.")
    parser.add_argument("--track-changes", choices=["on", "off", "leave"], default="on", help="Set Track Changes before the first click, or leave it as it is.")
    parser.add_argument("--force-focus", action="store_true", help="Always take Word back to the front, even when you switch away on purpose.")
    parser.add_argument("--empty-probe", type=float, default=1.5, help="Seconds to look for cards on a page before calling it empty.")
    parser.add_argument(
        "--log",
        default=str(DEFAULT_LOG_DIR / "grammar-sweeper.log"),
        help="Run log path.",
    )
    return parser.parse_args(argv)


class RunSummary:
    """Everything the finished screen and the command line report need."""

    def __init__(self) -> None:
        self.refused: str | None = None  # why the run never started
        self.document: str | None = None
        self.backup: Path | None = None
        self.budget: Budget | None = None
        self.chars_before = -1
        self.chars_after = -1
        self.log_path: Path | None = None
        self.started: dt.datetime = now()
        self.changes_path: Path | None = None
        self.report_path: Path | None = None
        self.change_count = 0
        self.exports: dict = {}
        self.revisions_before = -1
        self.revisions_after = -1
        self.first_changed_page = -1
        self.finished: dt.datetime | None = None


def refusal_reason() -> str:
    if is_elevated():
        return (
            "This process is running as administrator and Word is not. Windows keeps the two apart, "
            "so Word's documents cannot be reached. Run it from a normal session."
        )
    return "Word's automation interface is unreachable. Check the document is open, saved once, and not in Protected View."


def execute(args, control: RunControl | None = None) -> RunSummary:
    """One complete run: attach, back up, sweep, report. Used by the command
    line and by the interface, so both follow the same rules."""
    summary = RunSummary()
    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    summary.log_path = log_path
    unclassified_path = log_path.with_name(log_path.stem + "-unclassified" + log_path.suffix)

    with log_path.open("a", encoding="utf-8") as handle, \
            unclassified_path.open("a", encoding="utf-8") as uhandle:
        handle.write(json.dumps({"t": now().strftime("%H:%M:%S%z"), "level": "run", "msg": "run started", "at": now().isoformat(timespec="seconds"), "engine": args.engine}) + "\n")
        uhandle.write(f"\n=== run {now().isoformat(timespec='seconds')} ===\n")

        global AUDIT
        AUDIT = Audit(log_path.with_name("audit.log"))
        AUDIT.write("SETTINGS", version=_version(), force_focus=args.force_focus, track_changes=args.track_changes, preset=args.preset)
        AUDIT.watch()

        stamp = now().strftime('%Y%m%d-%H%M%S')
        args.changes_path = log_path.with_name(f'changes-{stamp}.jsonl')
        summary.changes_path = args.changes_path
        text_start = None
        args.run_id = stamp
        args.doc_hash = ""
        args.draft = None
        SWALLOWED.clear()
        session = WordSession(args.document)
        if not session.available and not args.force_without_com:
            # Fail closed. Without COM there is no backup, no Track Changes and
            # no revision count, so a run cannot be verified or undone, and a
            # misdirected click cannot even be detected.
            log("Refusing to run: Word's automation interface is unreachable.", handle)
            log("  Without it there is no backup, no Track Changes, and no way", handle)
            log("  to tell an applied suggestion from a click that did nothing.", handle)
            log(f"  {refusal_reason()}", handle)
            log("  --force-without-com overrides this, unsafely.", handle)
            summary.refused = refusal_reason()
            AUDIT.close()
            return summary
        if session.available:
            summary.document = session.full_name()
            log(f"Document: {summary.document}", handle)
            if not args.no_backup:
                summary.backup = session.backup()
                if summary.backup:
                    log(f"Backup written: {summary.backup}", handle)
                else:
                    log("WARNING: no backup written. The file may be unsaved.", handle)
            mode = "leave" if args.no_track_changes else args.track_changes
            if mode == "on":
                if session.set_track_changes(True):
                    log("Track Changes is ON, but do not rely on it as the undo path.", handle)
                    log("  Grammarly's add-in applies edits that Word does not always record", handle)
                    log("  as revisions. Observed on a long document: text changed while the", handle)
                    log("  revision count stayed at zero. The backup is the undo.", handle)
                else:
                    log("WARNING: could not switch Track Changes on.", handle)
            elif mode == "off":
                if session.set_track_changes(False):
                    log("Track Changes is OFF. Accepted cards overwrite text directly; the backup is the undo.", handle)
                else:
                    log("WARNING: could not switch Track Changes off.", handle)
            else:
                log("Track Changes left as it was.", handle)
            summary.chars_before = session.char_count()
            text_start = session.text()
            if text_start:
                import hashlib

                args.doc_hash = hashlib.sha256(text_start.encode("utf-8")).hexdigest()[:12]
            args.draft = session.custom_property("GS_Draft")
            summary.revisions_before = session.revision_count()
            log(f"Starting revision count: {summary.revisions_before}, characters: {summary.chars_before}", handle)

        load_learned_names(handle)
        log("Loop starting. Hold ESC to stop.", handle)
        if not args.no_wake_lock:
            prevent_sleep()
            log("Sleep and display-off are blocked for this process. Idle screen-lock is a", handle)
            log("  separate Windows policy and is not blocked by this.", handle)
        time.sleep(1.0)

        budget = None
        try:
            if args.engine == "uia":
                # An interface thread has no COM apartment of its own.
                with auto.UIAutomationInitializerInThread():
                    budget = run_uia(args, session, handle, uhandle, control)
            else:
                budget = run_click(args, session, handle)
        except Exception:  # noqa: BLE001 - a crash here must still report state
            import traceback

            log("CRASHED. Full traceback follows; the state below is as of the crash.", handle)
            for line in traceback.format_exc().splitlines():
                log(f"  {line}", handle)
            if budget is None:
                budget = Budget(args, control=control)
                budget.abort("the program hit an unexpected error")
        finally:
            if not args.no_wake_lock:
                allow_sleep()
            try:
                session.restore_markup()
            except Exception:  # noqa: BLE001
                pass
            AUDIT.close()

        summary.budget = budget
        summary.finished = now()
        if SWALLOWED:
            totals = ", ".join(f"{k} {v}" for k, v in sorted(SWALLOWED.items()))
            log(f"Errors caught and carried past: {totals}", handle)
            AUDIT.write("SWALLOWED_TOTALS", **{k.replace('-', '_'): v for k, v in SWALLOWED.items()})
        print()  # close off the in-place status line
        log(f"Done. Accepted {budget.accepted} suggestion(s).", handle)
        log(f"By type: {budget.breakdown()}", handle)
        method_parts = ", ".join(f"{k} {v}" for k, v in sorted(budget.by_method.items())) or "none"
        log(f"By invoke method: {method_parts}", handle)
        outcome = budget.outcome
        if outcome is not None:
            log(f"Result: {outcome.result}. {outcome.reason}. Suggestions {outcome.remaining}.", handle)
        if budget.outstanding > 0:
            log(f"Still showing in the pane at the last reading: {budget.outstanding}", handle)
        elif budget.outstanding == 0:
            log("Pane reported nothing outstanding at the last reading.", handle)
        else:
            log("Pane suggestion counter could not be read; outstanding is Unknown.", handle)
        if session.available:
            summary.chars_after = session.char_count()
            summary.revisions_after = session.revision_count()
            log(f"Final revision count: {summary.revisions_after}, characters: {summary.chars_after}", handle)
            log("If the revision count did not move, the edits are untracked and the", handle)
            log("backup written at the start of this run is the only way back.", handle)
            if budget.changes is not None:
                budget.changes.close()
                records = budget.changes.records
                summary.change_count = len(records)
                log(f"Recorded {len(records)} change(s) with their before and after text.", handle)
                log(f"  Capture added {budget.capture_seconds:.1f}s to the run.", handle)
                summary.report_path = log_path.with_name(f'report-{stamp}.html')
                try:
                    build_report(summary.report_path, {'Document': Path(summary.document or '').name,
                                 'Run': stamp, 'Document hash': args.doc_hash, 'Draft': args.draft if args.draft is not None else 'not set',
                                 'Applied': budget.accepted, 'Words': budget.total_words, 'Types': budget.breakdown()},
                                 records)
                    exports = write_exports(log_path.parent, stamp, records)
                    summary.exports = exports
                    log(f"Rule exports: {', '.join(p.name for p in exports.values())}", handle)
                    log(f"Report: {summary.report_path}", handle)
                except Exception as exc:  # noqa: BLE001 - a report failure must not hide the result
                    log(f"WARNING: could not write the report ({exc}).", handle)
                    summary.report_path = None
                pages = [r['page'] for r in records if isinstance(r.get('page'), int) and r['page'] > 0]
                if pages:
                    summary.first_changed_page = min(pages)
                    session.scroll_to_page(summary.first_changed_page)

    return summary


def main(argv=None) -> int:
    args = parse_args(argv)
    auto.SetGlobalSearchTimeout(2)

    if args.probe:
        run_probe(args)
        return 0
    if args.teach:
        teach_click_target(args)
        return 0

    summary = execute(args)
    return 2 if summary.refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
