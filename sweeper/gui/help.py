"""Help for the setup page and the summary page: a small dialog opened by the round ? button."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

SETUP = (
    "Setting up a run",
    """
<h3>Document</h3>
<p>The Word documents that are open now. Pick the one to sweep, and press Refresh after opening another.
A document stored on SharePoint or OneDrive can be swept, but no backup copy can be made of it.</p>
<h3>How thorough</h3>
<p><b>Quick</b> walks the document once. <b>Standard</b> walks it again and again, up to four times, and stops
early after two walks in a row find nothing. <b>Thorough</b> keeps going until two in a row find nothing,
for two hours at most.</p>
<h3>Pages</h3>
<p>The whole document, or only the pages you type in.</p>
<h3>Options</h3>
<p><b>Track Changes</b> switches Word's own change tracking on, off, or leaves it. Grammarly's edits are not
reliably recorded as tracked changes either way, so the backup is the way back.
<b>Always return to Word</b> takes Word back to the front whenever something else steals focus.</p>
<h3>Start</h3>
<p>Start checks that Grammarly's assistant is open in Word and showing its suggestions. If it is not, nothing
runs. While it runs, this window hides and a small panel sits above Grammarly's.</p>
<h3>What it accepts</h3>
<p>Corrections, clarity and engagement suggestions, including Rephrase on rewrite cards. It never accepts a
tone change such as "Want to sound friendlier?", and it never dismisses anything.</p>
<h3>If something goes wrong</h3>
<p>Every run writes an audit log and screenshots. The <b>Advanced</b> tab has buttons to open them, Copy
diagnostics to collect them for support, and Clean up to remove old logs, screenshots, reports and
diagnostic bundles. Backups of your documents are never removed there.</p>
""",
)

SUMMARY = (
    "Reading the summary",
    """
<h3>The banner</h3>
<p>Green means the run finished and nothing was left. Violet means suggestions may remain: the run hit its
pass limit, or Grammarly began undoing its own changes. Red means the run could not continue.</p>
<h3>The tiles</h3>
<p>Suggestions applied, by Grammarly's four types, plus any it could not classify.</p>
<h3>Your time</h3>
<p>The time it would take by hand at eight seconds a suggestion, the time this run took, and the difference.</p>
<h3>This run</h3>
<p>The document and its location are links. <b>Mode</b> is the preset and its pass limit. <b>Passes</b> says what
each pass did. A pass is one walk through the whole document. A pass that applies changes is where the
work happened. Passes that find nothing are checks: Grammarly can reveal new suggestions once earlier ones
are applied, so Standard keeps checking until two passes in a row find nothing. A document fixed in one pass
and then checked twice shows as one pass of changes and two checks.</p>
<p><b>Where it changed</b> is one block per page. Colour is the commonest kind of change on that page, grey
means nothing changed, and an outline means Grammarly could not read the page. Hover a block for a short
summary of what changed there. <b>Copy summary</b> puts the result on the clipboard as plain text.</p>
<p><b>Backup</b> is the copy of the document made before the run. It is your way back, so keep it until you
are happy.</p>
<h3>The buttons</h3>
<p><b>Open document</b>, <b>Open backup folder</b> and <b>Open report</b> open those items. The report lists
every change with its before and after text. The audit log, screenshots and diagnostics are on the setup
page's <b>Advanced</b> tab. <b>Resume</b> appears when a run stopped partway and
carries on from that page. <b>Run again</b> returns to the setup page.</p>
""",
)


class HelpDialog(QDialog):
    def __init__(self, parent, title: str, body: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(480, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        head = QLabel(title)
        head.setObjectName("headline")
        layout.addWidget(head)
        text = QTextBrowser()
        text.setFrameShape(QTextBrowser.NoFrame)
        text.setOpenExternalLinks(True)
        text.setHtml(body)
        layout.addWidget(text, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)


def help_button(parent, page: tuple[str, str]) -> QPushButton:
    """The round ? button that opens `page`, a (title, html) pair."""
    button = QPushButton("?")
    button.setObjectName("help")
    button.setToolTip("Help")
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(lambda: HelpDialog(parent, page[0], page[1]).exec())
    return button
