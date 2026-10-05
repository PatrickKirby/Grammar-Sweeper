"""Palette and stylesheet. Neutral dark (not black), indigo accent, flat surfaces.
One font family throughout. Headings are bold and context text is regular. Yellow is
reserved for the coffee button, so warnings use violet and notices use an indigo tint.
Mica is optional polish and is not attempted here; the flat fallback is the design."""

import tempfile
from pathlib import Path

from .. import texture

LIGHT = {
    "bg": "#F3F4F8", "card": "#FFFFFF", "text": "#1B1C22", "muted": "#5E6070",
    "line": "#DCDEE8", "accent": "#4F56D6", "accent_text": "#FFFFFF",
    "ok": "#1E8E5A", "warn": "#7A3FD1", "bad": "#C0392B",
    "ok_bg": "#DDF3E7", "warn_bg": "#ECE3FA", "bad_bg": "#F8DEDA",
    "notice_bg": "#ECEEFB", "handle": "#B9BCD0",
}
DARK = {
    "bg": "#26272D", "card": "#303139", "text": "#ECECF1", "muted": "#A3A5B5",
    "line": "#41424D", "accent": "#8B93FF", "accent_text": "#14152A",
    "ok": "#5FD39B", "warn": "#B79CFF", "bad": "#FF8A7A",
    "ok_bg": "#1F3A2B", "warn_bg": "#30284A", "bad_bg": "#43262A",
    "notice_bg": "#2D2F45", "handle": "#5A5C6E",
}

FONT = "'Segoe UI Variable Text', 'Segoe UI'"
ACCENT_NOW = LIGHT["accent"]  # colours of the sheet last built, for rich text and painted widgets
LINE_NOW = LIGHT["line"]
WARN_NOW = LIGHT["warn"]


def chevron(colour: str) -> str:
    """A small down chevron for drop-downs, drawn once per colour into the temp folder as a PNG,
    because a style sheet can only point at a file and the SVG plugin is not always present.
    Forward slashes, as Qt reads them."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

    path = Path(tempfile.gettempdir()) / f"grammar-sweeper-chevron-{colour.lstrip('#')}.png"
    if not path.exists():
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(colour), 3.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(5, 9), QPointF(12, 16), QPointF(19, 9)]))
        painter.end()
        image.save(str(path))
    return path.as_posix()


def texture_file(c: dict) -> str:
    """The background tile for a palette, written once to the temp folder because a style sheet can
    only point at a file. Forward slashes, as Qt reads them."""
    path = Path(tempfile.gettempdir()) / f"grammar-sweeper-texture-{c['bg'].lstrip('#')}-{c['accent'].lstrip('#')}-v1.png"
    if not path.exists():
        path.write_bytes(texture.tile_png(c["bg"], c["accent"]))
    return path.as_posix()


def sheet(c: dict) -> str:
    global ACCENT_NOW, LINE_NOW, WARN_NOW
    ACCENT_NOW, LINE_NOW, WARN_NOW = c["accent"], c["line"], c["warn"]
    arrow = chevron(c["muted"])
    grain = texture_file(c)
    return f"""
    QWidget {{ background: transparent; color: {c['text']}; font-family: {FONT}; font-size: 10pt; }}
    QWidget#window, QDialog {{ background-color: {c['bg']}; background-image: url({grain}); background-repeat: repeat-xy; }}
    QFrame#runrow {{ background: transparent; border: none; border-bottom: 1px solid {c['line']}; }}
    QLabel#title {{ font-size: 20pt; font-weight: 700; }}
    QLabel#headline {{ font-size: 16pt; font-weight: 700; }}
    QLabel#muted {{ color: {c['muted']}; font-weight: 400; }}
    QLabel#ok {{ color: {c['ok']}; font-weight: 700; }}
    QLabel#warn {{ color: {c['warn']}; font-weight: 700; }}
    QLabel#bad {{ color: {c['bad']}; font-weight: 700; }}
    QFrame#card {{ background: {c['card']}; border: 1px solid {c['line']}; border-radius: 10px; }}
    QFrame#card QLabel, QFrame#card QRadioButton, QFrame#card QCheckBox {{ background: transparent; }}
    QPushButton {{ background: {c['card']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 6px 14px; font-size: 9pt; }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton#primary {{ background: {c['accent']}; color: {c['accent_text']}; border: none; font-weight: 700; padding: 8px 22px; font-size: 9.5pt; }}
    QPushButton#primary:disabled {{ background: {c['line']}; color: {c['muted']}; }}
    QPushButton#danger {{ border-color: {c['bad']}; color: {c['bad']}; }}
    QPushButton#help {{ border-radius: 14px; padding: 0; font-weight: 700; font-size: 10pt; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }}
    QComboBox, QSpinBox {{ background: {c['card']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 5px 8px; }}
    QComboBox:hover, QSpinBox:hover {{ border-color: {c['accent']}; }}
    QComboBox {{ padding-right: 26px; }}
    QComboBox::drop-down {{ border: none; background: transparent; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
    QComboBox::down-arrow {{ image: url({arrow}); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['line']}; selection-background-color: {c['notice_bg']}; selection-color: {c['text']}; outline: none; }}
    QSpinBox {{ min-width: 52px; }}
    QRadioButton, QCheckBox {{ spacing: 8px; }}
    QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; border: 2px solid {c['muted']}; background: transparent; }}
    QRadioButton::indicator {{ border-radius: 10px; }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator:checked {{ border-color: {c['accent']}; background: qradialgradient(cx:.5, cy:.5, radius:.5, fx:.5, fy:.5, stop:0 {c['accent']}, stop:.55 {c['accent']}, stop:.6 transparent); }}
    QCheckBox::indicator:checked {{ border-color: {c['accent']}; background: {c['accent']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; border: none; }}
    QScrollBar::handle:vertical {{ background: {c['handle']}; border-radius: 4px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; border: none; }}
    QScrollBar::handle:horizontal {{ background: {c['handle']}; border-radius: 4px; min-width: 36px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; font-weight: 700; padding: 8px 18px; margin-right: 4px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; }}
    QRadioButton#preset {{ font-weight: 700; }}
    QLabel#presetdesc {{ color: {c['muted']}; font-size: 8pt; font-weight: 400; }}
    QLabel#footer {{ color: {c['muted']}; font-size: 8.5pt; font-weight: 400; }}
    QLabel#stat, QLabel#statok {{ font-size: 17pt; font-weight: 700; }}
    QLabel#statok {{ color: {c['ok']}; }}
    QLabel#tilecaption {{ color: {c['muted']}; font-size: 8.5pt; font-weight: 400; }}
    QLabel#section {{ color: {c['text']}; font-size: 11pt; font-weight: 700; }}
    QLabel#key {{ color: {c['text']}; font-weight: 600; }}
    QLabel#value {{ font-weight: 400; }}
    QLabel#bannerhead {{ font-size: 14pt; font-weight: 700; }}
    QLabel#bannersub {{ color: {c['muted']}; font-weight: 400; }}
    QFrame#bannerok {{ background: {c['ok_bg']}; border-radius: 10px; }}
    QFrame#bannerwarn {{ background: {c['warn_bg']}; border-radius: 10px; }}
    QFrame#bannerbad {{ background: {c['bad_bg']}; border-radius: 10px; }}
    QFrame#bannerok QLabel, QFrame#bannerwarn QLabel, QFrame#bannerbad QLabel {{ background: transparent; }}
    QFrame#bannerok QLabel#discok {{ background: {c['ok']}; color: {c['accent_text']}; border-radius: 17px; font-weight: 700; font-size: 13pt; }}
    QFrame#bannerwarn QLabel#discwarn {{ background: {c['warn']}; color: {c['accent_text']}; border-radius: 17px; font-weight: 700; font-size: 13pt; }}
    QFrame#bannerbad QLabel#discbad {{ background: {c['bad']}; color: {c['accent_text']}; border-radius: 17px; font-weight: 700; font-size: 13pt; }}
    QFrame#notice {{ background: {c['notice_bg']}; border: none; border-left: 3px solid {c['accent']}; border-radius: 6px; }}
    QLabel#noticetext {{ background: transparent; }}
    QPushButton#coffee {{ background: #FFDD00; color: #000000; border: none; font-weight: 700; padding: 7px 18px; }}
    QPushButton#coffee:hover {{ background: #FFE63D; }}
    QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']}; padding: 6px; }}
    """
