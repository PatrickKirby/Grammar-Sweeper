"""Read-only probe of the Grammarly assistant window.

Opens the assistant and one suggestion card, then prints every control it
exposes. Opening a card does not change the document; nothing else is invoked.

Findings this drives, recorded here because they are not documented anywhere:

  - The assistant is a top-level window of Grammarly.Desktop, not a child of the
    Word window, and it carries AutomationId GrammarlyAssistantWindow.
  - It only exists while Word is the foreground window.
  - Its Name is sometimes a live status string ("20 suggestions") and sometimes
    blank, so the AutomationId is the only stable handle.
  - Collapsed, it exposes just "open grammarly assistant".
  - Open, the feed lists each suggestion as a button whose label ends in
    "open suggestion card" and begins with the suggestion type.
  - The accept control exists only inside an expanded card.
"""

from __future__ import annotations

import time

import uiautomation as auto

import bulk_accept as ba

PANE_AUTOMATION_ID = "GrammarlyAssistantWindow"
OPEN_ASSISTANT = "open grammarly assistant"
ROW_MARKER = "open suggestion card"


def focus_word(title: str | None = None) -> bool:
    try:
        word = auto.WindowControl(searchDepth=1, ClassName="OpusApp", SubName=title or "")
        if not word.Exists(maxSearchSeconds=3):
            print("Word window not found.")
            return False
        word.SetActive()
        time.sleep(1.0)
        return True
    except Exception as exc:  # noqa: BLE001 - Word closed mid-call
        print(f"Could not activate Word ({exc}).")
        return False


def find_pane(retries: int = 6):
    """By AutomationId. Name is unreliable and geometry is a coincidence."""
    for _ in range(retries):
        for child in auto.GetRootControl().GetChildren():
            try:
                if child.AutomationId == PANE_AUTOMATION_ID:
                    return child
            except Exception:  # noqa: BLE001 - window closed mid-enumeration
                continue
        time.sleep(0.5)
    return None


def buttons_in(pane, seconds: float = 20.0):
    out = []
    deadline = time.monotonic() + seconds
    for node, depth in ba.walk(pane, 32, deadline):
        try:
            if node.ControlTypeName != "ButtonControl":
                continue
            label = ba.name_of(node)
            if label:
                out.append((depth, label, node))
        except Exception:  # noqa: BLE001 - stale node
            continue
    return out


def main() -> int:
    auto.SetGlobalSearchTimeout(2)
    if not focus_word():
        return 1
    pane = find_pane()
    if pane is None:
        print(f"No window with AutomationId {PANE_AUTOMATION_ID}. Is Grammarly running?")
        return 1
    rect = pane.BoundingRectangle
    print(f"PANE pid={pane.ProcessId} {rect.width()}x{rect.height()} at ({rect.left},{rect.top})")

    found = buttons_in(pane, 12)
    print(f"collapsed state: {len(found)} button(s)")
    opener = next((n for _, label, n in found if OPEN_ASSISTANT in label), None)
    if opener is not None:
        print("opening the assistant")
        try:
            opener.GetInvokePattern().Invoke()
        except Exception:  # noqa: BLE001 - no invoke pattern, click instead
            opener.Click(waitTime=0)
        time.sleep(2.5)

    found = buttons_in(pane, 20)
    rows = [(d, label, n) for d, label, n in found if ROW_MARKER in label]
    print(f"open state: {len(found)} button(s), {len(rows)} suggestion row(s)")
    for _, label, _ in found[:12]:
        print(f"  {label[:72]!r}")

    if rows:
        depth, label, row = rows[0]
        print(f"\nopening first row: {label[:70]!r}")
        try:
            row.GetInvokePattern().Invoke()
        except Exception:  # noqa: BLE001
            row.Click(waitTime=0)
        time.sleep(2.5)

        print("\n--- controls with a card open ---")
        for d, name, node in buttons_in(pane, 20):
            if ROW_MARKER in name:
                continue
            box = node.BoundingRectangle
            print(f"  d{d:2} {name[:70]!r} ({box.left},{box.top}) {box.width()}x{box.height()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
