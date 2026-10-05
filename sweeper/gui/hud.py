"""The running HUD: small, always on top, never takes focus.

Word must stay in front or Grammarly's panel stops rendering, so clicking a
button here must not activate this window. Qt's WindowDoesNotAcceptFocus maps to
WS_EX_NOACTIVATE on Windows."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..changes import ALL_TYPES, TYPE_COLOURS
from ..rules import format_duration


class Heat(QWidget):
    """One column per page stop across the whole run. Each column stacks the
    suggestions applied there, coloured by Grammarly type."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(44)
        self.cells: list[tuple[int, dict]] = []  # (page, {type: applied})
        self.current = 0
        self.color = QColor("#8B93FF")
        self.track = QColor("#41424D")

    def set_data(self, heat: dict, first: int, last: int, step: int, current: int) -> None:
        step = max(1, step)
        self.cells = [(page, heat.get(page, {})) for page in range(first, last + 1, step)] if last >= first else []
        self.current = current
        self.update()

    def paintEvent(self, _event) -> None:
        if not self.cells:
            return
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        peak = max(1, max(sum(counts.values()) for _page, counts in self.cells))
        width = self.width() / len(self.cells)
        usable = self.height() - 5
        for index, (page, counts) in enumerate(self.cells):
            x, w = index * width, max(1.0, width - 1)
            bottom = float(self.height())
            if not counts:
                painter.setBrush(QColor("#FFFFFF") if page == self.current else self.track)
                painter.drawRect(QRectF(x, bottom - 3, w, 3))
                continue
            for name in ALL_TYPES:
                n = counts.get(name, 0)
                if not n:
                    continue
                height = max(2.0, usable * n / peak)
                painter.setBrush(QColor(TYPE_COLOURS[name]))
                painter.drawRect(QRectF(x, bottom - height, w, height))
                bottom -= height
            if page == self.current:
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawRect(QRectF(x, 0, w, 2))


class Ring(QWidget):
    """Progress ring for the current pass, or a spinner when unknown."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(88, 88)
        self.percent: float | None = None
        self.color = QColor("#8B93FF")
        self.track = QColor("#41424D")
        self.text = QColor("#ECECF1")
        self.muted = QColor("#A3A5B5")
        self._spin = 0

    def tick(self) -> None:
        self._spin = (self._spin + 18) % 360
        if self.percent is None:
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(7, 7, 74, 74)
        painter.setPen(QPen(self.track, 7, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)
        painter.setPen(QPen(self.color, 7, Qt.SolidLine, Qt.RoundCap))
        if self.percent is None:
            painter.drawArc(rect, -self._spin * 16, -90 * 16)
            painter.setPen(self.text)
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(self.rect(), Qt.AlignCenter, "working")
            return
        painter.drawArc(rect, 90 * 16, int(-3.6 * self.percent * 16))
        painter.setPen(self.text)
        painter.setFont(QFont("Segoe UI", 15, QFont.DemiBold))
        painter.drawText(self.rect().adjusted(0, -8, 0, -8), Qt.AlignCenter, f"{self.percent:.0f}%")
        painter.setPen(self.muted)
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(self.rect().adjusted(0, 22, 0, 22), Qt.AlignCenter, "of this pass")


class Hud(QWidget):
    pause_toggled = Signal(bool)
    front_requested = Signal()  # the run waits for the person; Resume means put Word back
    stop_requested = Signal()
    moved = Signal(int, int)

    def __init__(self, clock_source, position=None, dark: bool = True) -> None:
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._clock = clock_source  # callable returning running seconds
        self._drag: QPoint | None = None
        self.locked = False  # docked above Grammarly's panel, so it is not dragged
        self._paused = False
        self._held = False  # the engine is waiting for the person to return to Word
        self._dark = dark
        self._accent = QColor("#8B93FF" if dark else "#4F56D6")
        self.eta: float | None = None
        self.eta_run: tuple | None = None

        self.ring = Ring()
        self.passlabel = QLabel("PASS 1")
        self.running = QLabel("Running 0 s")
        self.applied = QLabel("0")
        self.applied.setObjectName("big")
        self.applied_caption = QLabel("suggestions applied")
        self.where = QLabel("Starting")
        self.eta_label = QLabel("")
        self.eta_label.setWordWrap(True)
        self.note_label = QLabel("")
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(False)
        self.passes_label = QLabel("")
        self.passes_label.setWordWrap(True)
        self.passes_label.setVisible(False)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        self.hint = QLabel("Esc = Stop")

        self.tiles: dict[str, QLabel] = {}
        tile_row = QHBoxLayout()
        tile_row.setSpacing(6)
        for key in ALL_TYPES:
            frame = QFrame()
            frame.setObjectName("tile")
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(0, 0, 0, 6)
            inner.setSpacing(0)
            strip = QFrame()
            strip.setFixedHeight(4)
            strip.setStyleSheet(f"background: {TYPE_COLOURS[key]}; border-radius: 2px; margin: 0 8px;")
            value = QLabel("0")
            value.setObjectName("tilevalue")
            value.setAlignment(Qt.AlignCenter)
            name = QLabel(key)
            name.setObjectName("tilecaption")
            name.setAlignment(Qt.AlignCenter)
            inner.addWidget(strip)
            inner.addSpacing(5)
            inner.addWidget(value)
            inner.addWidget(name)
            self.tiles[key] = value
            tile_row.addWidget(frame, 1)
        self.heat = Heat()

        for button in (self.pause_button, self.stop_button):
            button.setFocusPolicy(Qt.NoFocus)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.stop_button.clicked.connect(self.stop_requested.emit)

        head = QHBoxLayout()
        head.addWidget(self.passlabel)
        head.addStretch(1)
        head.addWidget(self.running)

        numbers = QVBoxLayout()
        numbers.setSpacing(0)
        numbers.addStretch(1)
        numbers.addWidget(self.applied)
        numbers.addWidget(self.applied_caption)
        numbers.addWidget(self.where)
        numbers.addStretch(1)
        middle = QHBoxLayout()
        middle.setSpacing(14)
        middle.addWidget(self.ring)
        middle.addLayout(numbers, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.hint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        outer.addLayout(head)
        outer.addLayout(middle)
        outer.addLayout(tile_row)
        outer.addWidget(self.note_label)
        outer.addWidget(self.heat)
        outer.addWidget(self.passes_label)
        outer.addWidget(self.eta_label)
        outer.addWidget(self.message)
        outer.addLayout(buttons)
        self.setFixedWidth(412)
        self._apply_colors("running")
        self._show_time()

        if position:
            self.move(position[0], position[1])
        else:
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.move(area.right() - self.width() - 16, area.top() + 16)  # until Grammarly's panel is found

    def _apply_colors(self, state: str) -> None:
        bg, fg, muted, line, tile = (
            ("#1E1F25", "#ECECF1", "#A3A5B5", "#41424D", "#2A2B33")
            if self._dark
            else ("#FFFFFF", "#1B1C22", "#5E6070", "#C9CBD8", "#F3F4F8")
        )
        amber = "#B79CFF" if self._dark else "#7A3FD1"  # violet; yellow is for the coffee button only
        accent = amber if state in ("needs_user", "reconnecting", "paused") else self._accent.name()
        self.ring.color = QColor(accent)
        self.ring.track = QColor(line)
        self.ring.text = QColor(fg)
        self.ring.muted = QColor(muted)
        self.ring.update()
        self.heat.color = QColor(accent)
        self.heat.track = QColor(line)
        self.heat.update()
        self.setStyleSheet(
            f"""
            QWidget {{ background: {bg}; color: {fg}; font-family: 'Segoe UI'; font-size: 9pt; }}
            QFrame#tile {{ background: {tile}; border: 1px solid {line}; border-radius: 8px; }}
            QFrame#tile QLabel {{ background: transparent; }}
            QLabel#big {{ font-size: 28pt; font-weight: 600; }}
            QLabel#tilevalue {{ font-size: 13pt; font-weight: 600; }}
            QLabel#tilecaption {{ color: {muted}; font-size: 8pt; }}
            QPushButton {{ border: 1px solid {line}; border-radius: 6px; padding: 5px 14px; }}
            QPushButton:hover {{ border-color: {accent}; }}
            """
        )
        self.message.setStyleSheet(f"color: {amber if state != 'running' else muted};")
        for quiet in (self.hint, self.where, self.running, self.applied_caption, self.passlabel):
            quiet.setStyleSheet(f"color: {muted};")
        self.passlabel.setStyleSheet(f"color: {accent}; font-weight: 600; letter-spacing: 1px;")
        self.eta_label.setStyleSheet(f"color: {muted};")
        self.note_label.setStyleSheet(f"color: {muted}; font-size: 8pt;")
        self.passes_label.setStyleSheet(f"color: {muted};")

    def _toggle_pause(self) -> None:
        if self._held:
            self.front_requested.emit()
            return
        self._paused = not self._paused
        self.pause_button.setText("Resume" if self._paused else "Pause")
        self.pause_toggled.emit(self._paused)

    def set_progress(
        self, applied: int, page: int, pages: int, sweep: int, percent, eta=None, by_type=None, limit=None,
        heat=None, first=1, last=0, step=5, extra=None,
    ) -> None:
        extra = extra or {}
        self.applied.setText(f"{applied:,}")
        shown = extra.get("caret", -1)
        shown = shown if shown and shown > 0 else page  # the page Word is showing, as its status bar does
        scope = extra.get("scope")
        reading = f", Grammarly on {scope[0]} to {scope[1]}" if scope else ""
        self.where.setText(f"Page {shown} of {pages}{reading}" if pages else "Starting")
        number = max(1, sweep)  # the first pass is pass 1, never pass 0
        if limit == 1:
            self.passlabel.setText("PASS 1 OF 1")
        else:
            self.passlabel.setText(f"PASS {number} OF UP TO {limit}" if limit else f"PASS {number}")
        self.ring.percent = percent  # position within this pass, not the whole run
        self.ring.update()
        by_type = by_type or {}
        for key in ALL_TYPES:
            self.tiles[key].setText(f"{by_type.get(key, 0):,}")
        self.heat.set_data(heat or {}, first, last, step, page)
        noeffect = extra.get("noeffect", 0)
        notes = []
        if extra.get("behind"):
            notes.append(f"Word changed in {extra['measured']:,} places; the counter is {extra['behind']:,} behind")
        if noeffect:
            notes.append(f"{noeffect:,} clicks changed nothing and are not counted")
        self.note_label.setText(" · ".join(notes))
        self.note_label.setVisible(bool(notes))
        done = extra.get("passes_done") or []
        current = max(0, applied - sum(done))
        if done:
            parts = [f"{i}: {n:,}" for i, n in enumerate(done, 1)] + [f"{len(done) + 1}: {current:,} so far"]
            self.passes_label.setText("Applied per pass  " + "   ".join(parts))
        self.passes_label.setVisible(bool(done))
        self.eta_run = extra.get("eta_run")
        self.eta = eta
        self._show_time()

    def _show_time(self) -> None:
        self.running.setText(f"Running {format_duration(self._clock())}")
        if self.eta is None:
            self.eta_label.setText("Working out how long this pass will take")
            return
        text = f"This pass: about {format_duration(round(self.eta, -1) or 10)} left"
        if self.eta_run:
            total, further = self.eta_run
            if further:
                text += (
                    f"\nWhole run: at least {format_duration(round(total, -1) or 10)} more, "
                    f"with {further} more pass{'es' if further != 1 else ''} needed to confirm nothing is left"
                )
            else:
                text += "\nThis is the last pass."
        self.eta_label.setText(text)

    def set_state(self, state: str, message: str) -> None:
        self._held = state == "needs_user"
        if self._held:
            self.pause_button.setText("Resume")
        elif not self._paused:
            self.pause_button.setText("Pause")
        self._apply_colors(state)
        text = message if state != "running" else ""
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def tick(self) -> None:
        self._show_time()
        self.ring.tick()

    # Dragging: a frameless window has no title bar, so the whole face moves it.
    def dock(self, rect) -> None:
        """Take the rectangle (left, top, right, bottom), at the panel's own width."""
        left, top, right, _bottom = rect
        if self.width() != right - left:
            self.setFixedWidth(right - left)
        if self.pos() != QPoint(left, top):
            self.move(left, top)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.locked:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag is not None:
            self._drag = None
            self.moved.emit(self.x(), self.y())
