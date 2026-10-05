# Grammar Sweeper: user manual

For a short introduction and the installer, see [README.md](README.md). For the command-line engine, see [docs/developer.md](docs/developer.md). This manual covers the window: setting
up a run, watching it, reading the summary, and looking after the files it leaves behind. Behaviour rules are in
[docs/spec.md](docs/spec.md).

## Contents

- [What it does](#what-it-does)
- [Read this first](#read-this-first)
- [Requirements](#requirements)
- [Installing and starting](#installing-and-starting)
- [Setting up a run](#setting-up-a-run)
- [While it runs](#while-it-runs)
- [Reading the summary](#reading-the-summary)
- [Recent runs and Resume](#recent-runs-and-resume)
- [The Advanced tab](#the-advanced-tab)
- [Where files go](#where-files-go)
- [Troubleshooting](#troubleshooting)
- [Limits](#limits)
- [Building the program](#building-the-program)

## What it does

Grammarly's panel in Word lists suggestions one card at a time. A long document can carry thousands. Grammar Sweeper
clicks the accept control on each card for you, walking the document page by page, until a full pass finds nothing
left.

It is unofficial and unaffiliated with Grammarly. It automates Grammarly's interface, because Grammarly publishes no
way to apply suggestions in bulk.

## Read this first

- **It applies suggestions without showing them to you.** Rewrite cards restructure sentences. Review the document
  afterwards.
- **The backup is your undo.** Grammarly's edits are often not recorded by Word's Track Changes. Before the first
  click the tool saves a timestamped copy of the document beside the original. Keep it until you are happy with the
  result.
- **Documents on SharePoint or OneDrive can be swept, but no backup copy can be made of them.** Make your own copy
  first.
- **Whether this breaches Grammarly's terms is for you to check.** Use it on your own account, at your own risk.
- No warranty. See [LICENSE](LICENSE).

The first launch shows these points on a notice. Tick "I understand, and I want to continue" to go on. Tick "Don't show
this again" to skip the notice later.

## Requirements

- 64-bit Windows.
- Desktop Microsoft Word, with Grammarly's add-in installed in Word and signed in.
- An internet connection while setup runs. After setup the program needs none.
- Python 3.10 or later, only if you run from source. The installer does not need it.
- Run it from a normal shell, never as administrator. Windows keeps UI Automation separate by privilege level, so an
  elevated process cannot reach a normal Word.

## Installing and starting

### With the installer

1. Download `grammar-sweeper-setup.exe` from the Releases page and run it. No administrator rights are needed.
   It is unsigned, so Windows SmartScreen may warn on first run. Choose More info, then Run anyway.
2. Follow the wizard. After you press Install, setup shows a progress page while it downloads Qt and Pillow from PyPI,
   then unpacks them and finishes. It needs an internet connection for this step only.
3. Start Grammar Sweeper from the Start menu, or from the desktop shortcut if you ticked that option.

Setup installs by default into a folder under `%LOCALAPPDATA%\Programs`, and you can choose another folder in the wizard.
If a download fails, setup stops and installs nothing.

![What grammar-sweeper-setup.exe carries, what it downloads from PyPI, and what you must already have](docs/dependencies/dependencies.png)

The [README](README.md#what-is-inside-and-what-setup-downloads) lists every part, its version, its size and its licence.

### From source

```
pip install -r requirements.txt
python -m sweeper
```

You can also double-click `grammar_sweeper.pyw`. If you see `Missing dependency` on startup although `pip list` looks
right, the packages are in a different Python than the one you ran. Check which with
`python -c "import sys; print(sys.executable)"`.

## Setting up a run

1. Open the document in Word.
2. Open Grammarly's panel in Word, so the suggestion list is showing.
3. Open Grammar Sweeper. On the **Setup** tab:

| Control | What it does |
|---|---|
| Document | The Word documents open now. Pick one. Press **Refresh** after opening another. |
| How thorough | **Quick** walks the document once. **Standard** walks it up to four times and stops early after two walks in a row find nothing. **Thorough** keeps going until two in a row find nothing, for two hours at most. |
| Pages | The whole document, or only the pages you type in. The page count of the chosen document shows under the picker. |
| Track Changes | Switches Word's Track Changes on, off, or leaves it. Do not rely on it as an undo. |
| Always return to Word, even if I switch away | Takes Word back to the front whenever something steals focus. Off by default, so a deliberate switch pauses the run instead. |
| Open the report when the run ends | Opens the HTML report on the finished page. |

4. Press **Start**. It first checks that Grammarly's assistant is open in Word and showing suggestions. If it is not,
   nothing runs and the setup page says why.

The **?** button on the setup page opens a short help for the same controls.

### What it accepts

Corrections, clarity and engagement suggestions, including Rephrase on rewrite cards. It never accepts a tone change
such as "Want to sound friendlier?", and it never dismisses anything.

## While it runs

The window hides and a small panel sits above Grammarly's. Word must stay in front, because Grammarly's panel stops
drawing otherwise.

| Control | Effect |
|---|---|
| Pause / Resume | Holds the run. Resume puts Word back in front and carries on. |
| Stop | Ends the run and goes to the summary. |
| `Esc` | Same as Stop, from anywhere. |

The panel turns amber when the run is waiting for you, for example after you switch to another program or another
document. The run never clicks while a wrong window is in front. Put Word back, or press Resume.

A run also stops by itself when a pass limit is reached, when the time limit passes, when it goes five minutes without
a real accept, or when it detects it is repeating itself. The summary says which.

## Reading the summary

The finished page opens when a run ends. The **?** button explains each part. In short:

- **Banner.** Green: finished and nothing was left. Violet: suggestions may remain, because the run hit its pass limit
  or Grammarly began undoing its own changes. Red: the run could not continue.
- **Tiles.** Suggestions applied, by Grammarly's four types, plus any the tool could not classify.
- **Your time.** The time by hand at eight seconds a suggestion, the time the run took, and the difference.
- **Passes.** A pass is one walk through the whole document. A pass that applies changes is where the work happened.
  Passes that find nothing are checks, because Grammarly can reveal new suggestions once earlier ones are applied.
- **Where it changed.** One block per page. Colour is the commonest kind of change on that page, grey means nothing
  changed, and an outline means Grammarly could not read the page. Hover for a short summary.
- **Backup.** The pre-run copy of the document.

Buttons: **Open document**, **Open backup folder**, **Open report** (every change with its before and after text),
**Copy summary** (plain text to the clipboard), **Resume** (only after a run stopped partway), and **Run again**.

## Recent runs and Resume

The **Recent runs** tab lists the last 20 runs. Each row links to the document, the backup folder and the report, shows
the figures for the run, and draws a sparkline of changes per page across the document. A run that stopped partway offers **Resume** on its summary, which carries on from the page it reached.

## The Advanced tab

| Control | Use |
|---|---|
| Open logs folder, Open audit log, Open screenshots | Read what happened. The audit log records every change of the front window, which program owns it, and each focus decision. |
| Copy diagnostics | Bundles logs and screenshots for a bug report. Check it for document text before you share it. |
| Delete selected | Deletes screenshots, audit and run logs, reports and diagnostic bundles, filtered by age. Tick what to delete first. Each name has an Open link to its file or folder. |
| Delete change records and rule files | Deletes the per-run change records and rule files, which are kept separately. It has its own Open link. |

Deleting here never touches backups of your documents, your settings, or the run history.

## Where files go

| What | Where |
|---|---|
| Backup of the document | Beside the document, as `<name>.backup-<timestamp>.<ext>` |
| Settings | `%APPDATA%\Grammar Sweeper\settings.json` |
| Logs, reports, screenshots | `%APPDATA%\Grammar Sweeper\logs\` (screenshots in `shots\`) |
| Diagnostic bundles | `%APPDATA%\Grammar Sweeper\diagnostics\` |
| The program and its runtime (Qt, Pillow) | The install folder; Qt is in its `runtime` subfolder |

Screenshots and reports can contain text from your document.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Start says Grammarly's panel is not open | Open Grammarly's assistant in Word so its suggestion list shows, leave Word focused, and press Start again. |
| `Missing dependency` on startup, running from source | The packages are in another Python. Run `pip install -r requirements.txt` with the interpreter you start from. |
| Setup says the runtime could not be downloaded | Setup needs to reach `files.pythonhosted.org`. Check the internet connection, any proxy or firewall, then run setup again. Nothing is installed after a failed download. |
| Setup stops with a download error that mentions a hash or checksum | The file was not what the installer expects, so setup rejected it. Run setup again; if it repeats, report it under the project's security policy. |
| Setup says the runtime could not be unpacked, or the program will not start after install | Run `grammar-sweeper-setup.exe` again over the same folder. If you deleted or moved the `runtime` folder, setup restores it. |
| Word cannot be found or driven | Close the tool and start it from a normal, non-elevated shell. |
| The run pauses and the panel is amber | Another program or document took the front. Put Word back, or press Resume. |
| The run stops early with suggestions left | The pass or time limit was reached. Choose Thorough, or press Resume if it offers it. |
| Every card reports Unclassified | Grammarly changed its card headings. Accepts still apply; only the tally is affected. |
| Nothing is accepted and the run reports empty feeds | The panel exposes no accessible controls. Use the command-line `--probe` described in the [developer guide](docs/developer.md#when-the-uia-engine-finds-nothing). |

## Limits

- Windows only. The engine depends on UI Automation, COM and the Win32 API.
- It depends on Grammarly's current interface. A redesign can break it.
- Each accept writes to the live document while Grammarly is also editing it.
- An accept that swaps text for text of the same length reads as "changed nothing", so it can be miscounted. A repeat
  guard stops it looping.
- There is no reliable undo except the backup.

## Building the program

```
python build.py
```

This builds the program into `dist\Grammar Sweeper\`, stamped with the version and the commit, and needs PyInstaller. If
[Inno Setup 6](https://jrsoftware.org/isinfo.php) is installed it then wraps that folder into
`dist\grammar-sweeper-setup.exe`, a per-user installer that needs no administrator rights. That one file is
what to share; the build then removes `build\` and `dist\Grammar Sweeper\`, which are scratch. The installer is unsigned, so Windows SmartScreen may warn on first run; choose More info, then Run anyway.

The installer does not contain Qt, the toolkit that draws the window, or Pillow, which draws the logo. It needs an internet connection: during setup it
downloads Qt (the `PySide6_Essentials` and `shiboken6` packages) and `Pillow` from PyPI, checks each file against a pinned SHA-256
hash, and unpacks only the files the program uses into a `runtime` folder beside the program. The program adds that
folder to its import path at start. If the download fails, setup stops and installs nothing.

`installer/runtime.inc` pins the exact PyPI files. After changing the PySide6 or Pillow version, run
`python installer/pin_runtime.py` to repin them, then rebuild. `installer/runtime-files.txt` lists the Qt and Pillow files that are
kept; `installer/make_images.py` redraws the installer artwork from the app's own palette and logo.
