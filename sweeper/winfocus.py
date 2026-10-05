"""Take the foreground when another program holds it.

Windows refuses SetForegroundWindow from a background process, and
uiautomation's SetActive is that same call, so it silently fails while
Grammarly's panel window is in front. Seen live: four take-backs in a row did
nothing and the run sat held until the person clicked Word themselves.

The approach is the usual one: share input state with the thread that owns the
foreground, allow the call, raise through the topmost list, and verify."""

from __future__ import annotations

import ctypes
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
ASFW_ANY = -1


def panel_visible() -> bool:
    """Whether Grammarly's review panel is showing: a visible window titled Grammarly that
    is panel sized, not the small desktop widget."""
    from ctypes import wintypes

    seen: list[bool] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        if user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, title, 64)
            if title.value.strip().lower() == "grammarly":
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if rect.right - rect.left >= 200 and rect.bottom - rect.top >= 250:
                    seen.append(True)
        return True

    user32.EnumWindows(visit, 0)
    return bool(seen)


def foreground_is(hwnd: int) -> bool:
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def force_foreground(hwnd: int, attempts: int = 3) -> bool:
    """True once `hwnd` is the foreground window."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if foreground_is(hwnd):
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    for _ in range(attempts):
        current = user32.GetForegroundWindow()
        mine = kernel32.GetCurrentThreadId()
        theirs = user32.GetWindowThreadProcessId(current, None) if current else 0
        attached = bool(theirs and theirs != mine and user32.AttachThreadInput(mine, theirs, True))
        try:
            user32.AllowSetForegroundWindow(ASFW_ANY)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if not foreground_is(hwnd):
                user32.SwitchToThisWindow(hwnd, True)
        finally:
            if attached:
                user32.AttachThreadInput(mine, theirs, False)
        time.sleep(0.1)
        if foreground_is(hwnd):
            return True
    return False
