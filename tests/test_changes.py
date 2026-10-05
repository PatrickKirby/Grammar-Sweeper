"""Change capture, report, resume signal, pass label and history. No Word needed."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sweeper import control, history, rules
from sweeper.changes import ChangeLog, build_report, locate_change
from sweeper.gui.hud import Hud


def test_locate_change_finds_the_single_edit():
    before = "The team have agreed the plan. Next item."
    after = "The team has agreed the plan. Next item."
    found = locate_change(before, after, context=5)
    assert found["original"] == "have" and found["revised"] == "has"
    assert found["index"] == before.index("have")


def test_context_starts_and_ends_on_whole_words():
    before = "alpha bravo charlie delta echo foxtrot golf hotel india"
    after = before.replace("echo", "ECHO")
    found = locate_change(before, after, context=9)
    assert found["context_before"] and found["context_after"]
    for piece, text in ((found["context_before"], before), (found["context_after"], after)):
        assert piece == "" or piece.strip(" ") in text
        assert all(word in text.split() for word in piece.split())


def test_context_is_shortened_when_a_word_would_be_cut():
    text = "x" * 30 + " y " + "z" * 30
    found = locate_change(text, text.replace(" y ", " Y "), context=10)
    assert found["context_before"] == "" and found["context_after"] == ""


def test_locate_change_handles_an_insertion():
    found = locate_change("a b", "a, b", context=3)
    assert found["original"] == "" and found["revised"] == ","

def test_change_log_keeps_records_and_writes_lines(tmp_path):
    log = ChangeLog(tmp_path / "c.jsonl")
    log.add(n=1, category="Clarity", original="a", revised="b")
    log.close()
    assert len(log.records) == 1
    assert '"category": "Clarity"' in (tmp_path / "c.jsonl").read_text(encoding="utf-8")


def test_report_carries_type_and_both_texts(tmp_path):
    records = [{"category": "Delivery", "page": 3, "original": "very good", "revised": "good", "time": "10:00:00"}]
    out = build_report(tmp_path / "r.html", {"Applied": 1}, records)
    text = out.read_text(encoding="utf-8")
    assert "Delivery" in text and "very good" in text and "#5854E2" in text


def test_resume_is_signalled_to_the_engine():
    ctl = control.RunControl(rules.RunClock(), sleep=lambda _s: ctl._pause.clear())
    assert ctl.wait_while_blocked() is False  # nothing to wait for
    ctl.request_pause()
    assert ctl.wait_while_blocked() is True  # waited, so the engine must recover


def test_pass_label_counts_from_one_and_states_the_limit():
    hud = Hud(lambda: 0, None, True)
    hud.set_progress(0, 0, 0, 0, None, None, {}, 4)
    assert hud.passlabel.text() == "PASS 1 OF UP TO 4"
    hud.set_progress(0, 0, 0, 1, None, None, {}, 1)
    assert hud.passlabel.text() == "PASS 1 OF 1"
    hud.set_progress(0, 0, 0, 3, None, None, {}, None)
    assert hud.passlabel.text() == "PASS 3"


def test_hud_shows_the_four_grammarly_types():
    hud = Hud(lambda: 0, None, True)
    hud.set_progress(10, 5, 100, 1, 10.0, None, {"Correctness": 4, "Clarity": 3, "Engagement": 2, "Delivery": 1}, 4)
    assert [hud.tiles[k].text() for k in ("Correctness", "Clarity", "Engagement", "Delivery")] == ["4", "3", "2", "1"]


def test_preset_limits_match_the_presets():
    assert rules.RunPolicy(preset="quick").pass_limit == 1
    assert rules.RunPolicy(preset="standard").pass_limit == 4
    assert rules.RunPolicy(preset="thorough").pass_limit is None


def test_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_path", lambda: tmp_path / "h.json")
    history.add({"document": "a.docx", "applied": 3})
    assert history.load()[-1]["document"] == "a.docx"


def test_report_is_light_highlights_only_and_drops_the_dropped_sections(tmp_path):
    records = [{"category": "Correctness", "original": "polices", "revised": "policies", "page": 1, "flags": ["name"]}]
    html = build_report(tmp_path / "r.html", {"Applied": 1}, records).read_text(encoding="utf-8")
    assert "line-through" not in html
    assert "Per 1,000" not in html and "per_1000_words" not in html
    assert "Paragraph comparison" not in html
    assert "--bg:#F3F4F8" in html and "#26272D" not in html
    assert "How to read this report" in html and "Needs review" in html


def test_the_run_stamp_reads_as_a_date_and_time():
    from sweeper.changes import run_started

    assert run_started("20261005-172717") == "5 October 2026, 17:27"
    assert run_started("not a stamp") == "not a stamp"


def test_both_rule_tables_share_the_same_column_widths(tmp_path):
    import re

    from sweeper.changes import RULE_COLUMNS

    mech = {"category": "Correctness", "original": "teh", "revised": "the", "page": 1, "class": "mechanical", "kind": "replace", "rule": "spelling"}
    style = {"category": "Clarity", "original": "in order to", "revised": "to", "page": 1, "class": "stylistic", "kind": "replace", "rule": "wordy"}
    html = build_report(tmp_path / "r.html", {"Run": "20261005-172717"}, [mech, style]).read_text(encoding="utf-8")
    groups = re.findall(r"<colgroup>(.*?)</colgroup>", html)
    assert len(groups) == 2 and groups[0] == groups[1]
    assert sum(RULE_COLUMNS) == 100
    assert "Run started" in html and "5 October 2026, 17:27<" in html
    assert "buymeacoffee.com" in html and 'class="coffee"' in html


def test_report_has_a_logo_and_a_footer_with_the_company_repo_and_coffee(tmp_path):
    html = build_report(tmp_path / "r.html", {"Applied": 1}, [{"category": "Correctness", "original": "a", "revised": "b", "page": 1, "time": "17:27:23"}]).read_text(encoding="utf-8")
    assert "data:image/png;base64," in html
    footer = html[html.index("<footer>"):html.index("</footer>")]
    assert "Preceperi Limited" in footer and "github.com" in footer and "buymeacoffee.com" in footer
    assert html.index("<footer>") > html.index("Every applied suggestion")  # the coffee button moved down
    assert "17:27:23" not in html and "<td>17:27</td>" in html  # no seconds in the time column
