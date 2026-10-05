# Contributing

## Before you start

Open an issue first for anything beyond a small fix, so the approach is agreed before you spend time on it.

Grammar Sweeper is Windows only. It needs desktop Microsoft Word with the Grammarly add-in, and Python 3.10 or later.
A change that adds another platform, another word processor, or another suggestion engine is a larger discussion. Open
an issue before writing code.

## Setting up

```
pip install -r requirements.txt pytest ruff
python -m pytest
ruff check .
```

Run from a normal, non-elevated shell. The suite never touches Word or Grammarly, and the GUI tests build offscreen,
so it runs on a machine with neither installed.

## Building the installer

`python build.py` builds the program with PyInstaller, then wraps it in `dist\grammar-sweeper-setup.exe` when
[Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed. The installer does not bundle Qt or Pillow. It downloads
`PySide6_Essentials`, `shiboken6` and `Pillow` from PyPI, pinned in `installer/runtime.inc`, and keeps the files listed in
`installer/runtime-files.txt`. After changing the PySide6 or Pillow version, run `python installer/pin_runtime.py`, check that the
program still starts from an installed copy, and rebuild. `docs/dependencies/` holds the dependency diagram. Edit
`dependencies.architecture.json` and regenerate it with Archify when a dependency changes.

## Bug reports

Include:

- Windows version and Python version (`python --version`)
- Word version and Grammarly add-in version
- What you picked on the setup page (preset, pages, Track Changes) or the exact command you ran
- The summary from the finished page (Copy summary)
- The audit log, if the run stopped or Word lost focus (Advanced tab, Open audit log)

Check screenshots and logs for document text before you attach them. Do not attach a document you cannot share.

## Code style

[Ruff](https://docs.astral.sh/ruff/) lints, configured in `pyproject.toml`. Run it before opening a PR. CI runs Ruff
and the tests on a Windows runner.

Pure logic lives in `sweeper/` and is tested without a window. UI Automation and click code is exercised by hand
against real documents, so say in the PR what you ran it against. `docs/spec.md` describes behaviour. Change it in the
same PR as the behaviour.

## License

By contributing, you agree your contribution is licensed under this project's MIT license.
