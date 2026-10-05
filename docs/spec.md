# Grammar Sweeper: functional spec

Scope: what the engine does, when it stops, and what it tells the user. Appearance is in
[ui-walkthrough.md](ui-walkthrough.md) and the mockup. Terms in **bold** are defined in
[CONTEXT.md](../CONTEXT.md). The engine and the Python interface implement this document; the C# and C++
builds are deferred and will implement the same rules.

Status: all rules settled by Patrick on 2026-10-05 except where marked *to confirm*.

## 1. Passes and stopping

**Definitions**

- **Pass** (also called a review): one complete **Sweep** from the first page to the last page of the
  chosen range. With Pages set to "Whole document" it is end to end. With a narrower range, a clean pass
  only covers that range and the result screen says so.
- **Clean pass**: a pass that applied no suggestions and could see Grammarly throughout, meaning the
  **Panel** was present and its **Feed** readable at every page stop, with no blocked or no-change
  accepts. A pass that applied nothing because the Panel was missing, the run was paused, or accepts did
  not take effect is **inconclusive**, not clean, and does not count. An inconclusive pass resets the
  consecutive count.

**Stop rule, all presets.** The run stops after two consecutive clean passes, even if the preset has
passes left.

| Preset | Pass limit | Ends when |
|---|---|---|
| Quick | 1 | The single pass finishes. It cannot reach two clean passes, so it never claims the document is clear |
| Standard | 4 | Two consecutive clean passes, or the fourth pass finishes |
| Thorough | none | Two consecutive clean passes. It keeps iterating until then |

Every preset also ends on Stop or ESC, the 2 hour time limit, the 5 minute idle limit, the repetition
guard below, or a fatal error. Thorough has no pass limit, so these are its only other brakes.

This replaces three earlier behaviours: Thorough meaning "eight passes", the engine stopping after one
pass that accepts nothing, and the diminishing-returns early exit (removed for every preset, because it
could end a run while Grammarly was still finding suggestions).

**No accepts ceiling.** Decided 2026-10-05. The interface imposes none; the time limit and the idle limit
bound the run. The engine flag `--max-accepts` stays for command-line use, and a value of 0 or less means
no ceiling.

**Time limit.** 2 hours of running time for every preset. Time paused for the user does not count,
matching the idle limit. A run that reaches it ends as "Stopped early" and says so. *To confirm:* Patrick
answered this about Thorough; applying it to Quick and Standard too is a reading, not a statement.

**Repetition guard.** Grammarly can offer two rewrites that undo each other, so a pass is never clean.
At the end of every pass the app takes a fingerprint (a hash) of the document's full text and compares it
with the fingerprints from earlier passes. If a pass that applied suggestions ends with a fingerprint
already seen at the end of an earlier pass, the document has gone back to a previous state, and more
passes would only repeat it. The run stops with the result "Stopped: the changes started repeating" and
names which passes matched.

- It catches exact repeats only. A document that cycles through different paragraphs without ever
  returning to an identical whole is not caught, and falls back to the 2 hour limit.
- The cost of reading the whole text once per pass is unmeasured.
- Nothing is undone automatically. The run stops, and the user reviews the sections that keep changing.

## 2. Telling the user what is left

The finished screen always states one result. It never says "nothing left" except after two consecutive
clean passes.

| Result | When | What the screen says |
|---|---|---|
| Clear | Two consecutive clean passes | "Nothing left. Two full passes in a row found no suggestions." |
| Pass limit reached | Quick or Standard finished its last pass, and that pass still applied suggestions | "Suggestions may remain." Names the preset, the pass count, and how many the last pass applied, and offers to run Thorough |
| Stopped early | Stop, ESC, the 2 hour limit, the idle limit or a fatal error before the rule was met | "Suggestions remain." Names why it stopped, and what Grammarly was last showing |
| Stopped: repeating | The repetition guard tripped | "Suggestions remain." Says the changes started repeating, that more passes will not help, and points the user to the document |

Quick that finishes a pass applying nothing says "One pass found nothing. Run Standard to confirm."

The count Grammarly shows covers only the region in view, so any number quoted from it is labelled a
minimum, and when it could not be read the screen says "unknown" and states no figure.

## 3. Interruptions

The engine classifies every disturbance into a tier and acts on it. Never a raw traceback on screen.

| Situation | Tier | Engine action |
|---|---|---|
| Pop-up or notification takes focus briefly | Recoverable | Bring Word back, continue |
| User deliberately switches to another app | Needs the user | Pause. Resume when Word is in front. Do not take the window back while the person is working |
| Different Word document in front | Needs the user | Pause before the next click, name the other document, resume when the target returns |
| Grammarly panel closed | Needs the user | Pause, re-check with growing gaps, resume by itself |
| Grammarly restarts or reloads | Recoverable | Re-find the panel, continue |
| Target document closed | Needs the user | Pause. Name the backup, because Don't Save loses edits since the last periodic save |
| Word closed | Fatal | Safe stop with summary and backup path |
| Word dialog blocking | Needs the user | Pause, retry, resume when Word answers |
| No real progress for 5 minutes of running time | Fatal | Safe stop, summary, diagnostics |
| Screen locked or computer asleep | Needs the user | Sleep is blocked while running; a lock cannot be, so pause and resume after unlock |

**Idle limit.** 5 minutes of running time without real progress. Paused time does not count. Reaching a
new page counts as progress, because the last sweeps over a mostly clean document accept nothing for
minutes by design. The panel re-acquire limit (`stall_seconds`) must be shorter than the idle limit, so
the re-acquire fires first.

**Wrong-document check.** Before every Accept, confirm the document in front is the target, by Word's
active document through COM and by the foreground window title. On a mismatch, pause without clicking.
Any accepts made between a switch and its detection are listed on the finished screen. Unverified: what
Word reports mid-switch has not been tested.

## 4. Progress and time estimate

**Progress is words, not pages.** The ring shows the share of the current pass's words already reviewed,
using Word's own word count (words before the page now being read, over the words the pass covers). If the
counts cannot be read, it falls back to page position. It covers one pass only, because how many passes
follow cannot be known in advance.

**ETA.** Derived from the same word share and the pace so far in this pass. It is withheld until 5% of
the pass is done and 20 seconds of data exist, and until then the HUD says it is working it out. It is
shown as "About N left in this pass".

**Pass label.** Counts from 1 and states the preset's limit: Quick "Pass 1 of 1", Standard "Pass N of up to
4", Thorough "Pass N" with no limit. A run stopped during its first pass reports pass 1, never 0.

**What counts as applied.** Only a click that changes the document. After every click the text around
the card is compared with what it was before, and the document length is compared too. A click that
changes neither is a no-effect click: it is shown as its own note, never added to the applied count, and
never recorded as a change. The tiles then add up to the applied count, and the applied count matches the
change records.

**Page shown.** The HUD shows the page Word's insertion point is on, which is what Word's status bar
shows. The ring measures the page stop the engine is working through, so the two can differ.

**Whole-run estimate.** The HUD shows the rest of this pass, and a floor for the whole run: this pass's
remainder plus the passes the stop rule still needs (two clean passes in a row, capped by the preset's
limit). A clean pass is costed from the stops that have applied nothing so far, 8 seconds a stop until
some are measured. It says "at least", because passes that apply things run longer. Applied counts are
kept for every pass and shown per pass; the chart and tiles accumulate across passes.

## 5. Pages with no text, and cards with no accept

- Only an explicit "No text available" notice from the panel lets a page be skipped, and only after two
  probes a second apart, one re-select, and one click into the page. A page with no cards and no notice is
  not trusted as empty: it gets the full search.
- Many such pages make the pass inconclusive (more than 2, or more than a tenth of the stops).
- Cards that open but never show an accept button end the page after about nine opens. The page is logged,
  photographed, and the pass is marked inconclusive.

- **Positive clean signal.** Grammarly states "No unresolved suggestions for pages 19-28" when it has
  cleared a range. That message lets a stop be skipped, but only when its page range includes the stop,
  because the panel can still be showing the previous stop's message.
- **Retry and reopen.** A click that fails on a stale element is retried once after a fresh search. A
  control that applies nothing several times has its card reopened once before it is given up on, and a
  pass is marked inconclusive only when that fails and the control is blacklisted. One no-effect click
  does not spoil a pass.

## 6. Layout, focus and the Word view

- **Layout.** The app is locked to the left 32% of the work area (never under 580 pixels), and Word fills
  the rest, on the right. While a run is on, the app window is hidden and the toaster sits directly above
  Grammarly's panel on the right, at the panel's own width and left edge, at the top of the work area. The panel is
  moved down and shortened to make the room, and the toaster cannot be dragged. If the panel is not
  showing, the toaster waits at the top right. The layout is held for as long as the app runs, checked twice a second, including during a run:
  Word is restored if maximised or minimised, moved back if dragged, and the app likewise. Placement
  targets the visible frame, not the window rectangle, so Word's invisible resize border leaves no gap
  or overlap, and a placement counts only once the frame is read back in place. If the first call does not
  move the window, a second Windows call is tried. If Word is not open with the document, Word is started
  with it once, on load or on Start; closing Word later does not start it again. Every failure reaches the
  audit log (`GUI_PANE`, `GUI_PANE_ERROR`) with the measured frame, and the window shows a line saying
  Word would not move.- **Focus.** Word is `WINWORD.EXE`. Grammarly's panel belongs to `Superhuman.WebUI.exe`, and
  `Grammarly.Desktop.exe` is also exempt, as are this program's windows. The option to always return to
  Word takes it back after any switch.
- **Start gate.** Start brings Word forward, then waits up to twenty seconds for Grammarly's assistant to
  be open and showing its feed. If it is not, the run does not start and the window says so. The panel
  exists only while Word is in front, so the start page does not claim it is missing.
- **Following the panel.** Grammarly reviews ten pages around the caret, and re-scopes only after a real
  click, taking from one to eight seconds. Each stop clicks into the page (the first ordinary paragraph on
  screen, else the page top) and waits until the panel's own "pages A to B" text holds the stop, instead
  of a fixed delay. One further click is made at 60% of the wait, not earlier, because an earlier click
  restarts Grammarly's delay. A stop that never follows is retried once at the end of the pass, and if
  still stale it is logged (`SCOPE_STALE`) and the pass is inconclusive, never read as clean. The page
  step is eight, which overlaps the ten-page scope by two. The late re-click is followed by a key nudge
  (Right then Left, sent only while Word is in front). A stop still stale after the wait gets one panel
  restart: Grammarly's assistant hotkey, Ctrl+Shift+Alt+G, toggles, so a showing panel is closed and
  reopened, then the page is clicked, nudged and waited on again (`PANEL_RESET`). The document is also cut
  into sections of 40 pages, Grammarly's own advice for long documents being about fifty, and the panel
  is restarted at each section boundary.
- **Rephrase and tone.** Rewrite cards (for example "Rewrite in active voice") offer Rephrase as their
  one button, and it is accepted like any other accept, last in rank after the plainer wordings. Tone
  cards ("Want to sound friendlier?") are never accepted: they are not opened, and if one is open its
  button is not clicked (`TONE_SKIPPED` in the audit log). The test is on the card's heading only, so a
  document that says "user-friendly" is not skipped. Tone cards left alone stay in Grammarly's list, so
  a pass that still shows them is not read as clean by that alone.
- **Short documents.** Grammarly shows no page range for a document of ten pages or fewer. Its scope is
  then the whole document and the engine does not wait for a range.
- **No text available.** When Grammarly's panel says it has no text to read at a stop, the engine does not
  skip the page at once. "No text available" most often means the Word document is not the focused
  window, so the first step is to put the document back in front and click into its text. The audit log
  records what was in front when it happened (`NO_TEXT_SEEN`). It then tries a click in a different
  paragraph (twice), a key nudge, and a panel restart, looking at the panel after each (`NO_TEXT_RECOVERED` names the rung that worked). If all
  fail the page is skipped as unread, with where the caret was written to the audit log
  (`NO_TEXT_FAILED`: inside a table, outside the main text, on an empty paragraph, or Word unreadable
  because a dialog may be open). Three stops in a row hold the run: the toaster says "Grammarly says it has
  no text to read. Click into the body text in Word and close any dialog or banner.", the clock stops, and
  the run carries on by itself when Grammarly can read text again, or after five minutes.
- **Documents stored online.** A document opened from SharePoint or OneDrive has a web address, so no backup
  copy can be made from it and Word may block saving it ("Upload blocked"). The start page says so.
- **Counter check.** The applied counter is checked independently. The document's text is read before and
  after every stop, and the paragraphs that differ are counted. More paragraphs changed than the counter
  says were applied is written to the audit log (`STOP_DELTA`, with both figures and `behind`), noted in
  the log, and shown on the toaster as "Word changed in N places; the counter is M behind". Two accepts in
  one paragraph count once in the check, so it can only under-state the gap, never invent one. The HUD shows the page Word is on, read after
  the move, and the pages Grammarly is on.
- **Version stamp.** The window title reads the version from `VERSION`, the git commit (`-dirty` when work
  is uncommitted) and the build time, for example "Grammar Sweeper 0.3.0 (534d8eb-dirty), built ...". The
  audit log's first line of each run carries the same stamp. `python build.py` is the one way to build
  the exe: it stamps, builds into `dist\`, and removes the stamp file. A source run reads the same fields
  from `VERSION` and git.
- **Look.** One font family throughout (Segoe UI). Headings and field names are bold, and the text under
  them is regular weight. Yellow appears only on the coffee button: warnings are violet and notices an
  indigo tint. Button text is small. Scroll bars are thin rounded handles with no arrow buttons, and the
  page range is typed into plain boxes with no spin arrows.
- **Setup page tabs.** The setup page has three tabs: Setup (document, how thorough, pages, options),
  Recent runs (the last twenty), and Advanced. Each recent run is two lines: the document as a link to the
  file (or its SharePoint address) with Backup (the backup folder) and Report as links at the right, then
  the date, the number applied, the time saved and a sparkline of changes per page across the document
  (folded into at most forty buckets). A link shows only while its file exists. Runs made before the path,
  backup and sparkline were recorded show without them. Start, and the Grammarly status above it, show on
  the Setup tab only. The Setup tab shows the page count of the chosen document under the picker. The page title carries the logo to the right of its name, and no version. The tagline reads "Accept Grammarly suggestions hands free." How thorough shows each
  mode as a bold name with its description on the same line, two points smaller than the body text.
- **Advanced tab.** Holds what used to sit on the summary: Open logs folder, Open audit log, Open
  screenshots and Copy diagnostics. It also has Delete old files: tick screenshots, the audit log, run logs,
  reports or diagnostic bundles, each shown with its item count and size (an emptied log shows Empty),
  choose All time or older than 7, 30 or 90 days, and press Delete selected. Each name has an Open link to its file or folder. Change records and rule
  files are not in that list: they are what the rules are built from, so they have their own card with
  their own age choice, their own Open link and their own button (Delete change records and rule files), and the confirmation says what they hold. A dry run first counts
  what would go, and a confirmation names the number and size before anything is removed. Logs are emptied
  and the rest deleted; a log written to recently counts as new, so an age never empties a log in use.
  Backups of documents, settings and the run history are never removed. Each clean is written to the
  audit log (`CLEANUP`).
- **Footer and logo.** The setup page, the summary page and the report each carry a footer: the company
  (Preceperi Limited), the version (`v0.3.0`, from `VERSION`), a GitHub link and a link to The Apertura
  on Substack. The summary and the report also have the Buy me a coffee button in the footer. The summary
  and report carry the logo at the top. The window title shows no version; the full build (commit and
  build time) is on the Advanced tab and in the audit log. Addresses are set in one place,
  `sweeper/settings.py`. The GitHub link goes to the profile page until a repository exists.
- **No seconds.** Durations on the summary, in the copied summary and in Recent runs are to the nearest
  minute ("under 1 min", "5 min", "1 h 05 min"). The report's run start and its change times show hours
  and minutes. The toaster, which counts live, still shows seconds.
- **Logo.** The icon is shown on a rounded tile with a fine light edge and a soft shadow, drawn at twice the size and shrunk so it stays sharp on a high-density screen (`sweeper/brand.py`). It is 60 pixels on the setup page, 44 on the summary beside the name, and 60 in the report. The icon file is never altered.
- **Status and texture.** The setup status is a bold coloured badge: green Ready, violet Ready with notes
  (an unsaved or read-only document, an online document, a layout problem), red Not ready (no document
  open, or running as administrator), with the detail in regular text below it. The window and dialogs
  have a very light fine texture, paper grain with a faint dot grid, generated once from the page colour
  and repeated without a seam; the report carries the same tile. Cards sit flat on top of it.
- **Help.** A round ? button at the top right of the setup page and of the summary page opens a short help
  dialog for that page: the setup options and what the engine will and will never accept, and how to read
  the summary, including why a Standard run shows three passes.
- **Page strip.** "Where it changed" is one block per page, coloured by the commonest kind of change on
  that page (the four type colours), grey where nothing changed, outlined where Grammarly could not read
  the page. Hovering a block shows a short summary: the page, the number of changes and their mix, and up
  to three of them as "'teh' to 'the'", "added 'x'" or "removed 'x'". The data is the change record the
  run already keeps, so a page's change is on the page Word reported for it.
- **Passes.** A pass that applies changes is where the work happened; a pass that finds nothing is a check.
  The Passes row says "Changes made in 1 pass: pass 1 (5)" then "2 further passes checked and found
  nothing". A run fixed in one pass and checked twice therefore reads as one pass of changes.
- **Copy summary.** A button on the summary copies it as plain text: the result and its type mix, time,
  passes, backup, changes by page, and any pages Grammarly could not read. The button reads "Copied" for
  two seconds.
- **Summary page.** It fits the window width and never scrolls sideways. The document name and its
  location are links that open the file or folder, including a document stored online. The Passes row
  lists what each pass did ("Pass 1 applied 5", "Pass 2 found nothing") and why the run stopped. A pass is
  one walk through the whole document, and Standard walks it again until two in a row find nothing, so
  a document that needed one pass of work shows three. The Mode row names the preset and its limit.
- **Start page.** Only the recent runs list scrolls. The finished summary omits Word revisions and clicks
  with no effect.
- **Resume.** Resuming from a pause forces Word back to the front and into its area, discards the cached
  panel, and searches for it afresh. The audit log records the time from resume to the first accept.
- **Markup.** Word's markup view is set to none for the run, because tracked changes on screen confuse
  Grammarly, and restored afterwards. Only the view changes; the Track Changes setting is separate.
- **Track Changes** is switched on, off or left alone before starting, per the user's choice.
- **Awake.** Sleep and display-off are blocked during a run and restored after it.
- **Before starting.** The ready screen warns about unsaved changes, a read-only document, or a document
  over 300 pages. A warning does not block Start.

- **Taking the foreground.** `SetForegroundWindow` is refused from a background process, and so is
  the library's `SetActive`. Seen live: four take-backs did nothing while Grammarly's panel held the
  front. Taking the foreground shares input state with the thread that owns it, allows the call, raises
  the window through the topmost list, and checks that it worked. It is used on Start, on Resume and for
  every take-back. Until 2026-10-05 the interface's own Resume used a weaker call that did not do this,
  so Word stayed behind; the interface now uses the same forced method (`winfocus.force_foreground`),
  tries again after half a second, and a test checks the interface calls it. When the engine itself
  holds the run ("Return to Word to continue"), the HUD button reads Resume and a click forces Word
  forward; before, it read Pause and the first click only toggled a pause the engine was ignoring. Every
  interface attempt writes `GUI_FRONT` to the audit log with the program that ended up in front.

### Error handling

Errors that are caught on purpose are never silent. The first of each kind is written to the audit log in
full; every kind is counted, and the totals are written when the run ends and shown in the run log.
Current kinds: invoke pattern, legacy accessible, stale element on click, stale element on search, retry
search, heading path. Click failures are retried once (section 5). Nothing is retried without a new
search first.

## 7. Suggestion types

Four, exactly as Grammarly names them, in its own colours: Correctness (red), Clarity (blue), Engagement
(green) and Delivery (purple). They appear as tiles on the HUD and the finished screen with a strip in
each colour, in the log, and in the change records. A card whose type cannot be read is Unclassified:
a fifth tile with a grey strip, counted separately and never folded into another type. The type is read
from the card's header, the part before its 'learn more' link, never from the document sentence that
follows it.

## 8. Records

All written under `%APPDATA%\Grammar Sweeper\logs` unless stated.

| Record | Content |
|---|---|
| `audit.log` | Every focus change and decision, with the owning program, seconds since input, and who made the input; resume timing |
| `shots\` | Whole-screen picture on a focus problem, an unconfirmed empty page, a no-text page, or a missing accept button. The date and time are burned into the picture and the file name. At most one per reason every 20 seconds, 200 kept |
| `changes-<time>.jsonl` | One record per accepted suggestion: time, page, page stop, type, button label, the card's wording, the original text, the revised text, and up to 100 characters of context either side, cut to whole words |
| `report-<time>.html` | One file: filter by type, original beside revised, a bar per page showing where suggestions landed, the candidate rules, and a short note on how to read them. Changes are highlighted, never struck out. Light, in the same style as the summary page. The run's start is shown as a date and time ("5 October 2026, 17:27:17"), the two candidate rule tables share one set of column widths so they line up, and a Buy me a coffee button sits at the top right |
| `grammar-sweeper.log` | One JSON object per line (`t`, `level`, `msg`), so it can be queried. The live status line goes to the console only, not the file |
| `history.json` (one level up) | The last 50 runs, each with the document's path; the Recent runs tab lists the last 20 with links to the file and report |
| Diagnostics | A button copies the logs, settings, the newest screenshots and the report into one folder |

**Change record (`changes-<time>.jsonl`).** One object per applied suggestion. Fields: run id; hash of
the document at the start; draft number from the document property `GS_Draft` when a generator set it,
otherwise empty; time; page, page stop and heading path (outermost first); type; Grammarly's rule name;
kind of edit (insert, delete, replace, case, punctuation), judged on whole words; class (mechanical or
stylistic); original and revised text; up to 100 characters of context either side; the whole sentence before
and after; words removed and added; flags; the card's wording; and a text anchor (first eight words of the
sentence, plus a short hash), because page numbers drift as edits reflow the document.

**Whole words only.** Context never starts or ends in the middle of a word. If the 100 character cut falls
inside a word, that word is dropped, and when in doubt the context is made shorter. An edit that cuts
through a word ("ve" to "s" inside "have" to "has") is widened to the whole word, so the original and
revised text are always whole words.

**Flags.** An edit is flagged for human review when it touches a number, a negation, a capitalised name,
or an all-capitals defined term, because any of those can change what a sentence claims.

**Mechanical and stylistic.** Correctness fixes and punctuation or case edits are mechanical: they need no
judgement and belong in deterministic post-processing. Everything else is stylistic: a choice, so it
belongs in prompt guidance and few-shot examples.

**Rule mining.** Records are grouped by type, rule and the normalised edit (words removed to words added).
Each group has its count, up to three examples, and a drafted instruction
("Write 'use', not 'utilise'"). The instruction is a draft for a person to edit, not a decision. Phrases
removed more than once are listed separately.

**Exports.** Beside the report: `rules-<time>.json` (every group), `postprocess-<time>.json` (mechanical
groups), and `fewshot-<time>.jsonl` (stylistic examples, one before-and-after pair per line).

**Provenance.** The sweeper cannot know which model or skill wrote a section, because Word keeps no such
record. It never guesses: no inference from style, wording or timing. A field with no recorded source is
written as "unknown". It can read what the generator left behind. Only the draft number is read today, from the
document property `GS_Draft`. Reading the model and skill needs the generator to write them into the
document (custom properties, or tagged content controls per section) or into a manifest file beside it.
Not built.

**Why two captures.** The per-accept record carries the type, page and card wording, which a comparison
cannot recover, and is what makes the examples useful for training. The check that catches anything the
per-accept records missed is the counter check, which reads the document text before and after every page
stop. The report no longer carries a start against end paragraph comparison. The per-accept record finds its
change by comparing the document text before and after the click, so it does not depend on the card
exposing before and after text. The time this adds is measured and written to the run log.

When a run ends the report opens (a setting), and Word is scrolled to the first page that changed.
A stopped run offers to resume from the page where it stopped.

## 9. Engine status against this spec

Written 2026-10-05 after the Python build began. "Built" means coded and unit tested against fakes;
nothing here has been run against live Word and Grammarly in this session.

| Rule | Status |
|---|---|
| Clean and inconclusive passes, two consecutive | Built, `sweeper/rules.py` |
| Presets, Thorough unlimited | Built |
| Repetition guard by whole text hash | Built; text read cost unmeasured |
| 2 hour limit, 5 minute idle limit, paused time excluded | Built in the policy; wired to the engine clock |
| Diminishing-returns exit removed | Built |
| Result states | Built |
| Interruption tiers, pause and resume | Policy built; live detection of focus, panel and document is partly new work |
| Wrong-document pre-click check | Built behind a hook; live behaviour unverified |
| Word-based progress, ETA, pass label | Built; unit tested; per-page word count cost unmeasured |
| No-text rule, unconfirmed empty pages, stuck cards | Built; the click into a page is untested live |
| Layout, forced return on resume, markup hidden | Built; untested against live Word |
| Four types with colours | Built |
| Change records, report, history, diagnostics, resume from page | Built; unit tested without Word; not run live |
| Screenshots and audit log | Built; screenshots tested on the desktop, not inside a run |
| Applied counts only confirmed changes; no-effect clicks shown apart | Built; unit tested; the surrounding-text comparison is untested live |
| Foreground taken with shared input state | Built; no-op case tested; the take-back against Grammarly's panel is untested live |
| Clean-page signal, whole-run estimate, applied per pass | Built; unit tested |
| Retry on stale element, card reopen, swallowed-error counts, JSON log | Built; unit tested; live behaviour unverified |
| Fifth tile for Unclassified, grey | Built |
| Record fields, flags, mechanical and stylistic split, rule mining, exports, 100 character context | Built; unit tested without Word; heading path and draft property untested live |
| Model and skill provenance | Not built; needs the generator to write it (section 8) |

## 10. Risks

- **Thorough may not finish.** A partial cycle that never repeats the whole document is not caught, and
  the 2 hour limit is the backstop.
- **The 2 hour limit can cut off a legitimate Thorough run.** The run then reports "Suggestions remain"
  and is not a failure.
- **The rule costs one extra pass.** Confirming "nothing left" always takes two full passes after the
  last accept.
- **A clean result is only as good as the panel reading.** If the Panel reports nothing because it is
  scoped to the wrong region, a pass can look clean while suggestions remain.
- **Not verified live.** The Grammarly interface changes without notice; the fake-tree tests prove the
  rules, not the product.

## 11. Decisions

Settled by Patrick on 2026-10-05:

1. Repetition guard added.
2. Time limit is 2 hours.
3. No accepts ceiling.
4. Idle limit is 5 minutes.
5. Two consecutive clean passes end every preset; Thorough has no pass limit.

Recorded as a reading, *to confirm*: the 2 hour limit covers Quick and Standard; the diminishing-returns
exit is removed (recommended, and the build proceeded on it).

Settled by Patrick later on 2026-10-05:

6. Progress is measured in words reviewed in the pass, with an ETA.
7. Word is forced back to the front on resume, and the markup view is hidden for the run.
8. The four types are Grammarly's own, in its colours.
9. Capture both the per-accept change and the final comparison.
10. Added: resume from the stopped page, run history, an HTML report with type filters, per-page heat bars,
    auto-open of the report and first changed page, pre-start warnings, layout per monitor setup, and a
    diagnostics bundle.
11. Changes 2 and 3 of the log review are built: retry once on a stale element, reopen a card before
    giving up on it, a pass inconclusive only on repeated no-effect clicks, a JSON log, and counted errors.
12. Unclassified is a fifth tile, grey. Context is 100 characters. The report gains rule mining, the
    mechanical and stylistic split, review flags, repeat offenders, few-shot export and text anchors.
    Not taken up: per-draft rates, prompt attribution, and keep or reject marks.
13. This spec is updated in the same change as the behaviour it describes.
