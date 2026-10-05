"""Record enrichment, rule mining, exports, report, JSON log and the retry rules. No Word needed."""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bulk_accept as engine
from sweeper import analysis
from sweeper.changes import CONTEXT, build_report, locate_change, write_exports

BEFORE = "Intro sentence. The vendor shall deliver 30 days of support, not 60. Next one."
AFTER = "Intro sentence. The vendor shall deliver 30 days of support, not 90. Next one."
CARD = "suggestions | correctness correct your spelling | correctness · correct your spelling | learn more | the vendor"


def _record(before=BEFORE, after=AFTER, category="Correctness", card=CARD):
    found = locate_change(before, after)
    return {"category": category, "card": card, **found, **analysis.enrich(found, before, after, category, card)}


def test_context_is_one_hundred_characters():
    assert CONTEXT == 100
    long_before = "a " * 200 + "cat" + " b" * 200
    found = locate_change(long_before, long_before.replace("cat", "dog"))
    assert len(found["context_before"]) == 100 and len(found["context_after"]) == 100


def test_enrich_gives_sentences_rule_kind_and_anchor():
    rec = _record()
    assert rec["sentence_before"].startswith("The vendor shall deliver")
    assert "90" in rec["sentence_after"] and "60" in rec["sentence_before"]
    assert rec["rule"] == "correct your spelling" and rec["class"] == "mechanical"
    assert rec["kind"] == "replace" and rec["anchor"].startswith("The vendor shall")
    assert len(rec["anchor_id"]) == 10


def test_numbers_and_negations_are_flagged_for_review():
    assert "number" in _record()["flags"]
    neg = _record("It is allowed here. Ok.", "It is not allowed here. Ok.", "Clarity", "suggestions | improve your text | learn more")
    assert "negation" in neg["flags"]
    plain = _record("Their was a plan. Ok.", "There was a plan. Ok.")
    assert plain["flags"] == []


def test_defined_terms_and_names_are_flagged():
    rec = _record("We asked FIONA to deliver. Ok.", "We asked Fiona to deliver. Ok.", "Clarity", "suggestions | improve your text | learn more")
    assert "defined-term" in rec["flags"]


def test_mechanical_and_stylistic_are_split():
    assert analysis.classify("Correctness", "replace", "correct your spelling") == "mechanical"
    assert analysis.classify("Clarity", "punctuation", "improve your text") == "mechanical"
    assert analysis.classify("Clarity", "replace", "improve your text") == "stylistic"
    assert analysis.classify("Delivery", "replace", "replace the word") == "stylistic"


def test_mining_groups_repeats_and_drafts_an_instruction():
    a = _record("We will utilise the tool. Ok.", "We will use the tool. Ok.", "Clarity", "suggestions | replace the word | learn more")
    b = _record("They utilise it daily. Ok.", "They use it daily. Ok.", "Clarity", "suggestions | replace the word | learn more")
    groups = analysis.mine_rules([a, b])
    assert groups[0]["count"] == 2 and groups[0]["recurring"] and "per_1000_words" not in groups[0]
    assert "Write 'use', not 'utilise'" in groups[0]["instruction"]
    assert analysis.recurring_phrases([a, b]) == [("utilise", 2)]


def test_exports_split_by_class(tmp_path):
    mech = _record()
    style = _record("We will utilise the tool. Ok.", "We will use the tool. Ok.", "Clarity", "suggestions | replace the word | learn more")
    made = write_exports(tmp_path, "t", [mech, style])
    fewshot = [json.loads(line) for line in made["fewshot"].read_text(encoding="utf-8").splitlines()]
    assert len(fewshot) == 1 and fewshot[0]["category"] == "Clarity"
    post = json.loads(made["postprocess-t.json"].read_text(encoding="utf-8"))
    assert len(post) == 1 and post[0]["category"] == "Correctness"


def test_report_has_rule_tables_flag_filter_and_grey_type(tmp_path):
    rec = {**_record(), "time": "10:00:00", "page": 4, "section": ["2. Plan", "2.1 Scope"]}
    loose = {**_record(category="Unclassified"), "time": "10:00:01", "page": 4}
    out = build_report(tmp_path / "r.html", {"Applied": 2}, [rec, loose])
    text = out.read_text(encoding="utf-8")
    assert "mechanical fixes" in text and "stylistic choices" in text
    assert "Needs review" in text and "#8A8C99" in text and "2. Plan &gt; 2.1 Scope" in text


def test_log_file_is_json_lines_and_status_stays_off_it(tmp_path):
    path = tmp_path / "run.log"
    with path.open("w", encoding="utf-8") as handle:
        engine.log("WARNING: something", handle)
        engine.log("plain", handle)
        budget = engine.Budget(engine.parse_args([]))
        engine.show_status(budget, handle)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [x["level"] for x in lines] == ["warning", "info"]
    assert all("STATUS" not in x["msg"] for x in lines)


def test_swallowed_errors_are_counted_by_kind():
    engine.SWALLOWED.clear()
    engine.swallow("click-stale-element", RuntimeError("x"))
    engine.swallow("click-stale-element", RuntimeError("y"))
    assert engine.SWALLOWED["click-stale-element"] == 2
    engine.SWALLOWED.clear()
