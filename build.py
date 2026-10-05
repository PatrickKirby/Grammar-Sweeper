"""Build the exe into dist\\, the one build folder, stamped with the version and commit.

Run from the project root: python build.py. The stamp is written to
sweeper\\_build_info.py (gitignored) before PyInstaller runs and removed after, so
a source run never reads a stale stamp."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAMP = ROOT / "sweeper" / "_build_info.py"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    commit = git("rev-parse", "--short", "HEAD") + ("-dirty" if git("status", "--porcelain") else "")
    built = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    STAMP.write_text(f'VERSION = "{version}"\nCOMMIT = "{commit}"\nBUILT = "{built}"\n', encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "grammar-sweeper.spec", "--noconfirm", "--distpath", "dist", "--workpath", "build"],
            cwd=ROOT,
        )
    finally:
        STAMP.unlink(missing_ok=True)
    print(f"built {version} ({commit}) at {built}" if result.returncode == 0 else "build failed")
    if result.returncode == 0:
        return installer(version)
    return result.returncode


def installer(version: str) -> int:
    """Wrap dist\\Grammar Sweeper into dist\\grammar-sweeper-setup.exe with Inno Setup, when it is installed."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    compiler = next((path for path in candidates if path.exists()), None)
    if compiler is None:
        print("installer skipped: Inno Setup 6 is not installed")
        return 0
    result = subprocess.run([str(compiler), f"/DAppVersion={version}", "installer\\GrammarSweeper.iss"], cwd=ROOT)
    if result.returncode != 0:
        print("installer failed")
        return result.returncode
    # The installer is the product. Its input folder and PyInstaller's work folder are scratch, so remove them.
    shutil.rmtree(ROOT / "dist" / "Grammar Sweeper", ignore_errors=True)
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    print("installer built: dist\\grammar-sweeper-setup.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
