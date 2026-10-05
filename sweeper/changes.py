"""What the run changed: one record per accepted suggestion, the paragraph
comparison taken at the end, and the HTML report built from both.

Two captures, because they answer different questions. The per-accept record
carries the type, rule, page and card wording, which a final comparison cannot
recover. The final comparison is the ground truth of what differs, and catches
anything the per-accept records missed. The JSON lines file is the product; the
HTML report is a view of it."""

from __future__ import annotations

import base64
import datetime as dt
import html
import json
import os
from pathlib import Path

from . import brand, texture, version
from .settings import APERTURA_URL, COFFEE_URL, COMPANY, REPO_URL
from .analysis import fewshot_rows, mine_rules, postprocess_rows, recurring_phrases

# Grammarly's own tab colours, sampled from its panel. Grey is ours: a card whose
# type could not be read is shown, never folded into one of the four.
TYPE_COLOURS = {
    "Correctness": "#DB3212",
    "Clarity": "#2859D8",
    "Engagement": "#29685E",
    "Delivery": "#5854E2",
    "Unclassified": "#8A8C99",
}
TYPES = ("Correctness", "Clarity", "Engagement", "Delivery")
ALL_TYPES = (*TYPES, "Unclassified")
CONTEXT = 100  # characters kept either side of an edit


class ChangeLog:
    """Append-only JSON lines. One object per accepted suggestion."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.handle = path.open("a", encoding="utf-8") if path else None
        self.records: list[dict] = []

    def add(self, **fields) -> None:
        self.records.append(fields)
        if self.handle:
            self.handle.write(json.dumps(fields, ensure_ascii=False) + "\n")
            self.handle.flush()

    def close(self) -> None:
        if self.handle:
            self.handle.close()
            self.handle = None


def _in_word(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch in "'’")


def _whole_words_start(text: str, start: int, window: int) -> str:
    """text[start - window:start] without a word cut in half at its left edge.
    When in doubt the string is made shorter."""
    left = max(0, start - window)
    piece = text[left:start]
    if left and piece and not text[left - 1].isspace() and not piece[0].isspace():
        gap = next((i for i, ch in enumerate(piece) if ch.isspace()), None)
        piece = piece[gap + 1:] if gap is not None else ""
    return piece


def _whole_words_end(text: str, start: int, window: int) -> str:
    """text[start:start + window] without a word cut in half at its right edge."""
    right = start + window
    piece = text[start:right]
    if right < len(text) and piece and not text[right].isspace() and not piece[-1].isspace():
        gap = next((i for i in range(len(piece) - 1, -1, -1) if piece[i].isspace()), None)
        piece = piece[:gap] if gap is not None else ""
    return piece


def locate_change(before: str, after: str, context: int = CONTEXT) -> dict:
    """The one region that differs between two texts, found from both ends.
    Exact for a single edit, which is what one accepted card makes.

    An edit that cuts through a word ('ve' to 's' inside 'have' to 'has') is widened
    to the whole word, and the context on either side starts and ends on a whole
    word, because half a word reads as a different word."""
    head = len(os.path.commonprefix([before, after]))
    rest_b, rest_a = before[head:], after[head:]
    tail = len(os.path.commonprefix([rest_b[::-1], rest_a[::-1]]))
    end_b, end_a = len(before) - tail, len(after) - tail
    original, revised = before[head:end_b], after[head:end_a]
    if head and _in_word(before[head - 1]) and any(_in_word(c) for c in (original[:1], revised[:1])):
        while head and _in_word(before[head - 1]):
            head -= 1
    if end_b < len(before) and _in_word(before[end_b]) and any(_in_word(c) for c in (original[-1:], revised[-1:])):
        while end_b < len(before) and _in_word(before[end_b]):
            end_b += 1
            end_a += 1
    original, revised = before[head:end_b], after[head:end_a]
    return {
        "index": head,
        "original": original,
        "revised": revised,
        "context_before": _whole_words_start(before, head, context),
        "context_after": _whole_words_end(after, end_a, context),
    }


def _esc(text) -> str:
    return html.escape(str(text) if text is not None else "")


def write_exports(folder: Path, stamp: str, records: list[dict]) -> dict[str, Path]:
    """Files other tools read: mined rules, post-processing patterns, few-shot pairs."""
    groups = mine_rules(records)
    made: dict[str, Path] = {}
    pairs = (
        (f"rules-{stamp}.json", groups),
        (f"postprocess-{stamp}.json", postprocess_rows(groups)),
    )
    for name, payload in pairs:
        made[name] = folder / name
        made[name].write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    shots = fewshot_rows(groups)
    made["fewshot"] = folder / f"fewshot-{stamp}.jsonl"
    made["fewshot"].write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in shots), encoding="utf-8")
    return made


def _rule_table(groups: list[dict]) -> str:
    rows = "".join(
        f'<tr><td>{g["count"]}</td>'
        f'<td><span class="pill" style="background:{TYPE_COLOURS.get(g["category"], "#8A8C99")}">{_esc(g["category"])}</span></td>'
        f'<td>{_esc(g["rule"])}</td><td><code>{_esc(g["pattern"])}</code></td>'
        f'<td>{_esc(g["instruction"])}</td><td>{str(g["flagged"]) + " of " + str(g["count"]) if g["flagged"] else ""}</td>'
        f'<td class="c">{_esc(g["examples"][0]["before"][:160]) if g["examples"] else ""}</td></tr>'
        for g in groups
    )
    cols = "".join(f'<col style="width:{width}%">' for width in RULE_COLUMNS)
    return (
        f'<div class="wide"><table class="rules"><colgroup>{cols}</colgroup>'
        "<tr><th>Times</th><th>Type</th><th>Grammarly rule</th><th>Edit</th>"
        f"<th>Drafted instruction</th><th>Needs review</th><th>Example</th></tr>{rows}</table></div>"
    )


# Column widths in percent, shared by both candidate rule tables so they line up one under the other.
RULE_COLUMNS = (6, 11, 13, 17, 25, 8, 20)


LOGO = Path(__file__).resolve().parents[1] / "assets" / "icon.png"


REPORT_LOGO = 60  # the tile, in css pixels


def logo_data_uri(size: int = REPORT_LOGO) -> str:
    """The styled logo inlined, so the report stays one self-contained file. Empty when it cannot be
    drawn, and the report simply has no logo."""
    return brand.logo_data_uri(size)


def texture_data_uri() -> str:
    """The same fine texture as the window, inlined. Empty if Pillow is missing."""
    try:
        return "data:image/png;base64," + base64.b64encode(texture.tile_png("#F3F4F8", "#4F56D6")).decode("ascii")
    except Exception:  # noqa: BLE001 - a plain background is fine
        return ""


def run_started(stamp) -> str:
    """The run's file stamp (20261005-172717) as a date and time a person can read."""
    try:
        moment = dt.datetime.strptime(str(stamp), "%Y%m%d-%H%M%S")
    except ValueError:
        return str(stamp)
    return f"{moment.day} {moment:%B %Y}, {moment:%H:%M}"


# Light, the same palette and weights as the summary page: bold headings, regular context text,
# no yellow anywhere, violet for anything that needs a second look.
REPORT_CSS = """
:root{--bg:#F3F4F8;--card:#FFFFFF;--text:#1B1C22;--muted:#5E6070;--line:#DCDEE8;--accent:#4F56D6;--violet:#7A3FD1;--violet-bg:#ECE3FA;--tint:#ECEEFB}
*{box-sizing:border-box}
body{font:14px/1.55 'Segoe UI Variable Text','Segoe UI',sans-serif;font-weight:400;background:var(--bg);color:var(--text);margin:0;padding:28px 20px}
main{max-width:1120px;margin:0 auto}
h1{font-size:22px;font-weight:700;margin:0 0 4px}
h2{font-size:15px;font-weight:700;margin:0 0 12px}
.sub,.note,.c{color:var(--muted);font-weight:400}
.sub{margin:0 0 18px}
.note{margin:-6px 0 12px;font-size:13px}
p{margin:0 0 10px} p:last-child{margin-bottom:0}
.c{font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}
dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 28px;margin:0}
dl.kv dt{font-weight:600} dl.kv dd{margin:0;font-weight:400;overflow-wrap:anywhere}
.tiles{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
button.f,button.g{font:inherit;color:var(--text);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:0 0 10px;min-width:108px;cursor:pointer;text-align:center;overflow:hidden}
button.f:hover,button.g:hover{border-color:var(--accent)}
button.f .bar,button.g .bar{display:block;height:4px;margin-bottom:8px}
button.f .n,button.g .n{display:block;font-size:20px;font-weight:700}
button.f .cap,button.g .cap{display:block;font-size:12px;color:var(--muted);font-weight:400}
button.off{opacity:.4}
.wide{overflow-x:auto}
table{border-collapse:collapse;width:100%}
table.rules{table-layout:fixed}
table.rules td,table.rules th{overflow-wrap:anywhere;white-space:normal}
.head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
a.coffee{background:#FFDD00;color:#000;font-weight:700;font-size:13px;border-radius:6px;padding:7px 16px;text-decoration:none;white-space:nowrap}
.brand{display:flex;align-items:center;gap:14px}.brand img{display:block}
footer{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:22px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
footer a{color:var(--accent);text-decoration:none}
a.coffee:hover{background:#FFE63D}
th{font-weight:700;text-align:left;padding:8px 10px;border-bottom:2px solid var(--line);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;font-weight:400}
tr:hover td{background:#F7F8FC}
.pill{color:#fff;border-radius:10px;padding:1px 10px;font-size:12px;font-weight:600}
.flag{background:var(--violet-bg);color:var(--violet);border-radius:8px;padding:0 8px;font-size:11px;font-weight:600;margin-right:4px}
del{background:#F8DEDA;color:#8A2A1F;text-decoration:none;border-radius:3px}
ins{background:#DDF3E7;color:#176B45;text-decoration:none;border-radius:3px}
code{background:var(--tint);padding:1px 6px;border-radius:4px;font-family:inherit;font-size:13px}
.heat{display:flex;align-items:flex-end;gap:2px;height:64px;border-bottom:1px solid var(--line)}
.heat .col{display:flex;flex-direction:column-reverse;width:7px}
.heat span{display:block;width:7px}
"""


def build_report(path: Path, meta: dict, records: list[dict]) -> Path:
    """A single self-contained HTML file, light and styled as the summary page is: filter by type
    or by need for review, original beside revised, mined rules split into mechanical and
    stylistic."""
    counts = {name: 0 for name in ALL_TYPES}
    for rec in records:
        name = rec.get("category", "Unclassified")
        counts[name] = counts.get(name, 0) + 1
    flagged = sum(1 for rec in records if rec.get("flags"))
    tiles = "".join(
        f'<button class="f" data-t="{name}"><span class="bar" style="background:{TYPE_COLOURS[name]}"></span>'
        f'<span class="n">{count}</span><span class="cap">{name}</span></button>'
        for name, count in counts.items()
    )
    tiles += (
        '<button class="g" data-flag="1"><span class="bar" style="background:#7A3FD1"></span>'
        f'<span class="n">{flagged}</span><span class="cap">Needs review</span></button>'
    )
    rows = []
    for number, rec in enumerate(records, 1):
        cat = rec.get("category", "Unclassified")
        flags = rec.get("flags") or []
        section = " > ".join(rec.get("section", []) or [])
        rows.append(
            f'<tr data-t="{_esc(cat)}" data-flag="{1 if flags else 0}"><td>{number}</td><td>{_esc(str(rec.get("time", ""))[:5])}</td>'
            f'<td>{_esc(rec.get("page", ""))}<br><span class="c">{_esc(rec.get("anchor_id", ""))}</span></td>'
            f'<td><span class="pill" style="background:{TYPE_COLOURS.get(cat, "#8A8C99")}">{_esc(cat)}</span>'
            f'<br><span class="c">{_esc(rec.get("rule", ""))}<br>{_esc(rec.get("kind", ""))}, {_esc(rec.get("class", ""))}</span></td>'
            f'<td class="o"><span class="c">{_esc(section)}</span><br>{_esc(rec.get("context_before", ""))}'
            f'<del>{_esc(rec.get("original", ""))}</del>{_esc(rec.get("context_after", ""))}</td>'
            f'<td class="r">{_esc(rec.get("context_before", ""))}<ins>{_esc(rec.get("revised", ""))}</ins>'
            f'{_esc(rec.get("context_after", ""))}</td>'
            f'<td>{"".join(f"<span class=flag>{_esc(f)}</span>" for f in flags)}</td></tr>'
        )
    pages: dict = {}
    for rec in records:
        if isinstance(rec.get("page"), int) and rec["page"] > 0:
            per = pages.setdefault(rec["page"], {})
            name = rec.get("category", "Unclassified")
            per[name] = per.get(name, 0) + 1
    peak = max((sum(v.values()) for v in pages.values()), default=1)
    heat = "".join(
        '<div class="col" title="page {p}: {n}">'.format(p=page, n=sum(per.values()))
        + "".join(
            f'<span style="height:{max(3, int(56 * per[name] / peak))}px;background:{TYPE_COLOURS[name]}"></span>'
            for name in ALL_TYPES
            if per.get(name)
        )
        + "</div>"
        for page, per in sorted(pages.items())
    )
    groups = mine_rules(records)
    mechanical = [g for g in groups if g["class"] == "mechanical"]
    stylistic = [g for g in groups if g["class"] == "stylistic"]
    repeats = "".join(
        f"<li><code>{_esc(phrase)}</code> removed {n} times</li>" for phrase, n in recurring_phrases(records)
    )
    facts = "".join(
        f"<dt>Run started</dt><dd>{_esc(run_started(v))}</dd>" if k == "Run" else f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
        for k, v in meta.items()
    )
    title = _esc(meta.get("Document", "")) or "Grammar Sweeper report"
    grain = texture_data_uri()
    grain_css = f"body{{background-image:url({grain})}}" if grain else ""
    logo = logo_data_uri()
    logo_tag = f'<img src="{logo}" alt="">' if logo else ""
    shown = brand.display_size(REPORT_LOGO)
    logo_css = f".brand img{{width:{shown}px;height:{shown}px}}" if logo else ""
    path.write_text(
        f"""<!doctype html><meta charset="utf-8"><title>Grammar Sweeper report</title>
<style>{REPORT_CSS}{grain_css}{logo_css}</style>
<main>
<div class="brand">{logo_tag}<div><h1>Grammar Sweeper report</h1><p class="sub">{title}</p></div></div>
<div class="card"><h2>This run</h2><dl class="kv">{facts}</dl></div>
<div class="card"><h2>How to read this report</h2>
<p><b>Needs review.</b> An edit is flagged when it touched a number, a negation (not, never), a capitalised name, or an ALL-CAPS defined term. Those are the edits most able to change what a sentence claims, so check them first. The reason is shown on each row.</p>
<p><b>Candidate rules.</b> Edits of the same kind are grouped. <i>Mechanical fixes</i> (spelling, punctuation) are safe to repeat, so they can become a find-and-replace list you run before Grammarly. <i>Stylistic choices</i> are your house style showing through: paste the drafted instructions into a style guide, or into the prompt of an AI drafting tool, so the next draft starts closer to the final one. A rule is worth adopting once it repeats (a Times of 2 or more), ideally across several documents. Nothing reads these rules automatically yet; the files saved beside this report are for you to use.</p></div>
<div class="card"><h2>Where it changed</h2><p class="note">Suggestions applied by page, coloured by type. Hover a column for the page.</p><div class="heat">{heat}</div></div>
<div class="card"><h2>Candidate rules: mechanical fixes, for deterministic post-processing ({len(mechanical)})</h2>
{_rule_table(mechanical)}</div>
<div class="card"><h2>Candidate rules: stylistic choices, for prompt guidance and few-shot examples ({len(stylistic)})</h2>
{_rule_table(stylistic)}</div>
<div class="card"><h2>Phrases removed repeatedly</h2><ul>{repeats or "<li>None removed more than once.</li>"}</ul></div>
<div class="card"><h2>Every applied suggestion ({len(records)})</h2>
<p class="note">Click a type to hide or show it. Needs review shows only the edits that touch a number, a negation, a name or a defined term.</p>
<div class="tiles">{tiles}</div>
<div class="wide"><table id="t"><tr><th>#</th><th>Time</th><th>Page, anchor</th><th>Type, rule</th><th>Original</th><th>Revised</th><th>Review</th></tr>{"".join(rows)}</table></div></div>
<footer><span>{_esc(COMPANY)} &middot; v{_esc(version.VERSION)} &middot; <a href="{REPO_URL}">GitHub</a> &middot; <a href="{APERTURA_URL}">The Apertura</a></span>
<a class="coffee" href="{COFFEE_URL}">&#9749;&nbsp; Buy me a coffee</a></footer>
</main>
<script>
const on=new Set([...document.querySelectorAll('button.f')].map(b=>b.dataset.t));
let onlyFlag=false;
function apply(){{document.querySelectorAll('#t tr[data-t]').forEach(r=>{{
 r.style.display=(on.has(r.dataset.t)&&(!onlyFlag||r.dataset.flag==='1'))?'':'none';}});}}
document.querySelectorAll('button.f').forEach(b=>b.onclick=()=>{{
 const t=b.dataset.t; on.has(t)?on.delete(t):on.add(t); b.classList.toggle('off',!on.has(t)); apply();}});
document.querySelector('button.g').onclick=e=>{{const b=e.currentTarget;onlyFlag=!onlyFlag;b.classList.toggle('off',!onlyFlag);apply();}};
document.querySelector('button.g').classList.add('off');
</script>""",
        encoding="utf-8",
    )
    return path
