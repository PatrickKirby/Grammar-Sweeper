"""Wait for the Grammarly assistant to be expanded, then run the accept loop.

The assistant is only present while Word is the foreground window, and it
cannot be expanded by a synthetic click, so the sequence has to be: a person
expands it, Word keeps focus, and this picks up the moment the feed is visible.

Polls without stealing focus. Prints what it sees each second so a run that
never starts says why.
"""

from __future__ import annotations

import sys
import time

import uiautomation as auto

import bulk_accept as ba


def main(timeout: float = 90.0, doc: str = "Delivery Plan") -> int:
    auto.SetGlobalSearchTimeout(2)
    args = ba.parse_args(["--max-accepts", "2", "--no-sweep", "--document", doc])

    print(f"Watching for the assistant for up to {int(timeout)}s.")
    print("Expand the Grammarly panel in Word and leave Word focused.")

    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        pane = ba.find_pane(None, args.max_depth, 1.5)
        if pane is None:
            state = "no assistant window (Word is not the foreground window)"
        else:
            # Count what the subtree exposes. Collapsed it is a handful of nodes
            # and the walk returns instantly; expanded it is thousands, so this
            # doubles as the openness test and costs nothing while waiting.
            nodes = 0
            rows = 0
            for node, _ in ba.walk(pane, 32, time.monotonic() + 25):
                nodes += 1
                try:
                    if node.ControlTypeName != "ButtonControl":
                        continue
                except Exception:  # noqa: BLE001 - stale node
                    continue
                label = ba.name_of(node)
                if ba.ROW_MARKER in label or any(a in label for a in ba.ACCEPT_NAMES):
                    rows += 1
            if rows:
                print(f"\nFeed is visible: {rows} actionable control(s) across {nodes} nodes.")
                return run_accept(args)
            state = f"assistant collapsed ({nodes} nodes exposed, no suggestion rows)"
        if state != last:
            print(f"  {state}")
            last = state
        time.sleep(1.0)

    print("Timed out. The feed never became visible.")
    return 1


def run_accept(args) -> int:
    from pathlib import Path

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        session = ba.WordSession(args.document)
        if not session.available:
            print("COM unavailable, refusing to click.")
            return 2
        backup = session.backup()
        print(f"Backup: {backup}")
        print(f"Track Changes on: {session.enable_track_changes()}")
        print(f"Revisions before: {session.revision_count()}")
        ba.load_learned_names(handle)
        budget = ba.run_uia(args, session, handle)
        print()
        print(f"Accepted: {budget.accepted}")
        print(f"By type: {budget.breakdown()}")
        print(f"Revisions after: {session.revision_count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 90.0))
