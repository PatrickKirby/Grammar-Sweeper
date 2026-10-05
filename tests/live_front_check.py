"""Live check, needs Word open: does the interface's own resume path bring Word to the front
while another program holds it? Run by hand: python tests/live_front_check.py"""

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from sweeper.gui import main_window  # noqa: E402
from sweeper.settings import Settings  # noqa: E402

u = ctypes.windll.user32


def title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(100)
    u.GetWindowTextW(hwnd, buf, 100)
    return buf.value[:45]


app = QApplication([])
win = main_window.MainWindow(Settings(Path(os.environ["TEMP"]) / "front-check.json"), True)
win.show()
notepad = subprocess.Popen(["notepad.exe"])
time.sleep(2)
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)
print("foreground before:", title(u.GetForegroundWindow()))
print("_word_to_front returned:", win._word_to_front())
print("fg immediately:", title(u.GetForegroundWindow()))
for i in range(30):
    app.processEvents()
    time.sleep(0.05)
    if i % 5 == 0:
        print(i, "fg:", title(u.GetForegroundWindow()))
print("foreground after:", title(u.GetForegroundWindow()))
notepad.terminate()
