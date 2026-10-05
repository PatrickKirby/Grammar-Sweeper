# Grammar Sweeper: look and feel walkthrough

The product is shown to users as **Grammar Sweeper** (title bars, installer, headings). The repository
and folder keep the slug `grammar-sweeper`.

Status: approved on six open points (section 7). Next step is a static HTML mockup, then the shared Spec.
Terms in **bold** are defined in [CONTEXT.md](../CONTEXT.md).

Everything marked *proposal* is a design choice for Patrick to accept or change. No value here has been
rendered or contrast-tested yet.

## 1. The product in one paragraph

A small Windows app that a non-technical Word user installs once and runs in three clicks: pick the
document, press Start, walk away. It looks like a first-party Windows 11 tool, with one action per
screen and nothing the user has to decode. Because the engine must never steal focus from Word, the app
spends most of its life as a small floating **HUD**, not a window. The look must therefore be judged at
two sizes: the full window (setup, results) and the HUD (the running state). (Q1, Q2, Q4)

## 2. Design language

| Element | Choice | Source |
|---|---|---|
| Theme | Follows the Windows light or dark setting live; no in-app toggle on the main screen | Q2 |
| Accent | Indigo, used for the primary button, the progress ring and focus rings (*proposal:* `#4F46E5` light, `#8B93FF` dark) | Q2, icon |
| Warning | Amber for amber preflight rows and the recoverable error state (*proposal:* `#D97706`) | Q2 |
| Dark theme | Neutral Windows 11 greys, not purple-tinted: backdrop `#26272D`, cards `#303139`, text `#F4F5F9`. Status colours are lifted for dark and their tick marks use near-black ink for contrast. Replaces the first dark palette, which was rejected | Patrick, 2026-10-05 |
| Success | Green for passed checks and finished runs (*proposal:* `#16A34A`) | *proposal* |
| Danger | Red for blocked checks and fatal errors (*proposal:* `#DC2626`) | *proposal* |
| Surfaces | Rounded cards on a soft backdrop. Backdrop is Mica where Windows provides it, a flat tinted colour otherwise. Cards sit one step lighter than the backdrop in both themes | Q2, Q18 |
| Corners | Cards 8 px, buttons and inputs 4 px (*proposal*, check against Fluent 2 tokens) | *proposal* |
| Type | Segoe UI Variable where present, Segoe UI otherwise. One page title, one body size, one caption size. No bold paragraphs | Q17 research |
| Icons | Fluent UI System Icons only (MIT), one weight, outline style, so glyphs match | Q17 research |
| Window chrome | Standard Windows title bar, with the Mica backdrop extending under it. No custom frameless window | Q18 |
| Motion | Short fades and the ring sweep only. Respect the Windows "reduce animations" setting where practical | Q20 (best effort) |
| Density | Generous. One primary action per screen. One card of "advanced" content visible at a time | Q1, Q8 |

Rule that settles disputes: **if a control is not needed by a first-time user in the next ten seconds,
it goes behind Advanced or Diagnostics.** (Q1, Q8)

The Mica fallback matters. If transparency is off, Battery Saver is on, or the hardware is low-end,
Windows will not draw Mica, so every screen below must look finished on a flat colour. Mica is polish,
nothing depends on it. (Q18)

## 3. Screen map

```
Installer -> First launch: Consent -> Main window (Preflight + Ready) -> Start
   -> Looking for the Panel -> HUD (running)
        |-> HUD amber        (recoverable error, continues by itself)
        |-> HUD paused       (needs the user, resumes by itself)
        |-> Fatal error      (safe stop, summary, Copy diagnostics)
   -> Finished
Relaunch after a crash: Recovery banner on the Main window
Anytime: Tray icon, Toast, Settings, Advanced, Diagnostics
```

## 4. Screens

### 4.1 Installer (Inno Setup, per user)  (Q19)

Conventional Windows setup wizard, branded with the icon and the indigo accent on the header strip.
Pages: Welcome, Install location (default under the user's local app folder, so no administrator
rights), Optional "desktop shortcut" checkbox, Install progress, Finish with "Launch Grammar Sweeper".

- Per-user install, so the tool is never launched elevated by accident. An elevated process cannot see a
  normal Word's documents or drive its windows.
- Includes an uninstaller entry in Apps and Features.
- Unsigned, so the first launch may show a SmartScreen warning. The Finish page links a short "If
  Windows warns you" note. Signing is deferred. (Q19)

### 4.2 First launch: Consent screen  (Q5, Q9)

Shown once, on first launch only, as a centred card over the main window area.

```
+--------------------------------------------------+
|  [icon]  Before you start                        |
|                                                  |
|  Grammar Sweeper accepts Grammarly's suggestions |
|  for you, without showing each one first.        |
|                                                  |
|  *  Some suggestions rewrite sentences. Review   |
|     the document afterwards.                     |
|  *  Word's Track Changes may not record these    |
|     edits. The backup is your only undo.         |
|  *  A backup is saved before the first change:   |
|     C:\Users\...\Documents\...   [Open folder]   |
|                                                  |
|  [ ] I understand                                |
|  [ ] Don't show this again                       |
|                                                  |
|              [ Continue ]  (disabled until the   |
|                             first box is ticked) |
+--------------------------------------------------+
```

- "I understand" gates Continue. "Don't show this again" is independent and optional.
- After this, the main window keeps a one-line reminder: "Edits are applied without review. Backup is
  your undo." with a link to the full text. (Q5)
- "Don't show again" suppresses only this full screen. It comes back when the backup is turned off, when
  Track Changes is forced off, or when the major version changes. Settings has a switch "Show safety
  notice again". (Q9)

### 4.3 Main window: Preflight and Ready  (Q6, Q8, Q10)

The home screen. One card for the document, one for the checks, one for the three basic settings, and
one primary button.

```
+--------------------------------------------------------------+
|  Grammar Sweeper                                  [Settings] |
|--------------------------------------------------------------|
|  Document                                                    |
|  [ Delivery Plan vB.docx                         v ]  (open  |
|    Word documents currently open, refreshed         in Word) |
|                                                              |
|  Checks                                                      |
|   [ok]  Word is running                                      |
|   [ok]  Document is open and saved                           |
|   [ok]  Not running as administrator                         |
|   [ok]  Backup folder is writable                            |
|   [..]  Grammarly panel: checked when you press Start        |
|                                                              |
|  Options                                                     |
|   Pages        [ whole document v ]                          |
|   Thoroughness ( ) Quick  (o) Standard  ( ) Thorough         |
|   [x] Keep this computer awake while it runs                 |
|   > Advanced                                                 |
|                                                              |
|  Edits are applied without review. Backup is your undo.      |
|                                                              |
|                                   [        Start        ]    |
+--------------------------------------------------------------+
```

Behaviour:

- **Document picker.** A dropdown of open Word documents, refreshed automatically, with the active one
  preselected. No file browser, because the tool needs a document that is already open. Empty state: a
  card reading "Open a document in Word to begin" with the document control disabled. (Q6)
- **Preflight rows** re-check on their own. States: green tick (pass), amber triangle (warns, allows
  Start), red cross (blocks Start). Every red row carries a one-line fix beside it, for example
  "Close this app and reopen it from the Start menu, not as administrator". (Q10)
- **The Panel row is never live.** The Panel only renders while Word is in front, and this window is in
  front during preflight, so the row reads "Checked when you press Start". (Q10)
- **Thoroughness** maps to engine settings, defined in [spec.md](spec.md). Quick is one pass, Standard
  is up to four passes, Thorough has no pass limit. All three stop early once two complete passes in a
  row find nothing. Patrick changed Thorough from "eight passes" to "until clear" on 2026-10-05, which
  supersedes the earlier approval in Q8. The raw numbers appear under Advanced. Hovering or focusing each
  option shows a plain-language description. (Q8)
- **No manual-time estimate on this screen.** An earlier draft showed "Grammarly shows 62 suggestions
  in view, about 8 min by hand" here. It was removed on Patrick's instruction: the Grammarly panel is
  not visible before Start, because it renders only while Word is in front, so there is no count to
  read. The by-hand comparison appears only on the finished screen, where the applied count is real.
  The 8 seconds is a fixed figure Patrick supplied, not a measurement, and sits in one constant.
- **Several documents open.** The dropdown lists every open document with its folder. The one in front
  in Word is preselected and tagged "Active in Word". A document with unsaved changes is tagged and
  should be saved first. A document in Protected View, or one that has never been saved, is greyed with
  the reason, because no backup can be made or no edit is possible. A banner warns that selecting a
  document is not enough: Word must keep it in front during the run. (Screen 4 in the mockup)
- **Start** is the only filled, accent-coloured button on screen. It is disabled while any row is red.
- During a run there is no full window (see 4.6), so the close button has nothing to kill.

### 4.4 Advanced panel  (Q8)

An expander below Options. Collapsed by default. Contains the raw engine settings for people who want
them, each with a one-line description and a reset link: start page, page step, maximum accepts, time
limit, maximum idle time, settle delay, save frequency, periodic save on or off, wake lock on or off.
A separate **Diagnostics** group holds the power tools: dump what the Panel exposes, teach a click
position, and open the log folder. These are the former `--probe` and `--teach` modes. (Q1, Q8)

### 4.5 Start: Looking for the Panel  (Q4, Q10)

Pressing Start does three things in order, shown as a short progress card:

1. Writes the backup (shows the file name when done).
2. Brings Word to the front.
3. Looks for the Grammarly **Panel** and its **Feed**.

If the Panel is found, the main window shrinks into the **HUD**. If not, a guidance card appears: "Open
Grammarly in Word so the suggestion list is visible, then press Try again." with a short annotated
picture of where the Grammarly button sits. The app cannot open the Panel itself, because synthetic
clicks on that control do not register, so the user does it. Try again re-runs steps 2 and 3 only.

### 4.6 The HUD: running  (Q4, Q7)

A small always-on-top window that never takes focus. A user sees this for hours, so the whole running
experience is judged on it.

```
+-------------------------------------+
|  ( ring )   Applied  1,284          |
|   about 62%  Page 37 of 109         |
|              Sweep 2                |
|   [ Pause ]  [ Stop ]  Esc = Stop   |
+-------------------------------------+
```

The figures in the picture are placeholders for layout only.

- **Non-activating.** Clicking its buttons must not pull focus from Word. The engine depends on this,
  because the Panel renders only while Word is foreground. (Q4)
- **Placement.** Approved: it starts at the top-left of the work area and the user can drag it
  anywhere, with the position remembered. In the recorded log the Panel sits on the right of the screen,
  and a fallback mouse click could land on the HUD if it covered it. The left start position keeps the
  HUD clear of the Panel in that layout. Because the HUD is freely movable, the engine must not assume
  where it is: if the HUD overlaps the Panel's window, the HUD shows a short "Move me, I am covering
  Grammarly" hint and the engine avoids mouse clicks in that overlap. The HUD floats above Word without
  taking focus.
- **The ring** shows an estimated percentage and says "about". The estimate is a lower bound, because the
  Panel counts only the visible region and the total moves as text reflows. When the count cannot be read
  the ring shows an indeterminate sweep and the label "working", never an invented figure. This follows
  the engine's existing honesty rule. (Q8, existing behaviour)
- **Applied count** is large and tabular so digits do not jitter. A secondary line shows the current page
  and the current **Sweep** number, and a third line shows the time running. The clock stops while
  the run is paused. Approved.
- **Pause** and **Stop** are on screen. ESC remains the emergency stop and is shown as the hint
  "Esc = Stop", because it is already proven. Pause keeps the **Run** and stops clicking; Stop ends it safely. (Q7)
- The HUD is a flat, high-contrast surface, not Mica, so it stays legible over any document.

### 4.7 HUD states: recoverable and needs-the-user  (Q11)

Same size and position, different colour and message. Never a raw traceback.

| Tier | Looks like | Behaviour |
|---|---|---|
| Recoverable (panel lost, focus stolen, stale element) | Amber ring, "Reconnecting to Grammarly" | Continues by itself, retries back off, returns to indigo when healthy |
| Needs the user (panel closed, Word closed, document gone) | Amber ring paused, one plain instruction, for example "Grammarly was closed. Open it in Word to continue." | The **Run** pauses, not aborts, and resumes by itself once the condition clears |

If a **Run** makes no real progress for the idle limit, it stops itself and moves to the fatal screen.

#### Interruptions: switching apps, closing Grammarly or Word

| Situation | Tier | What the user sees | What the app does |
|---|---|---|---|
| A pop-up or notification takes focus briefly | Recoverable | Nothing, or "Reconnecting" for a moment | Brings Word back to the front itself |
| User deliberately switches to another app | Needs the user | "You switched to another app. Return to Word to continue." | Pauses and resumes when Word is in front again. It does not take the window back while the person is working |
| User brings a different Word document to the front | Needs the user | "Word is showing Board Paper.docx. This run is for Delivery Plan vB.docx. Nothing was changed in Board Paper." | Pauses before the next click, never clicks while the wrong document is in front, resumes when the right one returns |
| User closes the Grammarly panel | Needs the user | "Grammarly was closed. Open it in Word to continue." | Pauses, re-checks with growing gaps, resumes by itself |
| Grammarly restarts or reloads | Recoverable | "Reconnecting to Grammarly" | Re-finds the panel and carries on |
| User closes the document | Needs the user | "The document was closed. Reopen it to continue." | Pauses. If Don't Save was chosen, edits since the last periodic save are lost, so the HUD names the backup |
| User closes Word | Fatal | "Word was closed." | Safe stop with summary and backup path |
| Word shows a dialog and stops answering | Needs the user | "Word is waiting for you. Close its dialog to continue." | Pauses, retries, resumes when Word answers |
| No real progress for 5 minutes of running time | Fatal | "No progress for 5 minutes. Stopped to be safe." | Safe stop, summary, Copy diagnostics. Time paused for the user does not count; reaching a new page counts as progress |
| Screen locks or the computer sleeps | Needs the user | "Paused while the screen was locked." | Sleep is blocked while running; a lock cannot be, so it pauses and resumes after unlock |

What exists in the engine today, read from `bulk_accept.py`: a periodic save every few accepts, a
no-progress stop (`max_idle_seconds`, default 20 minutes, which also counts time spent waiting for a
closed panel), geometric back-off while waiting for the panel in `ensure_root`, and a foreground check
that pulls Word back to the front on every cycle at
[bulk_accept.py:1166](../bulk_accept.py#L1166). That last behaviour always fights the user, and it is
the one the table above replaces.

**The idle limit.** Patrick set it to 5 minutes. Three interactions follow, and the first two are my
decisions to confirm. (1) Paused time must not count, or a person who switches away for six minutes
would end the run as a fatal error. (2) Reaching a new page must count as progress, because the last
sweep over a mostly clean document accepts nothing for several minutes by design, and would otherwise
end as a fatal "no progress" instead of "Done". (3) The engine's `stall_seconds` default is also 300,
so the panel re-acquire and the stop would fire at the same moment; the re-acquire needs a shorter
limit. The engine default has not been changed: this is the target design.

#### If the user changes which Word document is in front

Read from the code: the engine binds to its target document through COM when it starts, and finds the
Word window by title fragment, remembering that window handle once. At the top of every loop it checks
that the remembered window is in front and pulls it back if not. Two consequences. First, it fights a
person who deliberately opens another document. Second, and more serious, nothing checks that the
Grammarly panel is showing the target document before an accept. Grammarly follows whichever document has
focus, so an accept in the gap between a switch and the next check lands in the wrong document. The
length check measures only the target document, so that click would read as a "barren accept" and the
real edit would go unnoticed.

Design: before every Accept, not only between pages, confirm that the document in front is the target
(by Word's active document through COM, and by the front window's title). On a mismatch, pause without
clicking, show the other document's name, and resume when the target returns. Any Accepts made in the
window before the switch was noticed are listed on the finished screen. This check is new work and is
unverified: I have not tested what Word reports mid-switch. Detecting a deliberate switch (using recent keyboard and mouse
activity), a closed document, a closed Word, a blocked Word dialog and a locked screen is new work. When
Word is closed, the current engine does not stop cleanly: page scrolling logs a warning and the run waits
for the idle limit. Treat the Word-closed and dialog cases as unverified until tested.

### 4.8 Fatal error  (Q11, Q13)

The full window returns with a red header. It states what stopped, in one sentence, then shows:

- what was applied before the stop, and how long it ran
- where the **Backup** is, with Open backup folder
- **Copy diagnostics**, which copies card types, counts, timings and error messages only. Card text quotes
  the user's own document, so it is redacted by default. A checkbox "Include card text" is available for
  people who accept the risk. The full traceback goes to the log file, never to the screen. (Q13)

### 4.9 Finished  (Q4)

The full window returns with a green header and a plain summary card.

```
+------------------------------------------------+
|  [tick]  Done                                  |
|  1,284 suggestions applied in 2 h 14 min       |
|  Correctness 640   Clarity 410   Other 234      |
|                                                |
|  Edits are not tracked in Word's Review pane.  |
|  Your backup is here: C:\...\vB.backup-....docx|
|                                                |
|  [ Open document ]  [ Open backup folder ]     |
|                              [ Run again ]     |
+------------------------------------------------+
```

The finished screen also carries, in this order: the type breakdown, a "Your time" card, and a "This run"
card, then the warning about untracked edits and the actions.

- **Your time** compares three figures: doing the same number of suggestions by hand at 8 seconds each,
  the actual run time, and the time saved. The mockup computes them from the applied count and the run
  seconds. The 8 seconds is Patrick's figure and is stated on screen next to the number.
- **This run** lists the document name, its folder, page count, the thoroughness used and passes
  completed, start and finish times, the text length before and after (the engine's own progress
  measure), and the backup file name.
- **Grammarly result.** The first card on the finished screen says whether suggestions remain: Nothing
  left (after two clean passes in a row), Suggestions may remain (pass limit reached), or Suggestions
  remain (stopped early, including the 2 hour limit), or Stopped because the changes started repeating.
  The rules behind each are in [spec.md](spec.md). The hero colour follows the result: green only for
  Nothing left, amber otherwise. The mockup has a review switch to show all five states.
- **Links.** Every backup file name, the document name and its folder are clickable. A click opens
  Explorer with the file selected. The same applies to the backup name on the starting, fatal and
  recovery screens, and to "Open folder" on the consent screen.
- **Buy me a coffee** sits first in the action row, in a warm yellow that stands apart from the indigo
  Run again button. Its link target is a placeholder: a real page address is needed before release.

The figures in the picture are placeholders for layout only. A Windows toast announces finish or error
when the app is not the foreground window, and clicking it brings this screen back. The tray icon does
the same at any time. The breakdown by type exists today; it reads "Other" in place of the engine's
current "Unclassified" label until card categorising improves. (Q4, existing behaviour)

### 4.10 Relaunch after a crash: recovery banner  (Q12)

If the **Checkpoint** shows an unfinished **Run**, a banner sits at the top of the main window: "Your last
run stopped at page 37. Your backup is here." Buttons: Open backup folder, Resume sweep, Dismiss.
There is no automatic restore, because overwriting a document that is open in Word is destructive and
could lose newer edits. Restore stays a manual step with a short how-to link.

Resume sweep needs the checkpoint to record a resumable position, which it does not do today (it holds
totals only). That is an engine task listed in the handoff. (Q12)

### 4.11 Settings  (Q9)

A single page: Show safety notice again (switch), Open log folder, Version and licence, and a link to
the project page. Nothing else. (Q9)

### 4.12 Tray icon and toasts  (Q4)

One tray icon, indigo, with a small amber badge while paused. Menu: Show window, Pause or Resume, Stop,
Quit. Toasts are limited to finish, fatal error and needs-the-user. No progress toasts.

## 5. Empty, loading and edge states

| Situation | What the user sees |
|---|---|
| Word not running | Document card empty state "Open Word to begin", Start disabled |
| Document opened in Protected View, read-only or unsaved | Red row with the exact fix |
| Started elevated | Red row "Close and reopen normally", with why in one line |
| Two documents open | Dropdown lists both, the active one preselected |
| Panel not found at Start | Guidance card, Try again |
| Antivirus or SmartScreen warning | Installer note, README note |

## 6. What is deliberately not here

- No account, no sign-in, no telemetry.
- No custom frameless window, so snapping and system behaviour stay intact. (Q18)
- No GPL widget library. (Q17)
- No C#, C++ or .NET build yet. (Q15)
- Accessibility is best effort, not a release gate: keyboard reachability and control names are kept
  because they are cheap, but full screen reader and high-contrast certification is out of scope. (Q20)

## 7. Approvals (2026-10-05)

1. Accent and status colours: approved as proposed.
2. HUD position: starts at the top-left, and the user can move it anywhere. Position is
   remembered.
3. Thoroughness presets: approved. Quick is one pass, Standard is four, Thorough is eight.
4. "Other" replaces "Unclassified" in the type breakdown: approved.
5. HUD shows the current page and the **Sweep** number: approved.
6. FluentQt as a dependency: approved. Fallback stays PyQtDarkTheme plus our own stylesheet if the first
   spike fails.

## 8. Unverified

- No screen has been rendered. Corner sizes, spacing and colours have not been tested for contrast.
- That a non-activating HUD works in the chosen toolkit has not been proven; it is the first spike.
- Mica under the chosen toolkit is unproven, so the flat fallback is the design baseline.
- The assumption that the Panel sits on the right of the screen comes from one recorded run, and
  other layouts are possible.
