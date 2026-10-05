"""The setup page: status badge, recent runs, footer, and the background texture."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from sweeper import history, texture  # noqa: E402
from sweeper.changes import build_report  # noqa: E402
from sweeper.gui import style  # noqa: E402
from sweeper.gui.main_window import MainWindow  # noqa: E402
from sweeper.settings import APERTURA_URL, REPO_URL, Settings  # noqa: E402


def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(style.sheet(style.LIGHT))
    monkeypatch.setattr(history, "_path", lambda: tmp_path / "h.json")
    settings = Settings(tmp_path / "s.json")
    settings["consent_accepted"] = True
    win = MainWindow(settings, False)
    win._snapped = True  # never move the real windows from a test
    return win


def info(paths=("C:/docs/a.docx",), elevated=False, warnings=None):
    return {"paths": list(paths), "elevated": elevated, "panel": None, "warnings": warnings or {}}


def test_ready_is_green_and_bold(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    win._pane_note = ""
    win._on_preflight(info())
    assert win.ready_badge.text().endswith("Ready") and win.ready_badge.objectName() == "ok"


def test_notes_turn_the_badge_violet_and_no_document_turns_it_red(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    win._on_preflight(info(warnings={"C:/docs/a.docx": ["is read-only."]}))
    assert "with notes" in win.ready_badge.text() and win.ready_badge.objectName() == "warn"
    win._on_preflight(info(paths=()))
    assert "Not ready" in win.ready_badge.text() and win.ready_badge.objectName() == "bad"
    win._on_preflight(info(elevated=True))
    assert win.ready_badge.objectName() == "bad"


def test_the_title_carries_no_version_and_the_footer_does(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    assert win.windowTitle() == "Grammar Sweeper"
    footers = [item.text() for item in win.ready_page.findChildren(QLabel) if item.objectName() == "footer"]
    assert footers and "Preceperi Limited" in footers[0] and "v0." in footers[0]
    assert REPO_URL in footers[0] and APERTURA_URL in footers[0]


def test_a_recent_run_links_the_document_and_the_report_and_puts_the_figures_on_line_two(tmp_path, monkeypatch):
    report = tmp_path / "report.html"
    report.write_text("x")
    win = window(tmp_path, monkeypatch)
    row = win._history_row(
        {"document": "Plan.docx", "path": r"C:\docs\Plan.docx", "date": "5 Oct 2026, 17:27", "applied": 5, "saved": 400, "report": str(report)}
    )
    texts = [item.text() for item in row.findChildren(QLabel)]
    assert any("Plan.docx" in text and "file:///C:/docs/Plan.docx" in text for text in texts)
    assert any(">Report</a>" in text for text in texts)
    assert "5 Oct 2026, 17:27  \u00b7  5 applied  \u00b7  saved 7 min" in texts


def test_an_old_run_without_a_path_is_plain_text(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    row = win._history_row({"document": "Old.docx", "date": "01 Oct 09:00", "applied": 1, "saved": 5, "report": ""})
    assert not any("<a href" in item.text() for item in row.findChildren(QLabel))


def test_the_texture_is_the_same_every_time_and_barely_differs_from_the_page_colour():
    a, b = texture.tile("#F3F4F8", "#4F56D6"), texture.tile("#F3F4F8", "#4F56D6")
    assert a.tobytes() == b.tobytes()
    assert a.size == (texture.TILE, texture.TILE) and texture.TILE % texture.GRID == 0
    base = (0xF3, 0xF4, 0xF8)
    most = max(abs(a.getpixel((x, y))[i] - base[i]) for x in range(texture.TILE) for y in range(texture.TILE) for i in range(3))
    assert most <= 20  # grain of 3, and a tenth of the accent at the dots: very light


def test_the_stylesheet_paints_the_texture_on_the_window_only():
    sheet = style.sheet(style.LIGHT)
    assert "QWidget#window" in sheet and "background-image: url(" in sheet
    assert "QWidget {" in sheet and "background: transparent" in sheet.split("QWidget#window")[0]


def test_the_report_has_the_texture_the_version_and_both_links(tmp_path):
    html = build_report(tmp_path / "r.html", {"Applied": 1}, [{"category": "Correctness", "original": "a", "revised": "b", "page": 1}]).read_text(encoding="utf-8")
    assert "body{background-image:url(data:image/png;base64," in html
    footer = html[html.index("<footer>"):html.index("</footer>")]
    assert "v0." in footer and APERTURA_URL in footer and REPO_URL in footer


def test_start_and_the_grammarly_status_show_on_the_setup_tab_only(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    win.show()
    win.tabs.setCurrentIndex(1)
    assert not win.start_button.isVisible()
    win.tabs.setCurrentIndex(2)
    assert not win.start_button.isVisible()
    win.tabs.setCurrentIndex(0)
    assert win.start_button.isVisible()


def test_the_setup_page_shows_the_page_count_of_the_chosen_document(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    win._on_preflight({**info(), "pages": {"C:/docs/a.docx": 42}})
    assert win.doc_pages.text() == "42 pages"
    win._on_preflight({**info(), "pages": {"C:/docs/a.docx": 1}})
    assert win.doc_pages.text() == "1 page"
    win._on_preflight(info())
    assert win.doc_pages.text() == ""


def test_a_recent_run_links_its_backup_folder_and_draws_a_sparkline(tmp_path, monkeypatch):
    from sweeper.gui.strip import Sparkline

    win = window(tmp_path, monkeypatch)
    backup = tmp_path / "a.backup-1.docx"
    backup.write_text("x")
    row = win._history_row({"document": "a.docx", "backup": str(backup), "spark": [0, 3, 1], "applied": 4, "saved": 0})
    links = [item.text() for item in row.findChildren(QLabel) if "href" in item.text()]
    assert links and "Backup" in links[0]
    assert row.findChildren(Sparkline)
    assert not win._history_row({"document": "a.docx", "applied": 0, "saved": 0}).findChildren(Sparkline)


def test_the_tagline(tmp_path, monkeypatch):
    win = window(tmp_path, monkeypatch)
    texts = [item.text() for item in win.ready_page.findChildren(QLabel)]
    assert "Accept Grammarly suggestions hands free." in texts
    assert not any("Accept every Grammarly" in text for text in texts)
