# Grammar Sweeper: source, command line and internals

This document is for people who run Grammar Sweeper from source or change its code. If you installed
`grammar-sweeper-setup.exe`, you do not need it; the [README](../README.md) and the [user manual](../MANUAL.md) cover the
installed program. Behaviour rules are in [spec.md](spec.md). Contribution rules are in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Contents

- [Why it has to work this way](#why-it-has-to-work-this-way)
- [How the panel is structured](#how-the-panel-is-structured)
- [Running from source](#running-from-source)
- [Command line](#command-line)
- [Which cards get accepted](#which-cards-get-accepted)
- [Covering the whole document](#covering-the-whole-document)
- [What the console shows](#what-the-console-shows)
- [Files it writes from source](#files-it-writes-from-source)
- [When the uia engine finds nothing](#when-the-uia-engine-finds-nothing)
- [Options](#options)
- [Known limits](#known-limits)

## Why it has to work this way

Grammarly publishes no API that applies suggestions. The Text Editor SDK that
once embedded their suggestion UI was switched off in January 2024, and the
current developer platform is enterprise REST: it scores writing, it does not
return applied rewrites. Inside the product there is no universal accept-all
either. Premium exposes a bulk-accept button above the suggestions feed once
there are at least three suggestions, and on a long document it applies a batch
and leaves hundreds behind.

So the only lever is the product's own interface. This tool drives it: find the
primary accept control on the card, invoke it, wait for the panel to render the
next card, repeat.

## How the panel is structured

Worth knowing, because none of it is documented and all of it shapes the tool:

- Grammarly's review panel is a **top-level window named `Grammarly`**, owned by
  `Grammarly.Desktop`. It is not a child of Word's window and does not appear in
  Word's accessibility tree. A separate always-collapsed widget window
  (`AutomationId=GrammarlyAssistantWindow`) also exists and is deliberately
  ignored.
- The panel renders its feed **only while Word is the foreground window**, and
  tears its contents down otherwise. A check made too soon after activating Word
  sees an empty tree and reads as closed.
- The tool cannot reliably open the panel from a script. Synthetic clicks on the
  control that opens it do not register. **You open the panel, the tool drives
  it.** While it cannot see the feed, it refuses to click anything.
- Open, the feed lists each suggestion as a row whose label leads with the type
  and ends with `open suggestion card`. The accept control **does not exist
  until a row is opened**, so the loop is two steps: open a row, accept the card.
- Card buttons vary: `accept and open next suggestion`, `use this version and
  open next suggestion`, `rewrite in active voice and open next suggestion`, and
  a bare `accept`. Matching therefore falls back to structure when the name list
  does not know a label.
- Grammarly proofreads around the **caret**, not the viewport. Scrolling alone
  leaves the panel reporting "No text available", so the sweep moves the caret to
  the start of each page.

Every search is rooted at the Grammarly window. That is the main safety
property: Word's Review ribbon contains `Accept` and `Accept and Move to Next`,
and an earlier version rooted at the Word window invoked one of those instead of
a suggestion card.

## Running from source

Use this instead of the installer if you want to run or change the code. It needs Windows, desktop Microsoft Word with
the Grammarly add-in, and Python 3.10 or later.

```
pip install -r requirements.txt
```

The command line needs only `uiautomation` and `pywin32`; the window needs `PySide6` too.
Install into the interpreter you run from. Packages present in one Python
installation are invisible to another, and the symptom is `Missing dependency`
at startup even though `pip list` looks right. Check with
`python -c "import sys; print(sys.executable)"` if in doubt.

**Run from a normal, non-elevated shell.** The Running Object Table and UI
Automation are both partitioned by integrity level, so an elevated process
cannot bind to a normal Word's document or drive its windows.

Window: `python -m sweeper` (or double-click `grammar_sweeper.pyw`). Pick the document and
a preset, press Start, and watch the small always-on-top HUD. Esc stops the run.

To build the executable yourself, see [CONTRIBUTING.md](../CONTRIBUTING.md) and the building section of the
[user manual](../MANUAL.md#building-the-program).

## Command line

1. Open the document in Word.
2. Open Grammarly's panel in Word so the suggestion list is visible, and leave
   that document focused.
3. Run a two-card test first, then check the result:

```
python bulk_accept.py --max-accepts 2
```

4. Run the sweep. This example works from page 5 in steps of 8 pages, with no
   time limit:

```
python bulk_accept.py --document "my report" --start-page 5 --page-step 8 --preset thorough
```

`--document` takes a fragment of the filename and picks which open document to
work on. Hold `ESC` at any point to stop the loop.

## Which cards get accepted

All of them, by default. The tool takes whatever the panel offers, so leaving
the feed unfiltered picks up correctness, clarity, engagement and delivery in
one run. The panel's tabs are the filter if you want less: click `Correctness`
and the loop only ever sees correctness cards.

Two strategies find the accept button:

1. **By name.** A list of known labels in `ACCEPT_NAMES`, most specific first,
   matched on word boundaries so that `accept` cannot match `acceptance`. `Dismiss`,
   `Ignore`, tab names and the rest sit on a blocked list that can never be
   clicked. Collapsed feed rows are excluded from accept matching.
2. **By structure.** Every card pairs its primary button with `Dismiss`. When no
   known label matches, the tool finds `Dismiss`, climbs to the card container,
   and takes the leftmost sibling button that is not blocked. The label it finds
   is written to `learned_names.json` so the cheap path catches it next time.

A control that is clicked repeatedly without changing the document is
blacklisted for the rest of that page, so one stuck button cannot hold the loop.

## Covering the whole document

The panel scopes its feed to the region on screen, which is what
`review suggestions pages 87-96` in its header means. A loop that only drains the
visible feed stops early with suggestions still live further down, so the tool
sweeps: it scrolls forward `--page-step` pages at a time through the document,
draining the feed at each stop, and repeats the pass because applying a
suggestion reflows the text and Grammarly then raises new ones in regions
already visited.

## What the console shows

One line per accepted card, with the document length before and after, and a
live status line rewritten in place beneath it:

```
est  34.7% | applied 33 | visible outstanding 62 | Clarity 11, Correctness 19, Delivery 3 | 214s
```

Progress is read from document length, because the revision count stays at zero
when Word does not record Grammarly's edits. A run of accepts that change
nothing is collapsed to one line and a count.

The percentage is an estimate and is labelled as one. Its denominator is the
larger of the first count the panel reported and everything seen since, because
the true total is not knowable in advance: the panel counts the visible region
only, and the count moves as edits reflow the document. `visible outstanding`
is a lower bound on what is left. When the badge cannot be read it says
`unknown` and the percentage shows `--%` rather than inventing a figure.

The run ends with a totals line, the breakdown by card type, the breakdown by
invoke method, and the last outstanding reading.

## Files it writes from source

The window writes `audit.log` beside the run log (in `%APPDATA%\Grammar Sweeper\logs`): one line for every change of the front window, with the program that owns it, and one for every focus decision. Read it to find out what took the focus.

| File | Where | Purpose |
|---|---|---|
| Backup | beside the document | Timestamped copy taken before the first click. The undo. |
| `logs/grammar-sweeper.log` | beside the script | Full run history, every status line. |
| `logs/grammar-sweeper-unclassified.log` | beside the script | Labels of cards the tool could not categorise. Useful for extending `CATEGORY_HINTS`. |
| `checkpoint.json` | beside the script | Running totals, rewritten periodically. |
| `learned_names.json` | beside the script | Accept labels discovered by the structural strategy. |

`--log` moves the run log. All four local files are git-ignored. The installed program keeps its files under
`%APPDATA%\Grammar Sweeper`; see [Where files go](../MANUAL.md#where-files-go).

## When the uia engine finds nothing

The panel is a WebView2. If it exposes no accessible tree, the name search finds
no button and the loop reports empty feeds. Dump what it can actually see:

```
python bulk_accept.py --probe
```

The dump lands in `logs/uia-tree.txt`. Search it for the accept
wording. If the string is there, add the name it reports to `ACCEPT_NAMES` in
`bulk_accept.py`. If nothing in the panel appears at all, fall back to the
taught-coordinate engine:

```
python bulk_accept.py --teach          # hover the accept button, wait for capture
python bulk_accept.py --engine click
```

The click engine replays one position relative to the Word window. It has no
document sweep and cannot read card types. It stops itself after `--idle-rounds`
clicks that produce no new revision, which guards against clicking into empty
space after the feed ends. Re-teach after moving or resizing the Word window.

## Options

| Flag | Default | Purpose |
|---|---|---|
| `--document` | none | Filename fragment picking which open document to work on. |
| `--preset` | standard | `quick` one pass, `standard` up to four, `thorough` until two clean passes. |
| `--max-accepts` | 0 | Hard ceiling on accepted cards. `0` means none. |
| `--time-limit` | 7200 | Running seconds before the loop stops (paused time excluded). `0` means no limit. |
| `--max-passes` | 0 | Overrides the preset's pass limit. `0` uses the preset. |
| `--start-page` / `--end-page` | 1 / end | Bound the sweep. |
| `--page-step` | 5 | Pages advanced per scroll stop. Lower it if cards are being missed. |
| `--scroll-settle` | 1.5 | Seconds for the panel to re-scope after each scroll. |
| `--settle` | 0.7 | Seconds allowed for the panel to render the next card. Raise it on a large document. |
| `--idle-rounds` | 3 | Empty or no-change rounds tolerated before moving on. |
| `--barren-limit` | 4 | Accepts that change nothing before blacklisting the control and re-searching. |
| `--max-idle-seconds` | 300 | Hard stop after this many running seconds without a real accept or a new page. `0` disables. |
| `--stall-seconds` | 120 | Running seconds without progress before re-acquiring the panel. Keep below `--max-idle-seconds`. |
| `--counter-every` | 5 | Read the panel counter, checkpoint and save every N accepts. |
| `--no-periodic-save` | off | Skip the periodic document save. |
| `--save-before-scroll` | off | Also save before every page scroll. Expensive on long documents. |
| `--no-wake-lock` | off | Allow the machine to sleep during the run. |
| `--no-sweep` | off | Drain only the visible region, do not scroll the document. |
| `--no-structural` | off | Disable `Dismiss`-sibling discovery of unknown buttons. |
| `--track-changes` | on | `on`, `off` or `leave`: set Track Changes before the first click. `--no-track-changes` is the same as `leave`. |
| `--force-focus` | off | Always take Word back to the front, even when you switch away on purpose. |
| `--empty-probe` | 1.5 | Seconds to look for cards on a page before calling it empty. |
| `--no-backup` | off | Skips the backup copy. Do not. |

## Known limits

- Card wording is matched by accessible name first. A Grammarly redesign breaks
  that coupling, and the structural strategy is the backstop; `--probe` is how
  you re-derive names when both miss.
- Many cards are reported as `Unclassified`, because the type hints in
  `CATEGORY_HINTS` do not cover every card heading. This affects only the
  tally. The accepts themselves still apply.
- `visible outstanding` is the panel's count for the region on screen, not the
  document. It is a lower bound, and the completion percentage inherits that.
- Whether Track Changes captures Grammarly's edits varies by document and has not
  been established in general. Treat the backup as the only undo.
- Each accept writes to the live document while Grammarly is also editing it.
  The automated tests cover the engine rules and the screens, not the clicking; that
  has been exercised by hand against real documents only.
- A change is detected by document length. An accept that swaps text for text of
  the same length reads as "changed nothing". The blacklist for repeated
  no-change clicks is the backstop, so a same-length edit can be miscounted as
  barren but cannot loop forever.
- `--max-idle-seconds` also counts time spent waiting for a closed panel to be
  reopened. Leave the panel closed for that long and the run stops itself.
- Windows only. The tool depends on UI Automation, COM, and the Win32 API.
