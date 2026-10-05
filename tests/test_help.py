"""The help dialogs and their buttons."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from sweeper.gui import help as helpmod  # noqa: E402


def app():
    return QApplication.instance() or QApplication([])


def test_each_page_has_a_title_and_a_body():
    for title, body in (helpmod.SETUP, helpmod.SUMMARY):
        assert title and "<h3>" in body


def test_the_summary_help_explains_checks_and_the_strip():
    body = helpmod.SUMMARY[1]
    assert "checks" in body and "Where it changed" in body and "Copy summary" in body


def test_the_setup_help_says_tone_is_never_accepted():
    assert "never accepts a" in helpmod.SETUP[1]


def test_the_button_is_a_round_question_mark():
    app()
    button = helpmod.help_button(QWidget(), helpmod.SETUP)
    assert isinstance(button, QPushButton)
    assert button.text() == "?" and button.objectName() == "help"
