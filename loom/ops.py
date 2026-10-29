"""Semantic operations: deduplicate, validate, and report."""

from __future__ import annotations

import re

from .ast import Document

__all__ = ["dedupe", "lint", "noise_report"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def dedupe(doc: Document) -> tuple[Document, int]:
    """Collapse duplicate rows, keeping the highest-trust copy.

    Duplicated tool output is one of the largest sources of waste in agent
    transcripts, and it also adds noise that competes for attention. The
    ``id`` column is ignored when comparing, since ids are assigned per row.
    """
    removed = 0
    for section in doc.sections:
        cols = section.columns or []
        skip = {i for i, c in enumerate(cols) if c.lower() in ("id", "row", "no")}
        seen: dict[str, int] = {}
        keep: list = []
        for row in section.rows:
            body = [c for i, c in enumerate(row.cells) if i not in skip]
            key = _norm("|".join(body))
            if not key:
                continue
            if key in seen:
                removed += 1
                prev = keep[seen[key]]
                if len(row.cells) > len(prev.cells):
                    keep[seen[key]] = row
                continue
            seen[key] = len(keep)
            keep.append(row)
        section.rows = keep
    return doc, removed


def lint(doc: Document) -> list[str]:
    """Return human-readable warnings. Errors are raised by the parser."""
    problems: list[str] = []
    if not doc.goal:
        problems.append("no !goal: the model has no objective to anchor on")
    if not doc.done:
        problems.append("no !done: success is undefined, so the agent may stop early")
    for section in doc.sections:
        if not section.rows:
            problems.append(f"#{section.name} is empty")
        for row in section.rows:
            joined = "|".join(row.cells)
            if len(joined) > 400:
                problems.append(
                    f"#{section.name} has a {len(joined)}-char row; split it or move it to #refs"
                )
    musts = {_norm(r.text) for r in doc.rules if r.kind == "must"}
    nevers = {_norm(r.text) for r in doc.rules if r.kind == "never"}
    for clash in sorted(musts & nevers):
        problems.append(f"contradiction: {clash!r} is both !must and !never")
    if len(doc.questions) > 8:
        problems.append("more than 8 open questions: resolve some before spending context")
    return problems


def noise_report(doc: Document) -> dict[str, object]:
    """Measure how much of the document is low-signal."""
    rows = [r for s in doc.sections for r in s.rows]
    low_trust = 0
    for section in doc.sections:
        cols = section.columns or []
        if "trust" in cols:
            for row in section.rows:
                try:
                    if float(row.get(cols, "trust", "1")) < 0.5:
                        low_trust += 1
                except ValueError:
                    pass
    return {
        "rows": len(rows),
        "low_trust_rows": low_trust,
        "dup_candidates": len(rows) - len({_norm("|".join(r.cells)) for r in rows}),
    }
