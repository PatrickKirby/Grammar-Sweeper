# Grammar Sweeper

Applies Grammarly's suggestions to a Word document in a loop by driving Grammarly's review panel, because no API exists to do it. This glossary covers the engine and the planned desktop interface.

## Language

**Panel**:
Grammarly's review window, a top-level window named `Grammarly` owned by `Grammarly.Desktop`, separate from Word. It renders its feed only while Word is the foreground window.
_Avoid_: pane, task pane, add-in pane, assistant window

**Feed**:
The list of collapsed suggestions shown in the **Panel**, scoped to the region of the document on screen.
_Avoid_: list, queue

**Row**:
One collapsed entry in the **Feed**. Opening it reveals its **Card**; it applies nothing itself.
_Avoid_: item, suggestion (when meaning the collapsed form)

**Card**:
An expanded suggestion carrying the accept control. A **Card** exists only after its **Row** is opened.
_Avoid_: suggestion card, popup

**Accept**:
One invocation of a **Card**'s primary button, which applies a suggestion to the document.
_Avoid_: click, apply (when meaning the whole action)

**Barren accept**:
An **Accept** after which the document length did not change. A repeated one blacklists its control for the current page.
_Avoid_: failed accept, no-op

**Sweep**:
One pass of the engine down the document, stopping every page step to drain the **Feed**. Sweeps repeat until one accepts nothing or a limit is reached.
_Avoid_: scan, loop (when meaning one pass)

**Run**:
One start to finish execution: preflight, backup, one or more **Sweeps**, and a summary.
_Avoid_: session, job

**Backup**:
The timestamped copy of the document written before the first **Accept** of a **Run**. It is the only dependable undo, because Track Changes does not reliably record Grammarly's edits.
_Avoid_: snapshot, restore point

**Checkpoint**:
The small file rewritten during a **Run** holding running totals. It lets the next launch report where an unfinished **Run** stopped.
_Avoid_: save state, resume file

## Interface

**HUD**:
The small always-on-top, non-activating window shown during a **Run**, holding progress, the applied count and Pause. It must never take focus from Word.
_Avoid_: overlay, mini window

**Preflight**:
The checklist of conditions verified before a **Run** can start. Red rows block Start, amber rows warn. The **Panel** row is checked at Start, not live.
_Avoid_: validation, health check

**Consent screen**:
The one-time notice that the tool applies suggestions unreviewed and that the **Backup** is the only undo. "Don't show again" suppresses it, and it returns if the backup is off, Track Changes is forced off, or the major version changes.
_Avoid_: disclaimer dialog, warning

**Error tier**:
The classification of a problem during a **Run** as recoverable, needs the user, or fatal. It decides whether the **Run** continues, pauses, or stops.
_Avoid_: severity, error level

**Spec**:
The single written definition of screens, labels, flow and engine behaviour that every build is judged against. The Python build leads while the C# build is deferred.
_Avoid_: design doc, requirements

## Relationships

- A **Run** contains one or more **Sweeps**; each **Sweep** drains the **Feed** at many page stops.
- Draining the **Feed** means opening a **Row** to reveal its **Card**, then performing an **Accept**.
- A **Run** always begins with **Preflight** and a **Backup**, and always shows the **HUD** while active.
- An unfinished **Run** leaves a **Checkpoint**, which the next launch reports.

## Example dialogue

> **Dev:** The **Panel** is empty after I launch. Is the engine broken?
> **Expert:** No. The **Panel** renders its **Feed** only while Word is in front. **Preflight** shows that row as "Checked when you press Start" for that reason.
> **Dev:** And once it starts, the main window shrinks?
> **Expert:** Into the **HUD**, which never takes focus. A normal window would pull focus from Word and every **Accept** after that would be **Barren**.

## Flagged ambiguities

- "pane", "task pane" and "add-in pane" were used for the **Panel** in early code and docs, wrongly implying it lives inside Word. Resolved: **Panel**.
- "suggestion" was used for both a collapsed **Row** and an expanded **Card**. Resolved: use **Row** or **Card**; "suggestion" is the generic Grammarly word only.
