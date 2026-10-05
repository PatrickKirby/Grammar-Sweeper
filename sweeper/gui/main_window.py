"""Main window: consent, ready, finished and fatal screens. The running screen
is the HUD, so this window hides while a run is in progress."""

from __future__ import annotations

import html

import threading
from pathlib import Path

import bulk_accept as engine
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QRadioButton, QScrollArea, QSpinBox, QStackedWidget, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from .. import brand, cleanup, history, rules, runner
from .. import summary as summaries
from ..changes import ALL_TYPES, TYPE_COLOURS
from ..rules import CLEAR, LIMIT, REPEATING, manual_estimate_seconds
from ..settings import APERTURA_URL, COFFEE_URL, COMPANY, REPO_URL, Settings, log_dir, settings_dir
from . import snap, style
from .. import version
from .help import SETUP, SUMMARY, help_button
from .hud import Hud
from .strip import PageStrip, Sparkline

ICON = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
HEADER_LOGO = 60  # the tile, in layout pixels
SUMMARY_LOGO = 44

# Where each Delete category lives, for the Open link beside it.
CATEGORY_TARGETS = {
    "screenshots": log_dir() / "shots",
    "audit": log_dir() / "audit.log",
    "runlog": log_dir(),
    "reports": log_dir(),
    "changes": log_dir(),
    "diagnostics": settings_dir() / "diagnostics",
}

PRESET_TEXT = {
    "quick": ("Quick", "One pass through the document. Fast, but it cannot confirm nothing is left."),
    "standard": ("Standard", "Up to four passes. Stops early after two clean passes in a row."),
    "thorough": ("Thorough", "Keeps going until two clean passes in a row. Stops at 2 hours at the latest."),
}


class Bridge(QObject):
    """Carries engine-thread callbacks onto the interface thread."""

    event = Signal(str, dict)
    done = Signal(object)
    preflight = Signal(dict)
    grammarly = Signal(bool)


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(8)
    return frame, layout


def logo_label(size: int) -> QLabel:
    """The styled logo at `size`, sharp on a high-density screen. An empty label when it cannot be drawn."""
    item = QLabel()
    item.setAttribute(Qt.WA_TranslucentBackground, True)
    try:
        pixmap = QPixmap()
        pixmap.loadFromData(brand.logo_png(size, 2))
        pixmap.setDevicePixelRatio(2)
        item.setPixmap(pixmap)
        item.setFixedSize(brand.display_size(size), brand.display_size(size))
    except Exception:  # noqa: BLE001 - the window works without a logo
        pass
    return item


def set_tone(widget: QWidget, tone: str) -> None:
    """Switch a label between the ok, warn and bad styles, and repaint it."""
    widget.setObjectName(tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    item.setWordWrap(wrap)
    return item


class MainWindow(QWidget):
    def __init__(self, settings: Settings, dark: bool) -> None:
        super().__init__()
        self.settings = settings
        self.dark = dark
        self.setWindowTitle("Grammar Sweeper")
        self.setObjectName("window")
        self.setAttribute(Qt.WA_StyledBackground, True)
        if ICON.exists():
            self.setWindowIcon(QIcon(str(ICON)))
        self.setMinimumSize(580, 600)
        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        self.bridge.done.connect(self._on_done)
        self.bridge.preflight.connect(self._on_preflight)
        self.bridge.grammarly.connect(self._on_grammarly)
        self.job: runner.Job | None = None
        self.hud: Hud | None = None
        self.paths: list[str] = []
        self.warnings: dict = {}
        self._app_w = 0
        self.tray = QSystemTrayIcon(QIcon(str(ICON)) if ICON.exists() else QIcon(), self)

        self.stack = QStackedWidget()
        self.consent_page = self._build_consent()
        self.ready_page = self._build_ready()
        self.finished_page = QWidget()
        self.fatal_page = QWidget()
        for page in (self.consent_page, self.ready_page, self.finished_page, self.fatal_page):
            self.stack.addWidget(page)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.stack)
        outer.addWidget(scroll)
        self._snapped = False
        # The start page has one scroll area of its own, so the window's scrolls only for the long pages.
        self.scroll = scroll
        self.stack.currentChanged.connect(self._set_scroll_policy)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

        self._pane_note = ""
        self.pane = snap.PaneKeeper(
            lambda: self._app_w or snap.app_width(self.minimumWidth()),
            lambda: self.doc_box.currentData(),
            lambda: int(self.winId()),
            lambda event, **data: engine.AUDIT.write(event, **data),
        )
        self.pane_timer = QTimer(self)
        self.pane_timer.timeout.connect(self._keep_pane)
        self.pane_timer.start(500)

        if settings["consent_accepted"]:
            self._show_ready()
        else:
            self.stack.setCurrentWidget(self.consent_page)

    def _set_scroll_policy(self, _index: int = 0) -> None:
        on_start_page = self.stack.currentWidget() is self.ready_page
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if on_start_page else Qt.ScrollBarAsNeeded)

    # Screens -------------------------------------------------------------

    def _build_consent(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Before you start", "title"))
        frame, inner = card()
        for text in (
            "Grammar Sweeper is an independent tool. It is not made by, affiliated with, or endorsed by Grammarly or Microsoft.",
            "It clicks Grammarly's own Accept buttons in Word, one after another. Every accepted suggestion rewrites your document.",
            "A timestamped backup copy is saved next to your file before the first click. That copy is your undo. Word's Track Changes is switched on but does not reliably record Grammarly's edits.",
            "Use it at your own risk, on documents you can recover.",
        ):
            inner.addWidget(label(text))
        layout.addWidget(frame)
        self.agree = QCheckBox("I understand, and I want to continue")
        self.dont_show = QCheckBox("Don't show this again")
        self.dont_show.setChecked(True)
        go = QPushButton("Continue")
        go.setObjectName("primary")
        go.setEnabled(False)
        self.agree.toggled.connect(go.setEnabled)
        go.clicked.connect(self._accept_consent)
        layout.addWidget(self.agree)
        layout.addWidget(self.dont_show)
        layout.addStretch(1)
        layout.addWidget(go)
        return page

    def _accept_consent(self) -> None:
        if self.dont_show.isChecked():
            self.settings["consent_accepted"] = True
        self._show_ready()

    def _build_ready(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QHBoxLayout()
        heading.addWidget(label("Grammar Sweeper", "title", wrap=False))
        heading.addWidget(logo_label(HEADER_LOGO))
        heading.addStretch(1)
        heading.addWidget(help_button(self, SETUP), 0, Qt.AlignTop)
        layout.addLayout(heading)
        layout.addWidget(label("Accept Grammarly suggestions hands free.", "muted"))

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self.tabs = tabs
        setup_tab = QWidget()
        setup_layout = QVBoxLayout(setup_tab)
        setup_layout.setContentsMargins(0, 12, 0, 0)
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(0, 12, 0, 0)
        tabs.addTab(setup_tab, "Setup")
        tabs.addTab(history_tab, "Recent runs")
        tabs.addTab(self._build_advanced(), "Advanced")
        layout.addWidget(tabs, 1)

        frame, inner = card()
        inner.addWidget(label("Document", "section"))
        row = QHBoxLayout()
        self.doc_box = QComboBox()
        self.doc_box.setMinimumWidth(320)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        row.addWidget(self.doc_box, 1)
        row.addWidget(refresh)
        inner.addLayout(row)
        self.page_counts: dict[str, int] = {}
        self.doc_pages = label("", "muted", wrap=False)
        inner.addWidget(self.doc_pages)
        self.doc_status = label("", "muted")
        self.doc_box.currentIndexChanged.connect(lambda _i: self._show_warnings())
        self.ready_badge = label("", "ok", wrap=False)
        inner.addWidget(self.ready_badge)
        inner.addWidget(self.doc_status)
        setup_layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("How thorough", "section"))
        self.presets = QButtonGroup(self)
        for key, (name, tip) in PRESET_TEXT.items():
            button = QRadioButton(name)
            button.setObjectName("preset")
            button.setToolTip(tip)
            button.setProperty("preset", key)
            button.setChecked(key == self.settings["preset"])
            self.presets.addButton(button)
            line = QHBoxLayout()
            line.setSpacing(10)
            line.addWidget(button)
            line.addWidget(label(tip, "presetdesc"), 1)
            inner.addLayout(line)
        setup_layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("Pages", "section"))
        self.whole = QRadioButton("Whole document")
        self.whole.setChecked(True)
        self.range = QRadioButton("Only pages")
        self.first = QSpinBox()
        self.first.setButtonSymbols(QSpinBox.NoButtons)
        self.first.setRange(1, 9999)
        self.last = QSpinBox()
        self.last.setButtonSymbols(QSpinBox.NoButtons)
        self.last.setRange(1, 9999)
        self.last.setValue(9999)
        pages = QHBoxLayout()
        pages.addWidget(self.range)
        pages.addWidget(self.first)
        pages.addWidget(QLabel("to"))
        pages.addWidget(self.last)
        pages.addStretch(1)
        inner.addWidget(self.whole)
        inner.addLayout(pages)
        setup_layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("Options", "section"))
        track = QHBoxLayout()
        track.addWidget(QLabel("Track Changes"))
        self.track_box = QComboBox()
        for value, text in (("on", "Switch on"), ("off", "Switch off"), ("leave", "Leave as it is")):
            self.track_box.addItem(text, value)
        self.track_box.setCurrentIndex(max(0, self.track_box.findData(self.settings["track_changes"])))
        self.track_box.setToolTip("Grammarly's edits are not reliably recorded as tracked changes. The backup is the undo.")
        track.addWidget(self.track_box)
        track.addStretch(1)
        inner.addLayout(track)
        self.force_box = QCheckBox("Always return to Word, even if I switch away")
        self.force_box.setChecked(bool(self.settings["force_focus"]))
        self.force_box.setToolTip(
            "Off: the run pauses while you use another app. On: it takes Word back to the front every time."
        )
        inner.addWidget(self.force_box)
        self.report_box = QCheckBox("Open the report when the run ends")
        self.report_box.setChecked(bool(self.settings["open_report"]))
        inner.addWidget(self.report_box)
        setup_layout.addWidget(frame)

        frame, inner = card()
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.history_box = QVBoxLayout(holder)
        self.history_box.setContentsMargins(0, 0, 0, 0)
        self.history_box.setSpacing(4)
        history_scroll = QScrollArea()  # the only scrolling on this page
        history_scroll.setWidgetResizable(True)
        history_scroll.setFrameShape(QFrame.NoFrame)
        history_scroll.setMinimumHeight(64)
        history_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        history_scroll.viewport().setAutoFillBackground(False)
        history_scroll.setWidget(holder)
        inner.addWidget(history_scroll, 1)
        history_layout.addWidget(frame, 1)

        setup_layout.addStretch(1)

        self.grammarly_status = label("", "muted")
        layout.addWidget(self.grammarly_status)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        layout.addWidget(self.start_button)
        tabs.currentChanged.connect(self._tab_changed)
        layout.addLayout(self._footer_row(coffee=False))
        return page

    def _tab_changed(self, index: int) -> None:
        """Start and the Grammarly status belong to the Setup tab only."""
        on_setup = index == 0
        self.start_button.setVisible(on_setup)
        self.grammarly_status.setVisible(on_setup)

    def _show_ready(self) -> None:
        self.stack.setCurrentWidget(self.ready_page)
        self._refresh_history()
        self._refresh_advanced()
        self._refresh()

    def _refresh(self) -> None:
        self.doc_status.setText("Looking for open Word documents")
        self.start_button.setEnabled(False)
        threading.Thread(target=lambda: self.bridge.preflight.emit(runner.preflight()), daemon=True).start()

    def _on_preflight(self, info: dict) -> None:
        self.paths = info["paths"]
        self.warnings = info.get("warnings", {})
        self.page_counts = info.get("pages", {})
        self._elevated = bool(info["elevated"])
        self.doc_box.clear()
        for path in self.paths:
            self.doc_box.addItem(Path(path).name, path)
        for index, path in enumerate(self.paths):  # prefer a document Word has a window for
            if snap.find_word(Path(path).stem):
                self.doc_box.setCurrentIndex(index)
                break
        if self._elevated:
            self._base_status = "This program is running as administrator, so it cannot reach Word. Run it from a normal session."
        elif not self.paths:
            self._base_status = "No open Word document found. Open one, save it once, then press Refresh."
        elif len(self.paths) > 1:
            self._base_status = f"{len(self.paths)} documents are open. Pick the one to sweep."
        else:
            self._base_status = ""
        self._show_warnings()
        if info["panel"] is True:
            self.grammarly_status.setText("Grammarly's panel is open.")
        else:  # the panel is only there while Word is in front, so absence here proves nothing
            self.grammarly_status.setText("")
        self.start_button.setEnabled(bool(self.paths) and not self._elevated)
        if not self._snapped:
            self._snapped = True
            self._snap_layout()

    def _show_warnings(self) -> None:
        """The colour-coded status line, and under it the selected document's notes."""
        notes = self.warnings.get(self.doc_box.currentData() or "", [])
        name = self.doc_box.currentText()
        lines = [self._base_status] if getattr(self, "_base_status", "") else []
        lines += [f"{name} {note}" for note in notes]
        if self._pane_note:
            lines.append(self._pane_note)
        self.doc_status.setText("\n".join(lines))
        self.doc_status.setVisible(bool(lines))
        if getattr(self, "_elevated", False) or not self.paths:
            tone, text = "bad", "\u25cf  Not ready"
        elif notes or self._pane_note:
            tone, text = "warn", "\u25cf  Ready, with notes"
        else:
            tone, text = "ok", "\u25cf  Ready"
        self.ready_badge.setText(text)
        set_tone(self.ready_badge, tone)
        pages = self.page_counts.get(self.doc_box.currentData() or "")
        self.doc_pages.setText(f"{pages:,} page{'s' if pages != 1 else ''}" if pages else "")
        self.doc_pages.setVisible(bool(pages))

    def _refresh_history(self) -> None:
        while self.history_box.count():
            item = self.history_box.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()
                old.setParent(None)  # off the page at once, deleted when Qt next idles
                old.deleteLater()
        entries = history.load()[-20:][::-1]
        if not entries:
            self.history_box.addWidget(label("No runs yet.", "muted"))
        for entry in entries:
            self.history_box.addWidget(self._history_row(entry))
        self.history_box.addStretch(1)

    def _history_row(self, entry: dict) -> QFrame:
        """One past run: the document as a link on the first line, the figures on the second, and the
        report as a link at the right."""
        accent = style.ACCENT_NOW
        name = html.escape(entry.get("document") or "Document")
        path = entry.get("path", "")
        if path:
            online = path.lower().startswith(("http://", "https://"))
            href = html.escape(path if online else QUrl.fromLocalFile(path).toString())
            title = f'<a href="{href}" style="color: {accent}; text-decoration: none;"><b>{name}</b></a>'
        else:
            title = f"<b>{name}</b>"
        frame = QFrame()
        frame.setObjectName("runrow")
        column = QVBoxLayout(frame)
        column.setContentsMargins(0, 8, 0, 8)
        column.setSpacing(2)
        top = QHBoxLayout()
        head = label(title, "value", wrap=False)
        head.setTextFormat(Qt.RichText)
        head.setOpenExternalLinks(True)
        top.addWidget(head, 1)
        links = []
        backup = entry.get("backup")
        for text, target in (
            ("Backup", str(Path(backup).parent) if backup else ""),
            ("Report", entry.get("report") or ""),
        ):
            if target and Path(target).exists():
                href = html.escape(QUrl.fromLocalFile(target).toString())
                links.append(f'<a href="{href}" style="color: {accent}; text-decoration: none;">{text}</a>')
        if links:
            link = label("  \u00b7  ".join(links), "value", wrap=False)
            link.setTextFormat(Qt.RichText)
            link.setOpenExternalLinks(True)
            top.addWidget(link)
        column.addLayout(top)
        applied = entry.get("applied", 0)
        saved = summaries.format_minutes(entry.get("saved", 0))
        detail = QHBoxLayout()
        detail.addWidget(label(f"{entry.get('date', '')}  \u00b7  {applied:,} applied  \u00b7  saved {saved}", "muted"), 1)
        if entry.get("spark"):
            detail.addWidget(Sparkline(entry["spark"], accent))
        column.addLayout(detail)
        return frame

    PANE_TEXT = {
        "starting": "Starting Word with the document.",
        "cannot-start": "Word could not be started with the document. Open it in Word.",
        "no-window": "Word has no window for this document. Open it in Word.",
        "off-target": "Word would not move into its pane. The audit log has the measured position.",
    }

    def _snap_layout(self) -> None:
        """App on the left, Word filling the rest of the screen. Starts Word with the
        document when it is not open."""
        self._keep_pane(start=True)

    def _keep_pane(self, start: bool = False) -> None:
        """One enforcement pass, on a timer for as long as the app runs. A failure is
        written to the audit log and tried again on the next pass."""
        try:
            self._app_w = snap.app_width(self.minimumWidth())
            state = self.pane.tick(self.isVisible(), start)
        except Exception as exc:  # noqa: BLE001 - logged, and the next pass tries again
            engine.AUDIT.write("GUI_PANE_ERROR", error=repr(exc))
            return
        note = self.PANE_TEXT.get(state, "")
        if note != self._pane_note:
            self._pane_note = note
            self._show_warnings()
        self._dock_hud()

    def _dock_hud(self) -> None:
        """While running, the toaster sits directly above Grammarly's panel at its width.
        The panel is moved down and shortened to make the room."""
        if self.hud is None:
            return
        try:
            self.hud.adjustSize()
            rect = snap.dock_above_grammarly(self.hud.height())
        except Exception as exc:  # noqa: BLE001 - logged, and the next pass tries again
            engine.AUDIT.write("GUI_DOCK_ERROR", error=repr(exc))
            return
        self.hud.locked = rect is not None
        if rect is not None:
            self.hud.dock(rect)

    # Running -------------------------------------------------------------

    def _preset(self) -> str:
        button = self.presets.checkedButton()
        return button.property("preset") if button else "standard"

    def _start(self) -> None:
        """Nothing starts until Grammarly's assistant is open and showing its feed. Word goes
        to the front first, because the panel is not there while another window is."""
        document = self.doc_box.currentData()
        if not document:
            return
        self.start_button.setEnabled(False)
        self.grammarly_status.setText("Checking that Grammarly is open and ready in Word.")
        self._snap_layout()
        self._word_to_front("ready-check")
        stem = Path(document).stem
        threading.Thread(
            target=lambda: self.bridge.grammarly.emit(runner.grammarly_ready(stem)), daemon=True
        ).start()

    def _on_grammarly(self, ready: bool) -> None:
        if not ready:
            engine.AUDIT.write("GRAMMARLY_NOT_READY")
            self.grammarly_status.setText(
                "Grammarly is not open and ready in Word. Open its assistant panel in Word, then press Start."
            )
            self.start_button.setEnabled(bool(self.paths))
            return
        self.grammarly_status.setText("Grammarly's panel is open.")
        self._launch()

    def _launch(self) -> None:
        document = self.doc_box.currentData()
        if not document:
            return
        self.settings["preset"] = self._preset()
        first, last = (self.first.value(), self.last.value()) if self.range.isChecked() else (1, 0)
        self.settings["track_changes"] = self.track_box.currentData()
        self.settings["force_focus"] = self.force_box.isChecked()
        self.settings["open_report"] = self.report_box.isChecked()
        args = runner.build_args(
            self._preset(),
            Path(document).name,
            first,
            0 if last >= 9999 else last,
            self.track_box.currentData(),
            self.force_box.isChecked(),
        )
        self.job = runner.Job(
            args,
            lambda kind, **data: self.bridge.event.emit(kind, data),
            lambda job: self.bridge.done.emit(job),
        )
        self._snap_layout()
        self._word_to_front()
        self.hud = Hud(
            lambda: self.job.control.clock.running_seconds(),
            None,  # the toaster is docked above Grammarly's panel, not remembered
            self.dark,
        )
        self.hud.pause_toggled.connect(self._on_pause)
        self.hud.front_requested.connect(self._on_front_requested)
        self.hud.stop_requested.connect(lambda: self.job.control.request_stop("Stop"))
        self.hud.show()
        self._dock_hud()
        self.hide()
        self.tray.show()
        self.job.start()

    def _on_pause(self, paused: bool) -> None:
        if self.job is None:
            return
        if paused:
            self.job.control.request_pause()
        else:
            self._word_to_front("hud-resume")
            QTimer.singleShot(500, lambda: self._word_to_front("hud-resume-retry"))  # after the click settles
            self.job.control.request_resume()

    def _on_front_requested(self) -> None:
        self._word_to_front("hud-resume-held")
        QTimer.singleShot(500, lambda: self._word_to_front("hud-resume-held-retry"))

    def _word_to_front(self, why: str = "start") -> bool:
        """Word placed in its share of the screen and forced to the front. Every try goes to
        the audit log with what ended up in front, so a failure can be read there."""
        ok = False
        try:
            document = self.doc_box.currentData()
            ok = snap.place_word(
                Path(document).stem if document else None,
                self._app_w or snap.app_width(self.minimumWidth()),
                front=True,
            )
        except Exception as exc:  # noqa: BLE001 - the engine also takes Word back
            engine.AUDIT.write("GUI_FRONT_ERROR", why=why, error=repr(exc))
        try:
            _hwnd, exe, title = engine.foreground_window()
            engine.AUDIT.write("GUI_FRONT", why=why, ok=ok, front_exe=exe, front_title=title[:50])
        except Exception:  # noqa: BLE001 - logging must not break the click
            pass
        return ok

    def _tick(self) -> None:
        if self.hud is not None and self.job is not None:
            self.hud.tick()

    def _on_event(self, kind: str, data: dict) -> None:
        if self.hud is None:
            return
        if kind == "progress":
            self.hud.set_progress(
                data["applied"], data["page"], data["pages"], data["sweep"], data["percent"], data.get("eta"),
                data.get("by_type"), data.get("limit"),
                data.get("heat"), data.get("first", 1), data.get("last", 0), data.get("step", 5), data,
            )
        elif kind == "state":
            self.hud.set_state(data["state"], data["message"])

    # Finished ------------------------------------------------------------

    def _on_done(self, job: runner.Job) -> None:
        if self.hud is not None:
            self.hud.close()
            self.hud = None
        self.tray.hide()
        self.show()
        self.activateWindow()
        summary = job.summary
        if job.crashed or summary is None or summary.refused or summary.budget is None:
            reason = job.crashed or (summary.refused if summary else None) or "The run could not start."
            self._show_fatal(reason, summary)
        else:
            self._show_finished(summary)
        self.job = None

    def _swap(self, old: QWidget, new: QWidget) -> None:
        index = self.stack.indexOf(old)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(index, new)
        self.stack.setCurrentWidget(new)

    def _link(self, text: str, target: str) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(target)))
        return button

    def _show_fatal(self, reason: str, summary) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("The run could not continue", "headline"))
        frame, inner = card()
        inner.addWidget(label(reason))
        inner.addWidget(label("Nothing was changed if the run never started. The full details are in the log.", "muted"))
        layout.addWidget(frame)
        row = QHBoxLayout()
        row.addWidget(self._link("Open log folder", str(log_dir())))
        row.addWidget(self._link("Open audit log", str(log_dir() / "audit.log")))
        if summary is not None and summary.backup:
            row.addWidget(self._link("Open backup folder", str(Path(summary.backup).parent)))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        again = QPushButton("Back")
        again.setObjectName("primary")
        again.clicked.connect(self._back_to_ready)
        layout.addWidget(again)
        self._swap(self.fatal_page, page)
        self.fatal_page = page

    def _headline(self, outcome: rules.Outcome) -> tuple[str, str, str]:
        scope = "" if outcome.complete_range else " in the chosen pages only"
        if outcome.result == CLEAR:
            return "Nothing left", f"Two full passes in a row found no suggestions{scope}.", "ok"
        if outcome.result == LIMIT:
            if outcome.last_applied == 0:
                return "One pass found nothing", "Run Standard to confirm.", "warn"
            name = rules_name(outcome.preset)
            return (
                "Suggestions may remain",
                f"{name} finished {outcome.passes} pass(es). The last one still applied {outcome.last_applied}. "
                "Run Thorough to keep going until nothing is left.",
                "warn",
            )
        if outcome.result == REPEATING:
            a, b = outcome.matched_passes or (0, 0)
            return (
                "Stopped: the changes started repeating",
                f"Passes {a} and {b} ended with identical text, so Grammarly is undoing its own changes. "
                "More passes will not help. Review the sections that keep changing.",
                "bad",
            )
        return "Suggestions remain", f"Stopped: {outcome.reason}.", "bad"

    def _tile(self, value: str, caption: str, tone: str = "", colour: str = "") -> QFrame:
        frame, inner = card()
        inner.setSpacing(2)
        inner.setContentsMargins(6, 12, 6, 12)
        if colour:
            strip = QFrame()
            strip.setFixedHeight(4)
            strip.setStyleSheet(f"background: {colour}; border: none; border-radius: 2px;")
            inner.addWidget(strip)
        top = label(value, "stat" + tone, wrap=False)
        top.setAlignment(Qt.AlignCenter)
        low = label(caption, "tilecaption", wrap=True)
        low.setAlignment(Qt.AlignCenter)
        inner.addWidget(top)
        inner.addWidget(low)
        return frame

    def _tile_row(self, tiles: list[QFrame]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for tile in tiles:
            row.addWidget(tile, 1)
        return row

    def _show_finished(self, summary) -> None:
        budget = summary.budget
        outcome = budget.outcome or budget.policy.failed(budget.stop_reason or "the run ended")
        head, body, tone = self._headline(outcome)
        run_seconds = budget.policy.clock.running_seconds()
        manual = manual_estimate_seconds(budget.accepted)
        saved = max(0, manual - run_seconds)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.addLayout(self._brand_row())

        # Banner: tinted by outcome, icon disc, headline, one line of fact.
        banner = QFrame()
        banner.setObjectName("banner" + tone)
        row = QHBoxLayout(banner)
        row.setContentsMargins(18, 14, 18, 14)
        disc = QLabel({"ok": "\u2713", "warn": "!", "bad": "\u2715"}.get(tone, "!"))
        disc.setObjectName("disc" + tone)
        disc.setAlignment(Qt.AlignCenter)
        disc.setFixedSize(34, 34)
        words = QVBoxLayout()
        words.setSpacing(0)
        clear = outcome.result == CLEAR
        words.addWidget(label("Done" if clear else head, "bannerhead"))
        words.addWidget(
            label(f"{budget.accepted:,} suggestions applied in {summaries.format_minutes(run_seconds)}", "bannersub")
        )
        row.addWidget(disc)
        row.addLayout(words, 1)
        row.addWidget(help_button(self, SUMMARY), 0, Qt.AlignTop)
        layout.addWidget(banner)
        if not clear or not outcome.complete_range:
            layout.addWidget(label(body, "muted"))

        by = budget.by_type
        layout.addLayout(self._tile_row([self._tile(f"{by.get(key, 0):,}", key, colour=TYPE_COLOURS[key]) for key in ALL_TYPES]))

        records = budget.changes.records if budget.changes is not None else []
        changed = summaries.page_changes(records)
        unread = {int(stop[1:]) for stop in budget.unread if stop[1:].isdigit()}
        if budget.pages > 0:
            frame, inner = card()
            inner.addWidget(label("Where it changed", "section"))
            inner.addWidget(PageStrip(budget.pages, changed, unread))
            ends = QHBoxLayout()
            ends.addWidget(label("Page 1", "tilecaption", wrap=False))
            ends.addStretch(1)
            ends.addWidget(label("Hover a block to see what changed on that page", "tilecaption", wrap=False))
            ends.addStretch(1)
            ends.addWidget(label(f"Page {budget.pages}", "tilecaption", wrap=False))
            inner.addLayout(ends)
            layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("Your time", "section"))
        inner.addLayout(
            self._tile_row(
                [
                    self._tile(summaries.format_minutes(manual), "By hand"),
                    self._tile(summaries.format_minutes(run_seconds), "This run"),
                    self._tile(summaries.format_minutes(saved), "Saved", "ok"),
                ]
            )
        )
        layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("This run", "section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        document = summary.document or ""
        online = document.lower().startswith(("http://", "https://"))
        path = None if online else (Path(document) if document else None)
        name = document.rsplit("/", 1)[-1] if online else (path.name if path else "Unknown document")
        place = document.rsplit("/", 1)[0] if online else (str(path.parent) if path else "")
        started = summary.started.strftime("%H:%M")
        ended = summary.finished.strftime("%H:%M") if summary.finished else "?"
        chars = (
            f"{summary.chars_before:,} to {summary.chars_after:,} characters"
            if summary.chars_before >= 0 and summary.chars_after >= 0
            else "Not available"
        )
        backup = Path(summary.backup).name if summary.backup else "None made"
        if online and not summary.backup:
            backup = "None made, the document is stored online"
        facts = [
            ("Document", link_text(name, document, online), "value"),
            ("Location", link_text(place, place if online else (str(path.parent) if path else ""), online), "value"),
            ("Pages", f"{budget.pages}" if budget.pages > 0 else "Not available", "value"),
            ("Mode", pass_mode(budget.policy.preset, budget.policy.pass_limit), "value"),
            ("Passes", passes_text(budget.policy.passes, outcome), "value"),
            ("Started, finished", f"{started}, {ended}", "value"),
            ("Length of text", chars, "value"),
            ("Backup", backup, "value"),
        ]
        for index, (key, value, kind) in enumerate(facts):
            grid.addWidget(label(key, "key", wrap=False), index, 0, Qt.AlignTop)
            item = label(value, kind)
            item.setTextFormat(Qt.RichText)
            item.setOpenExternalLinks(True)
            item.setTextInteractionFlags(Qt.TextBrowserInteraction)
            grid.addWidget(item, index, 1)
        grid.setColumnStretch(1, 1)
        inner.addLayout(grid)
        layout.addWidget(frame)

        tracked = self.settings["track_changes"] == "on"
        note = QFrame()
        note.setObjectName("notice")
        notice = QVBoxLayout(note)
        notice.setContentsMargins(14, 12, 14, 12)
        notice.addWidget(
            label(
                "Edits are tracked in Word's Review pane. Reject any you disagree with, and keep the backup until you are happy."
                if tracked
                else "Edits are not tracked in Word's Review pane. Review the document, and keep the backup until you are happy.",
                "noticetext",
            )
        )
        layout.addWidget(note)

        links = QGridLayout()
        links.setHorizontalSpacing(8)
        links.setVerticalSpacing(8)
        link_buttons = []
        if summary.backup:
            link_buttons.append(self._link("Open backup folder", str(Path(summary.backup).parent)))
        if summary.document:
            link_buttons.append(self._link("Open document", summary.document))
        if summary.report_path:
            link_buttons.append(self._link("Open report", str(summary.report_path)))
        headline = f"{'Done' if clear else head}: {budget.accepted:,} suggestions applied in {summaries.format_minutes(run_seconds)}"
        text = summaries.summary_text(
            name=name, location=place, headline=headline, by_type=dict(by), manual=summaries.format_minutes(manual),
            run=summaries.format_minutes(run_seconds), saved=summaries.format_minutes(saved),
            passes=summaries.passes_lines(budget.policy.passes, outcome), pages=budget.pages, chars=chars,
            backup=backup, changed=changed, unread=unread,
        )
        copy = QPushButton("Copy summary")

        def copy_summary() -> None:
            QApplication.clipboard().setText(text)
            copy.setText("Copied")
            QTimer.singleShot(2000, lambda: copy.setText("Copy summary"))

        copy.clicked.connect(copy_summary)
        link_buttons.append(copy)
        for index, button in enumerate(link_buttons):
            links.addWidget(button, index // 2, index % 2)
        layout.addLayout(links)
        layout.addStretch(1)
        again_row = QHBoxLayout()
        again_row.addStretch(1)
        if outcome.result not in (CLEAR, LIMIT, REPEATING) and budget.page > 1:
            resume = QPushButton(f"Resume from page {budget.page}")
            resume.clicked.connect(lambda: self._resume_from(budget.page, budget.policy.preset, budget.args.end_page))
            again_row.addWidget(resume)
        again = QPushButton("Run again")
        again.setObjectName("primary")
        again.clicked.connect(self._back_to_ready)
        again_row.addWidget(again)
        layout.addLayout(again_row)
        layout.addLayout(self._footer_row())
        self._swap(self.finished_page, page)
        self.finished_page = page
        self.tray.showMessage("Grammar Sweeper", head)
        history.add({
            "date": f"{summary.started.day} {summary.started:%b %Y, %H:%M}",
            "path": summary.document or "",
            "document": Path(summary.document).name if summary.document else "",
            "applied": budget.accepted, "saved": saved, "result": head,
            "report": str(summary.report_path) if summary.report_path else "",
            "backup": summary.backup or "",
            "spark": summaries.spark_series(changed, budget.pages),
        })
        if summary.report_path and self.settings["open_report"]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(summary.report_path)))

    # Advanced ------------------------------------------------------------

    def _build_advanced(self) -> QWidget:
        """Logs, screenshots and housekeeping, kept off the summary."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        frame, inner = card()
        inner.addWidget(label("Logs and screenshots", "section"))
        inner.addWidget(label("What a run leaves behind, for finding out what went wrong.", "muted"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        buttons = [
            self._link("Open logs folder", str(log_dir())),
            self._link("Open audit log", str(log_dir() / "audit.log")),
            self._link("Open screenshots", str(log_dir() / "shots")),
        ]
        diagnostics = QPushButton("Copy diagnostics")
        diagnostics.setToolTip("Gathers the logs, settings, newest screenshots and last report into one folder for support.")
        diagnostics.clicked.connect(self._diagnostics)
        buttons.append(diagnostics)
        for index, button in enumerate(buttons):
            grid.addWidget(button, index // 2, index % 2)
        inner.addLayout(grid)
        layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("Delete old files", "section"))
        inner.addWidget(label("Free space by deleting what you no longer need. Each name opens the file or folder.", "muted"))
        self.clean_boxes: dict[str, tuple[QCheckBox, QLabel]] = {}
        rows = QGridLayout()
        rows.setHorizontalSpacing(16)
        rows.setVerticalSpacing(6)
        for index, key in enumerate(cleanup.GROUP_KEYS):
            box = QCheckBox(cleanup.CATEGORIES[key][0])
            amount = label("", "muted", wrap=False)
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rows.addWidget(box, index, 0)
            rows.addWidget(amount, index, 1)
            rows.addWidget(self._open_link(CATEGORY_TARGETS[key]), index, 2)
            self.clean_boxes[key] = (box, amount)
        rows.setColumnStretch(0, 1)
        inner.addLayout(rows)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Remove"))
        self.clean_age = self._age_box()
        controls.addWidget(self.clean_age)
        controls.addStretch(1)
        self.clean_button = QPushButton("Delete selected")
        self.clean_button.setObjectName("danger")
        self.clean_button.clicked.connect(self._clean_selected)
        controls.addWidget(self.clean_button)
        inner.addLayout(controls)
        self.clean_result = label("", "muted")
        inner.addWidget(self.clean_result)
        layout.addWidget(frame)

        frame, inner = card()
        inner.addWidget(label("Change records and rule files", "section"))
        inner.addWidget(
            label(
                "The record of every edit and the rule files mined from it. They are kept apart because they are what "
                "the rules are built from, so they are never removed with the rest.",
                "muted",
            )
        )
        amount_row = QHBoxLayout()
        self.changes_amount = label("", "value", wrap=False)
        amount_row.addWidget(self.changes_amount, 1)
        amount_row.addWidget(self._open_link(CATEGORY_TARGETS["changes"]))
        inner.addLayout(amount_row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Remove"))
        self.changes_age = self._age_box()
        controls.addWidget(self.changes_age)
        controls.addStretch(1)
        self.changes_button = QPushButton("Delete change records and rule files")
        self.changes_button.setObjectName("danger")
        self.changes_button.clicked.connect(self._clean_changes)
        controls.addWidget(self.changes_button)
        inner.addLayout(controls)
        self.changes_result = label("", "muted")
        inner.addWidget(self.changes_result)
        layout.addWidget(frame)

        layout.addWidget(label("Backups of your documents, your settings and the run history are never removed here.", "muted"))
        layout.addStretch(1)
        built = "run from source" if version.BUILT == "source run" else f"built {version.BUILT}"
        layout.addWidget(label(f"Version {version.VERSION}, build {version.COMMIT}, {built}", "muted"))
        return page

    def _open_link(self, target: Path) -> QLabel:
        """A small 'Open' link to a file or folder, for the rows on the Advanced tab."""
        href = html.escape(QUrl.fromLocalFile(str(target)).toString())
        link = label(f'<a href="{href}" style="color: {style.ACCENT_NOW}; text-decoration: none;">Open</a>', "value", wrap=False)
        link.setTextFormat(Qt.RichText)
        link.setOpenExternalLinks(True)
        return link

    def _age_box(self) -> QComboBox:
        box = QComboBox()
        for text, days in cleanup.AGES.items():
            box.addItem(text, days)
        return box

    def _refresh_advanced(self) -> None:
        found = cleanup.scan(settings_dir())
        for key, (box, amount) in self.clean_boxes.items():
            amount.setText(cleanup.summary_line(found[key]))
            box.setEnabled(found[key].files > 0)
            if not found[key].files:
                box.setChecked(False)
        self.changes_amount.setText(cleanup.summary_line(found["changes"]))
        self.changes_button.setEnabled(found["changes"].files > 0)

    def _diagnostics(self) -> None:
        latest = [entry.get("report") for entry in history.load() if entry.get("report")]
        report = Path(latest[-1]) if latest else None
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(history.diagnostics_bundle(report))))

    def _clean_selected(self) -> None:
        keys = [key for key, (box, _amount) in self.clean_boxes.items() if box.isChecked()]
        if not keys:
            self.clean_result.setText("Tick what to delete first.")
            return
        self._clean(keys, self.clean_age.currentData(), self.clean_result, "")

    def _clean_changes(self) -> None:
        self._clean(
            ["changes"], self.changes_age.currentData(), self.changes_result,
            "\n\nThese hold your edit history and the rules mined from it.",
        )

    def _clean(self, keys: list[str], days, result_label: QLabel, warning: str) -> None:
        """Count what would go, ask, then remove it and say what was freed."""
        preview = cleanup.clean(settings_dir(), keys, days, dry_run=True)
        if not preview.files:
            result_label.setText("Nothing matches, so nothing was removed.")
            return
        names = ", ".join(cleanup.CATEGORIES[key][0].lower() for key in keys)
        sure = QMessageBox.question(
            self,
            "Delete files",
            f"Remove {preview.files:,} item{'s' if preview.files != 1 else ''} ({cleanup.human_size(preview.bytes)}) from {names}?\n\n"
            f"Logs are emptied, the rest are deleted. This cannot be undone.{warning}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if sure != QMessageBox.Yes:
            return
        result = cleanup.clean(settings_dir(), keys, days)
        text = f"Removed {result.files:,} item{'s' if result.files != 1 else ''}, freed {cleanup.human_size(result.bytes)}."
        if result.errors:
            text += f" {len(result.errors)} could not be removed: {result.errors[0]}"
        result_label.setText(text)
        engine.AUDIT.write("CLEANUP", keys=",".join(keys), older_than_days=days, removed=result.files, errors=len(result.errors))
        self._refresh_advanced()
        self._refresh_history()

    def _brand_row(self) -> QHBoxLayout:
        """The logo and the name, at the top of the summary."""
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(logo_label(SUMMARY_LOGO))
        row.addWidget(label("Grammar Sweeper", "title", wrap=False))
        row.addStretch(1)
        return row

    def _footer_row(self, coffee: bool = True) -> QHBoxLayout:
        """The company, the version, the GitHub and Apertura links, and the coffee button when asked."""
        def link(text: str, url: str) -> str:
            return f'<a href="{url}" style="color: {style.ACCENT_NOW}; text-decoration: none;">{text}</a>'

        row = QHBoxLayout()
        parts = [COMPANY, f"v{version.VERSION}", link("GitHub", REPO_URL), link("The Apertura", APERTURA_URL)]
        note = label("  \u00b7  ".join(parts), "footer", wrap=False)
        note.setTextFormat(Qt.RichText)
        note.setOpenExternalLinks(True)
        row.addWidget(note)
        row.addStretch(1)
        if coffee and COFFEE_URL and not self.settings["coffee_dismissed"]:
            button = QPushButton("\u2615  Buy me a coffee")
            button.setObjectName("coffee")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(COFFEE_URL)))
            row.addWidget(button)
        return row

    def _back_to_ready(self) -> None:
        self._show_ready()

    def _resume_from(self, page: int, preset: str, end_page: int) -> None:
        """Start again at the page where the last run stopped."""
        self._show_ready()
        for button in self.presets.buttons():
            button.setChecked(button.property("preset") == preset)
        self.range.setChecked(True)
        self.first.setValue(page)
        self.last.setValue(end_page if end_page > 0 else 9999)
        if self.doc_box.currentData():
            self._start()
        else:
            self.doc_status.setText("Pages are set to resume. Pick the document and press Start.")


def wrappable(text: str) -> str:
    """Zero width spaces after path and address separators, so a long path wraps inside the card."""
    return text.replace("/", "/\u200b").replace("\\", "\\\u200b")


def link_text(text: str, target: str, online: bool) -> str:
    """The text as a clickable link to the file or folder, in the same font as everything else."""
    if not text:
        return ""
    shown = html.escape(wrappable(text))
    if not target:
        return shown
    href = target if online else QUrl.fromLocalFile(target).toString()
    return f'<a href="{html.escape(href)}" style="color: {style.ACCENT_NOW}; text-decoration: none;">{shown}</a>'


def pass_mode(preset: str, limit) -> str:
    name = rules_name(preset)
    return f"{name}, up to {limit} passes" if limit and limit > 1 else f"{name}, one pass"


def passes_text(passes: list, outcome) -> str:
    """What the passes did, one line each, for the This run card."""
    return "<br>".join(html.escape(line) for line in summaries.passes_lines(passes, outcome))


def rules_name(preset: str) -> str:
    return PRESET_TEXT.get(preset, (preset.title(), ""))[0]


def run() -> int:
    import sys

    app = QApplication(sys.argv)
    settings = Settings()
    choice = settings["theme"]
    dark = choice == "dark" or (
        choice == "system" and app.styleHints().colorScheme().name == "Dark"
    )
    app.setStyleSheet(style.sheet(style.DARK if dark else style.LIGHT))
    window = MainWindow(settings, dark)
    window.show()
    return app.exec()
