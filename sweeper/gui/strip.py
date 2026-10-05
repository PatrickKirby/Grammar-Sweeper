"""The page strip on the summary: one block per page, coloured by the kind of change that page took,
with a hover that says what happened there."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from .. import summary
from ..changes import TYPE_COLOURS
from . import style


class Sparkline(QWidget):
    """A small filled line of changes per page, for one past run. Drawn nothing when there is no series."""

    def __init__(self, series: list[int], colour: str) -> None:
        super().__init__()
        self.series = series
        self.colour = QColor(colour)
        self.setFixedHeight(22)
        self.setMinimumWidth(80)
        if series:
            self.setToolTip(f"Changes per page across the document, {max(series):,} at the most in one stretch")

    def paintEvent(self, _event) -> None:
        if not self.series:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width() - 2, self.height() - 3
        top = max(self.series) or 1
        step = width / max(1, len(self.series) - 1)
        points = [QPointF(1 + i * step, 1 + height - height * value / top) for i, value in enumerate(self.series)]
        if len(points) == 1:
            points.append(QPointF(1 + width, points[0].y()))
        fill = QPolygonF([QPointF(points[0].x(), 1 + height), *points, QPointF(points[-1].x(), 1 + height)])
        shade = QColor(self.colour)
        shade.setAlpha(60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shade)
        painter.drawPolygon(fill)
        painter.setPen(QPen(self.colour, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF(points))


class PageStrip(QWidget):
    HEIGHT = 30

    def __init__(self, pages: int, changed: dict[int, list[dict]], unread: set[int]) -> None:
        super().__init__()
        self.pages = max(1, pages)
        self.changed = changed
        self.unread = unread
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setMinimumWidth(120)
        self._hover = 0

    def _cell(self) -> float:
        return self.width() / self.pages

    def _page_at(self, x: float) -> int:
        return min(self.pages, max(1, int(x // self._cell()) + 1))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cell = self._cell()
        gap = 1.5 if cell >= 7 else 0.5 if cell >= 3.5 else 0
        quiet = QColor(style.LINE_NOW)
        for page in range(1, self.pages + 1):
            rect = QRectF((page - 1) * cell + gap / 2, 0, max(1.0, cell - gap), self.HEIGHT)
            changes = self.changed.get(page)
            kind = summary.dominant(changes or [])
            if kind:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(TYPE_COLOURS.get(kind, TYPE_COLOURS["Unclassified"])))
            elif page in self.unread:
                painter.setPen(QPen(QColor(style.WARN_NOW), 1.2))
                painter.setBrush(Qt.NoBrush)
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(quiet)
            painter.drawRoundedRect(rect, min(3.0, cell / 3), min(3.0, cell / 3))
            if page == self._hover:
                painter.setPen(QPen(QColor(style.ACCENT_NOW), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 3, 3)

    def mouseMoveEvent(self, event) -> None:
        page = self._page_at(event.position().x())
        if page != self._hover:
            self._hover = page
            self.update()
        QToolTip.showText(
            event.globalPosition().toPoint(),
            summary.page_tip(page, self.changed.get(page, []), page in self.unread),
            self,
        )

    def leaveEvent(self, _event) -> None:
        self._hover = 0
        self.update()
        QToolTip.hideText()
