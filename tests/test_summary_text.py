"""The summary page's text: what each pass did, and links to the file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sweeper import rules  # noqa: E402
from sweeper import summary as summaries  # noqa: E402
from sweeper.gui import main_window as mw  # noqa: E402


def outcome(result):
    return rules.Outcome(result=result, reason="r", passes=3, last_applied=0, preset="standard")


def test_one_pass_of_changes_and_two_checks_reads_as_one_pass():
    passes = [rules.PassRecord(1, 5, True), rules.PassRecord(2, 0, True), rules.PassRecord(3, 0, True)]
    text = mw.passes_text(passes, outcome(rules.CLEAR))
    assert text.split("<br>") == [
        "Changes made in 1 pass: pass 1 (5)",
        "2 further passes checked and found nothing",
        "Stopped because two passes in a row found nothing",
    ]


def test_changes_in_two_passes_are_both_listed():
    passes = [rules.PassRecord(1, 5, True), rules.PassRecord(2, 2, True), rules.PassRecord(3, 0, True)]
    lines = summaries.passes_lines(passes, outcome(rules.LIMIT))
    assert lines[0] == "Changes made in 2 passes: pass 1 (5), pass 2 (2)"
    assert lines[1] == "1 further pass checked and found nothing"


def test_a_run_where_nothing_changed_says_so():
    passes = [rules.PassRecord(1, 0, True), rules.PassRecord(2, 0, True)]
    assert summaries.passes_lines(passes, outcome(rules.CLEAR))[0] == "2 passes checked and found nothing"


def test_a_run_with_no_finished_pass_says_so():
    assert mw.passes_text([], outcome(rules.CLEAR)) == "None finished"


def test_the_mode_names_the_limit():
    assert mw.pass_mode("standard", 4) == "Standard, up to 4 passes"
    assert mw.pass_mode("quick", 1) == "Quick, one pass"


def test_an_online_document_links_to_its_address():
    html = mw.link_text("Policy.docx", "https://x.sharepoint.com/a/Policy.docx", True)
    assert 'href="https://x.sharepoint.com/a/Policy.docx"' in html


def test_a_local_file_links_as_a_file_url():
    html = mw.link_text("Plan.docx", r"C:\docs\Plan.docx", False)
    assert "file:///C:/docs/Plan.docx" in html


def test_long_paths_can_wrap():
    assert "\u200b" in mw.wrappable("https://a.example/b/c")


RECORDS = [
    {"page": 1, "category": "Correctness", "original": "teh", "revised": "the"},
    {"page": 1, "category": "Correctness", "original": "and ", "revised": ""},
    {"page": 1, "category": "Clarity", "original": "", "revised": ", please"},
    {"page": 1, "category": "Correctness", "original": "recieve", "revised": "receive"},
    {"page": 2, "category": "Clarity", "original": "in order to", "revised": "to"},
    {"page": None, "category": "Clarity", "original": "x", "revised": "y"},
]


def test_changes_group_by_page_and_skip_records_without_one():
    grouped = summaries.page_changes(RECORDS)
    assert sorted(grouped) == [1, 2]
    assert len(grouped[1]) == 4


def test_the_hover_for_a_changed_page_gives_the_mix_and_examples():
    tip = summaries.page_tip(1, summaries.page_changes(RECORDS)[1])
    lines = tip.split("\n")
    assert lines[0] == "Page 1: 4 changes (3 Correctness, 1 Clarity)"
    assert lines[1] == "  'teh' to 'the'"
    assert lines[2] == "  removed 'and'"
    assert lines[-1] == "  and 1 more"


def test_the_hover_for_quiet_and_unread_pages():
    assert summaries.page_tip(5, []) == "Page 5: nothing changed"
    assert "could not read" in summaries.page_tip(5, [], unread=True)


def test_the_dominant_kind_colours_the_block():
    assert summaries.dominant(summaries.page_changes(RECORDS)[1]) == "Correctness"
    assert summaries.dominant([]) is None


def test_long_changed_text_is_shortened():
    long = summaries.describe({"original": "a" * 80, "revised": "b"})
    assert "\u2026" in long and len(long) < 60


def test_the_copied_summary_carries_the_result_and_the_pages():
    text = summaries.summary_text(
        name="Policy.docx", location="https://x/y", headline="Done: 5 suggestions applied in 32 s",
        by_type={"Correctness": 4, "Clarity": 1, "Delivery": 0}, manual="40 s", run="32 s", saved="7 s",
        passes=["Changes made in 1 pass: pass 1 (5)"], pages=3, chars="5,607 to 5,602 characters",
        backup="None made", changed=summaries.page_changes(RECORDS), unread={3},
    )
    assert text.startswith("Grammar Sweeper summary")
    assert "Result: Done: 5 suggestions applied in 32 s (4 Correctness, 1 Clarity)" in text
    assert "  Changes made in 1 pass: pass 1 (5)" in text
    assert "  Page 1: 4 (3 Correctness, 1 Clarity)" in text
    assert "pages 3" in text


def test_durations_never_show_seconds():
    f = summaries.format_minutes
    assert f(0) == "under 1 min" and f(59) == "under 1 min"
    assert f(60) == "1 min" and f(296) == "5 min" and f(3000) == "50 min"
    assert f(3900) == "1 h 05 min"


def test_spark_series_folds_changes_per_page_into_buckets():
    from sweeper.summary import spark_series

    changed = {1: [{}], 2: [{}, {}], 10: [{}]}
    assert spark_series(changed, 0) == []
    assert spark_series(changed, 10) == [1, 2, 0, 0, 0, 0, 0, 0, 0, 1]
    folded = spark_series(changed, 80, points=8)
    assert len(folded) == 8 and sum(folded) == 4
