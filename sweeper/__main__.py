import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sweeper.gui.main_window import run  # noqa: E402

raise SystemExit(run())
