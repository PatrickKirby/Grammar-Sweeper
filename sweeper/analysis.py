"""Turns one accepted suggestion into a record a rule can be mined from, and
turns the records of a run into candidate rules.

Everything here works on plain strings, so it is tested without Word. The aim
is the loop the report exists for: Grammarly keeps fixing the same things in
generated drafts, so those fixes become either a deterministic post-processing
rule or a line of prompt guidance, and the draft stops needing them."""

from __future__ import annotations

import difflib
import hashlib
import re
from collections import defaultdict

SENTENCE_END = re.compile(r"[.!?]\s|[\r\n\x07]")
NEGATIONS = {"not", "no", "never", "none", "without", "cannot", "neither", "nor", "n't", "unless", "except"}
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")
MECHANICAL_WORDS = ("spelling", "punctuation", "comma", "period", "hyphen", "apostrophe", "capital", "agreement",
                    "article", "preposition", "verb", "plural", "determiner", "quotation", "spacing", "space")


def sentence_around(text: str, start: int, end: int, limit: int = 600) -> str:
    """The whole sentence that holds text[start:end], trimmed to `limit`."""
    left = 0
    for match in SENTENCE_END.finditer(text, 0, max(0, start)):
        left = match.end()
    found = SENTENCE_END.search(text, end)
    right = found.end() if found else len(text)
    return text[left:right].strip()[:limit]


def edit_kind(original: str, revised: str) -> str:
    if not original and revised:
        return "insert"
    if original and not revised:
        return "delete"
    if original.lower() == revised.lower():
        return "case"
    strip = lambda s: re.sub(r"[\W_]+", "", s)  # noqa: E731
    if strip(original) == strip(revised):
        return "punctuation"
    if not WORD.search(original) and not WORD.search(revised):
        return "punctuation"
    return "replace"


def token_diff(before: str, after: str) -> tuple[list[str], list[str]]:
    """Words removed and words added between two sentences."""
    a, b = WORD.findall(before), WORD.findall(after)
    removed: list[str] = []
    added: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += a[i1:i2]
        if tag in ("replace", "insert"):
            added += b[j1:j2]
    return removed, added


def kind_from_tokens(removed, added, original: str, revised: str) -> str:
    """Kind of edit judged on whole words. The character-level change can be a
    slice of a word ('til' out of 'utilise'), which is not what was edited."""
    if removed and added:
        if [t.lower() for t in removed] == [t.lower() for t in added]:
            return "case"
        return "replace"
    if added:
        return "insert"
    if removed:
        return "delete"
    return edit_kind(original, revised)


def flags_for(removed, added, original: str, revised: str, before_sentence: str, known_terms=(), after_sentence: str = "") -> list[str]:
    """Why a human should look at this edit: numbers, names, negations, defined terms.
    An edit that touches any of them can change what a sentence claims."""
    flags: list[str] = []
    touched = [*removed, *added] or WORD.findall(original + " " + revised)
    if re.search(r"\d", original + revised) or any(any(ch.isdigit() for ch in t) for t in touched):
        flags.append("number")
    if any(t.lower() in NEGATIONS or t.lower().endswith("n't") for t in touched):
        flags.append("negation")
    starts = {m.group(0) for m in (WORD.search(before_sentence), WORD.search(after_sentence)) if m}
    if any(t[:1].isupper() and t not in starts and not t.isupper() and len(t) > 1 for t in touched):
        flags.append("name")
    if any((t.isupper() and len(t) > 1 and not t.isdigit()) or t in known_terms for t in touched):
        flags.append("defined-term")
    return flags


def rule_name(card: str, category: str) -> str:
    """Grammarly's own name for the rule, from the card header before 'learn more'.
    Header parts look like 'correctness correct your spelling' or 'improve your text'."""
    parts = [p.strip() for p in card.split("|")]
    for part in parts:
        low = part.lower()
        if low.startswith("learn more"):
            break
        if not low or low == "suggestions" or "·" in low:
            continue
        for name in ("correctness", "clarity", "engagement", "delivery"):
            if low.startswith(name):
                low = low[len(name):].strip()
        if low:
            return low
    return ""


def classify(category: str, kind: str, rule: str) -> str:
    """mechanical: a fix that can be made without judgement, so it belongs in
    deterministic post-processing. stylistic: a choice, so it belongs in the prompt."""
    if category == "Correctness":
        return "mechanical"
    if kind in ("punctuation", "case"):
        return "mechanical"
    if any(word in rule for word in MECHANICAL_WORDS):
        return "mechanical"
    return "stylistic"


def anchor_for(sentence: str) -> dict:
    """A short text anchor. Page numbers drift as edits reflow the document;
    these words, and their hash, find the same place again."""
    words = sentence.split()
    return {"anchor": " ".join(words[:8]), "anchor_id": hashlib.sha1(" ".join(words[:20]).encode("utf-8")).hexdigest()[:10]}


def enrich(found: dict, text_before: str, text_after: str, category: str, card: str, known_terms=()) -> dict:
    """Derived fields for one record. `found` comes from changes.locate_change."""
    index = found["index"]
    original, revised = found["original"], found["revised"]
    before_sentence = sentence_around(text_before, index, index + len(original))
    after_sentence = sentence_around(text_after, index, index + len(revised))
    removed, added = token_diff(before_sentence, after_sentence)
    kind = kind_from_tokens(removed, added, original, revised)
    rule = rule_name(card, category)
    return {
        "rule": rule,
        "kind": kind,
        "class": classify(category, kind, rule),
        "sentence_before": before_sentence,
        "sentence_after": after_sentence,
        "tokens_removed": removed,
        "tokens_added": added,
        "flags": flags_for(removed, added, original, revised, before_sentence, known_terms, after_sentence),
        **anchor_for(before_sentence),
    }


def pattern_of(rec: dict) -> str:
    """The edit with the sentence stripped away, so repeats of the same fix group together."""
    removed = " ".join(t.lower() for t in rec.get("tokens_removed", []))
    added = " ".join(t.lower() for t in rec.get("tokens_added", []))
    if not removed and not added:
        removed, added = rec.get("original", "").strip().lower(), rec.get("revised", "").strip().lower()
    return f"{removed or '(nothing)'} -> {added or '(nothing)'}"


def instruction_for(group: dict) -> str:
    """A drafted line to paste into a prompt or a lint list. A draft to edit, not a decision."""
    kind, rule = group["kind"], group["rule"] or group["category"].lower()
    removed, _, added = group["pattern"].partition(" -> ")
    if group["class"] == "mechanical":
        if kind == "punctuation":
            return f"Post-process: apply the {rule} fix ({group['pattern']})."
        return f"Post-process: replace '{removed}' with '{added}' ({rule})."
    if kind == "delete":
        return f"Do not write '{removed}'; it is deleted on review ({rule})."
    if kind == "insert":
        return f"Add '{added}' where the draft omits it ({rule})."
    return f"Write '{added}', not '{removed}' ({rule})."


def mine_rules(records: list[dict]) -> list[dict]:
    """Group records by type, rule and normalised edit. Most frequent first."""
    groups: dict[tuple, dict] = {}
    for rec in records:
        key = (rec.get("category", "Unclassified"), rec.get("rule", ""), pattern_of(rec))
        group = groups.setdefault(
            key,
            {
                "category": key[0], "rule": key[1], "pattern": key[2], "kind": rec.get("kind", ""),
                "class": rec.get("class", "stylistic"), "count": 0, "examples": [], "flagged": 0,
            },
        )
        group["count"] += 1
        group["flagged"] += 1 if rec.get("flags") else 0
        if len(group["examples"]) < 3:
            group["examples"].append(
                {"before": rec.get("sentence_before", ""), "after": rec.get("sentence_after", ""), "anchor": rec.get("anchor", "")}
            )
    out = sorted(groups.values(), key=lambda g: (-g["count"], g["category"]))
    for group in out:
        group["instruction"] = instruction_for(group)
        group["recurring"] = group["count"] >= 2
    return out


def recurring_phrases(records: list[dict], minimum: int = 2) -> list[tuple[str, int]]:
    """Phrases removed again and again, whatever the rule that removed them."""
    counts: dict[str, int] = defaultdict(int)
    for rec in records:
        removed = " ".join(t.lower() for t in rec.get("tokens_removed", []))
        if removed:
            counts[removed] += 1
    return sorted(((p, n) for p, n in counts.items() if n >= minimum), key=lambda item: -item[1])


def fewshot_rows(groups: list[dict]) -> list[dict]:
    """Prompt-ready pairs, one object per example, for stylistic rules only.
    Mechanical fixes are post-processing and need no examples."""
    rows = []
    for group in groups:
        if group["class"] != "stylistic":
            continue
        for example in group["examples"]:
            if example["before"] and example["after"] and example["before"] != example["after"]:
                rows.append(
                    {
                        "rule": group["rule"] or group["category"],
                        "category": group["category"],
                        "instruction": group["instruction"],
                        "before": example["before"],
                        "after": example["after"],
                        "count_in_run": group["count"],
                    }
                )
    return rows


def postprocess_rows(groups: list[dict]) -> list[dict]:
    return [
        {"rule": g["rule"], "category": g["category"], "pattern": g["pattern"], "count": g["count"],
         "instruction": g["instruction"]}
        for g in groups
        if g["class"] == "mechanical"
    ]
