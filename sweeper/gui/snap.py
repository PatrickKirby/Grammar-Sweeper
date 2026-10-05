"""Lay the screen out as the app locked to the left and Word filling the rest, and keep it so.

Plain Win32 calls. The work area excludes the taskbar, and the process is
per-monitor DPI aware under Qt, so every figure here is in physical pixels.

Windows 10 and 11 give a window an invisible resize border, so the rectangle
SetWindowPos sets is wider than the one the eye sees. Every placement here
targets the visible frame and reads it back; a placement is only reported as
done once the frame is where it was asked to be."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Callable

from sweeper import winfocus

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
SPI_GETWORKAREA = 0x0030
SM_CMONITORS = 80
SW_SHOWNORMAL = 1
SW_RESTORE = 9
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
DWMWA_EXTENDED_FRAME_BOUNDS = 9
WORD_CLASS = "OpusApp"
APP_FRACTION = 0.32  # share of the work width the app takes
TOLERANCE = 3  # pixels a frame may sit off its target and still count as placed
ATTEMPTS = 3
START_WAIT = 25.0  # seconds Word gets to show a window after it is started

Rect = tuple[int, int, int, int]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def work_area() -> Rect:
    rect = wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def screen_signature() -> str:
    """Names the monitor setup, so a layout is remembered per setup."""
    left, top, right, bottom = work_area()
    return f"{user32.GetSystemMetrics(SM_CMONITORS)}:{right - left}x{bottom - top}"


def app_width(minimum: int) -> int:
    left, _top, right, _bottom = work_area()
    return max(minimum, int((right - left) * APP_FRACTION))


def window_rect(hwnd: int) -> Rect:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def frame_rect(hwnd: int) -> Rect:
    """The rectangle the eye sees, without the invisible resize border."""
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        return window_rect(hwnd)
    return rect.left, rect.top, rect.right, rect.bottom


def compensate(outer: Rect, frame: Rect, target: Rect) -> Rect:
    """The window rectangle that puts the visible frame on `target`."""
    return (
        target[0] - (frame[0] - outer[0]),
        target[1] - (frame[1] - outer[1]),
        target[2] + (outer[2] - frame[2]),
        target[3] + (outer[3] - frame[3]),
    )


def within(frame: Rect, target: Rect) -> bool:
    return all(abs(a - b) <= TOLERANCE for a, b in zip(frame, target))


def find_word(fragment: str | None) -> int:
    """The visible Word window whose title contains `fragment`; any Word window when
    no fragment is given. A fragment that matches nothing returns 0, because
    placing some other document's window is worse than placing none."""
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == WORD_CLASS:
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            found.append((hwnd, title.value))
        return True

    user32.EnumWindows(visit, 0)
    if fragment:
        for hwnd, title in found:
            if fragment.lower() in title.lower():
                return hwnd
        return 0
    return found[0][0] if found else 0


def _place_by_size(hwnd: int, target: Rect) -> bool:
    for _ in range(ATTEMPTS):
        left, top, right, bottom = compensate(window_rect(hwnd), frame_rect(hwnd), target)
        user32.SetWindowPos(hwnd, HWND_TOP, left, top, right - left, bottom - top, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        if within(frame_rect(hwnd), target):
            return True
    return False


def _place_by_placement(hwnd: int, target: Rect) -> bool:
    """The second route: set the restored position directly. It reaches windows that
    take no notice of SetWindowPos, such as one that is maximised or snapped."""
    plan = WINDOWPLACEMENT()
    plan.length = ctypes.sizeof(plan)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(plan)):
        return False
    left, top, right, bottom = compensate(window_rect(hwnd), frame_rect(hwnd), target)
    plan.showCmd = SW_SHOWNORMAL
    plan.rcNormalPosition = wintypes.RECT(left, top, right, bottom)
    user32.SetWindowPlacement(hwnd, ctypes.byref(plan))
    return within(frame_rect(hwnd), target)


def place(hwnd: int, target: Rect) -> bool:
    """Put a window's visible frame on `target`, raised so it cannot sit hidden behind
    another window. True only when the frame was read back in place."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)  # a maximised window ignores a new size
    return _place_by_size(hwnd, target) or _place_by_placement(hwnd, target)


def foreground(hwnd: int) -> bool:
    """Bring a window to the front and say whether it got there. Windows refuses a
    plain SetForegroundWindow from a background process, so this is the forced
    method in winfocus, the same one the engine uses."""
    return winfocus.force_foreground(hwnd)


def word_target(width: int) -> Rect:
    left, top, right, bottom = work_area()
    return left + width, top, right, bottom


def app_target(width: int) -> Rect:
    left, top, _right, bottom = work_area()
    return left, top, left + width, bottom


def grammarly_window() -> int:
    """Grammarly's assistant panel: the visible top-level window titled Grammarly that is
    big enough to be the review panel, not the small desktop widget."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, title, 64)
        if title.value.strip().lower() == "grammarly":
            left, top, right, bottom = frame_rect(hwnd)
            if right - left >= 200 and bottom - top >= 250:
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def dock_above_grammarly(height: int) -> Rect | None:
    """Make room for a toaster of `height` directly above Grammarly's panel and return
    where it goes: the panel's own width and left edge, the top of the work area. The
    panel is moved down and shortened to fit beneath it. None when the panel is not
    showing, or would not move."""
    panel = grammarly_window()
    if not panel:
        return None
    left, top, right, bottom = work_area()
    below = (frame_rect(panel)[0], top + height, frame_rect(panel)[2], bottom)
    if not within(frame_rect(panel), below) and not place(panel, below):
        return None
    return below[0], top, below[2], top + height


def place_word(document: str | None, width: int, front: bool = False) -> bool:
    """Word fills the area to the right of the app. False when Word was not found,
    was not read back in place, or was asked to the front and did not get there."""
    word = find_word(document)
    if not word or not place(word, word_target(width)):
        return False
    return foreground(word) if front else True


class PaneKeeper:
    """Holds Word in the right pane and the app in the left for as long as it is ticked.

    Each tick is cheap when both are already in place. Word that is not open is
    started with the document, once, and given START_WAIT seconds to show. A
    change of state goes to `note`, a repeat of the same state does not."""

    def __init__(
        self,
        width: Callable[[], int],
        document: Callable[[], str | None],
        app_hwnd: Callable[[], int],
        note: Callable[..., None],
    ) -> None:
        self._width = width
        self._document = document  # path of the document, or None
        self._app_hwnd = app_hwnd
        self._note = note
        self._state = ""
        self._started_at = 0.0

    def _report(self, state: str, **data) -> str:
        if state != self._state:
            self._state = state
            self._note("GUI_PANE", state=state, **data)
        return state

    def _start_word(self, path: str) -> str:
        now = time.monotonic()
        if not self._started_at:
            self._started_at = now
            try:
                os.startfile(path)
            except OSError as exc:
                self._started_at = -1.0
                return self._report("cannot-start", path=path, error=repr(exc))
            return self._report("starting", path=path)
        if self._started_at < 0:
            return self._report("cannot-start", path=path)
        if now - self._started_at < START_WAIT:
            return self._report("starting", path=path)
        return self._report("no-window", path=path)

    def tick(self, app_visible: bool = True, start: bool = False) -> str:
        """One enforcement pass. Returns the state: placed, starting, cannot-start,
        no-window, no-document, or off-target (with the measured frame in the audit
        entry). Word is started only when `start` is set or a start is under way, so
        closing Word on purpose does not bring it back."""
        width = self._width()
        app = self._app_hwnd()
        if app_visible and app and not within(frame_rect(app), app_target(width)):
            place(app, app_target(width))  # the app is locked to its pane whatever Word is doing
        path = self._document()
        if not path:
            return self._report("no-document")
        word = find_word(os.path.splitext(os.path.basename(path))[0])
        if not word:
            if start or self._started_at:
                return self._start_word(path)
            return self._report("no-window", path=path)
        self._started_at = 0.0
        target = word_target(width)
        if not within(frame_rect(word), target) and not place(word, target):
            return self._report("off-target", frame=frame_rect(word), target=target)
        return self._report("placed")


def snap(app_hwnd: int, document: str | None, minimum: int) -> bool:
    """App takes the left panel, Word the rest. Word is placed first and the app
    last, so the app ends up on top of its own panel."""
    width = app_width(minimum)
    found = place_word(document, width)
    place(app_hwnd, app_target(width))
    return found
