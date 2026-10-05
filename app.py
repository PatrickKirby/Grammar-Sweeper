import os
import sys
from pathlib import Path

# The installer downloads the Qt runtime and Pillow (PySide6, shiboken6 and PIL, from PyPI) into runtime\ beside the program, so it is not
# part of the file shipped on GitHub. A source run has PySide6 installed normally and has no such folder.
_runtime = Path(sys.executable).parent / "runtime"
if getattr(sys, "frozen", False) and _runtime.is_dir():
    sys.path.insert(0, str(_runtime))
    # Qt's extension modules need python3.dll, which sits with the bundled Python. Windows looks for an extension's
    # dependencies only in registered folders, so register it before Qt loads.
    os.add_dll_directory(sys._MEIPASS)

from sweeper.gui.main_window import run  # noqa: E402

raise SystemExit(run())
