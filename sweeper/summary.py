"""What the summary page says, as plain functions: what each pass did, what changed on each page,
and the text copied to the clipboard. No interface code, so it is tested without a window."""

from __future__ import annotations

from collections import Counter

SNIPPET = 28  # characters of changed text shown in a hover or the copied summary
EXAMPLES = 3  # changes described per page in a hover


def format_minutes(seconds: float) -> str:
    """A duration to the nearest minute, never seconds: "under 1 min", "5 min", "1 h 05 min"."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return "under 1 min"
    hours, minutes = divmod(int(seconds / 60 + 0.5), 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


def passes_lines(passes: list, outcome) -> list[str]:
    """What the passes did. A pass that applied something made the changes; a pass that found
    nothing is a check. A document that needed one pass of work and two checks is one pass of
    work, however many times Standard walked it."""
    if not passes:
        return ["None finished"]
    work = [record for record in passes if record.applied]
    checks = [record for record in passes if not record.applied]
    lines = []
    if work:
        listed = ", ".join(f"pass {record.index} ({record.applied:,})" for record in work)
        lines.append(f"Changes made in {plural(len(work), 'pass', 'passes')}: {listed}")
        if checks:
            lines.append(f"{plural(len(checks), 'further pass', 'further passes')} checked and found nothing")
    else:
        lines.append(f"{plural(len(checks), 'pass', 'passes')} checked and found nothing")
    reason = {
        "clear": "Stopped because two passes in a row found nothing",
        "limit": "Stopped at the pass limit",
        "repeating": "Stopped because Grammarly began undoing its own changes",
    }.get(outcome.result, "Stopped early")
    lines.append(reason)
    return lines


def page_changes(records: list[dict]) -> dict[int, list[dict]]:
    """Change records grouped by the page they landed on. A record with no page is left out."""
    pages: dict[int, list[dict]] = {}
    for record in records or []:
        page = record.get("page")
        if isinstance(page, int) and page > 0:
            pages.setdefault(page, []).append(record)
    return pages


def spark_series(changed: dict[int, list[dict]], pages: int, points: int = 40) -> list[int]:
    """Changes per page across the document, folded into at most `points` buckets so a long document
    still fits one small line. Empty when the page count is unknown."""
    if pages <= 0:
        return []
    count = min(points, pages)
    series = [0] * count
    for page, records in changed.items():
        if 1 <= page <= pages:
            series[(page - 1) * count // pages] += len(records)
    return series


def snippet(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SNIPPET else text[: SNIPPET - 1].rstrip() + "…"


def describe(record: dict) -> str:
    """One change in a few words: 'teh' to 'the', added 'x', or removed 'x'."""
    before, after = snippet(record.get("original", "")), snippet(record.get("revised", ""))
    if before and after:
        return f"'{before}' to '{after}'"
    if after:
        return f"added '{after}'"
    if before:
        return f"removed '{before}'"
    return record.get("category", "change")


def page_tip(page: int, changes: list[dict], unread: bool = False) -> str:
    """The hover text for one page of the strip."""
    if not changes:
        if unread:
            return f"Page {page}: Grammarly could not read this page, so it was not checked"
        return f"Page {page}: nothing changed"
    kinds = Counter(record.get("category") or "Unclassified" for record in changes)
    mix = ", ".join(f"{count} {name}" for name, count in kinds.most_common())
    lines = [f"Page {page}: {plural(len(changes), 'change')} ({mix})"]
    lines += [f"  {describe(record)}" for record in changes[:EXAMPLES]]
    if len(changes) > EXAMPLES:
        lines.append(f"  and {len(changes) - EXAMPLES} more")
    return "\n".join(lines)


def dominant(changes: list[dict]) -> str | None:
    if not changes:
        return None
    return Counter(record.get("category") or "Unclassified" for record in changes).most_common(1)[0][0]


def summary_text(
    *, name: str, location: str, headline: str, by_type: dict, manual: str, run: str, saved: str,
    passes: list[str], pages: int, chars: str, backup: str, changed: dict[int, list[dict]], unread: set[int],
) -> str:
    """The summary as plain text, for pasting into an email or a ticket."""
    types = ", ".join(f"{count} {kind}" for kind, count in by_type.items() if count)
    lines = [
        "Grammar Sweeper summary",
        f"Document: {name}",
        f"Location: {location}" if location else "",
        f"Result: {headline}" + (f" ({types})" if types else ""),
        f"Time: {manual} by hand, {run} this run, {saved} saved",
        f"Pages: {pages}" if pages > 0 else "",
        f"Length of text: {chars}",
        "Passes:",
        *[f"  {line}" for line in passes],
        f"Backup: {backup}",
    ]
    if changed:
        lines.append("Changes by page:")
        for page in sorted(changed):
            kinds = Counter(record.get("category") or "Unclassified" for record in changed[page])
            lines.append(f"  Page {page}: {len(changed[page])} ({', '.join(f'{n} {k}' for k, n in kinds.most_common())})")
    if unread:
        lines.append("Not checked, Grammarly could not read: pages " + ", ".join(str(p) for p in sorted(unread)))
    return "\n".join(line for line in lines if line)
