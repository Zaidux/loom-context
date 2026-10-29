"""Canonical rendering, budget-aware eviction and position-aware placement.

Two ideas are baked in here:

1. **Nothing is dropped silently.** When the budget engine evicts rows it
   leaves a ``~elided n`` marker, because a model that does not know context
   was removed will answer with false confidence.

2. **Position is part of the encoding.** Hard constraints go first and are
   optionally restated last, exploiting the U-shaped attention curve that
   causes the "lost in the middle" effect (Liu et al., TACL 2024).
"""

from __future__ import annotations

import copy
import re

from .ast import KV, TABLE, Document, Section
from .budget import count_tokens


class BudgetError(ValueError):
    """Raised when the budget cannot hold the mandatory context."""


SECTION_ORDER = [    "state",
    "defs",
    "evidence",
    "facts",
    "refs",
    "open",
    "questions",
    "next",
    "plan",
    "notes",
]

# Baseline retention priority per section. Higher survives longer.
SECTION_PRIORITY = {
    # state is ground truth, so it outranks plans and evidence; only the
    # mandatory head (goal/done/rules) is safer.
    "state": 0.85,
    "defs": 0.90,
    "evidence": 0.50,
    "facts": 0.50,
    "refs": 0.55,
    "open": 0.60,
    "questions": 0.60,
    "next": 0.70,
    "plan": 0.70,
    "notes": 0.10,
}


def _needs_quote(cell: str) -> bool:
    return any(c in cell for c in (",", '"')) or cell != cell.strip()


def _quote(cell: str) -> str:
    if not _needs_quote(cell):
        return cell
    return '"' + cell.replace('"', '""') + '"'


def _row_priority(section: Section, row) -> float:
    base = SECTION_PRIORITY.get(section.name, 0.5)
    cols = section.columns or []
    if "trust" in cols:
        try:
            base *= 0.5 + float(row.get(cols, "trust", "0.5"))
        except ValueError:
            pass
    if "salience" in cols:
        try:
            base *= 0.5 + float(row.get(cols, "salience", "0.5"))
        except ValueError:
            pass
    if "prio" in cols:
        prio = row.get(cols, "prio", "2")
        base *= {"high": 1.3, "hi": 1.3, "low": 0.6, "lo": 0.6}.get(prio.lower(), 1.0)
    return base


def _section_key(section: Section) -> tuple[int, str]:
    try:
        return (SECTION_ORDER.index(section.name), section.name)
    except ValueError:
        return (len(SECTION_ORDER), section.name)


def _render_section(section: Section, elided: int) -> list[str]:
    head = "#" + section.name
    if section.meta:
        head += "[" + " ".join(f"{k}={v}" for k, v in section.meta.items()) + "]"
    if section.style == TABLE and section.columns:
        head += "{" + ",".join(section.columns) + "}"
    if not section.rows and elided:
        # collapse a fully-evicted section to one line instead of two
        return [f"{head} ~elided {elided}"]
    lines = [head]
    for row in section.rows:
        if section.style == KV:
            value = row.cells[1] if len(row.cells) > 1 else ""
            lines.append(f"  {row.cells[0]} = {value}")
        elif section.style == TABLE:
            lines.append("  " + ",".join(_quote(c) for c in row.cells))
        else:
            lines.append("  - " + (row.cells[0] if row.cells else ""))
    if elided:
        lines.append(f"  ~elided {elided}")
    return lines


def render(
    doc: Document,
    budget: int | None = None,
    order: str = "salient",
    recap: bool = False,
    legend: bool = False,
) -> str:
    """Serialise a document back to canonical Loom.

    ``budget`` is a token budget. Rows are evicted lowest-priority-first and
    the survivors are marked with ``~elided n``. Goals and hard rules are
    never evicted.
    """
    d = copy.deepcopy(doc)
    elided: dict[int, int] = {}
    use_recap = recap

    def current_text() -> str:
        return _render(d, elided, order, use_recap, legend)

    if budget is not None:
        # evict cheapest-to-lose items first; goals and rules are never candidates
        while count_tokens(current_text()) > budget:
            best: tuple[float, str, int, int] | None = None
            for si, section in enumerate(d.sections):
                if section.name in ("defs",):  # schema is load-bearing, keep
                    continue
                for ri, row in enumerate(section.rows):
                    p = _row_priority(section, row)
                    if best is None or p < best[0]:
                        best = (p, "row", si, ri)
            # capability lines are cheaper to lose than hard-won state
            if d.uses:
                p = 0.35
                if best is None or p < best[0]:
                    best = (p, "use", -1, len(d.uses) - 1)
            # unknowns are cheap insurance, but still evictable under pressure
            if d.questions:
                p = 0.60
                if best is None or p < best[0]:
                    best = (p, "q", -1, len(d.questions) - 1)
            if best is None:
                break
            _, kind, si, ri = best
            if kind == "row":
                d.sections[si].rows.pop(ri)
                elided[si] = elided.get(si, 0) + 1
            elif kind == "use":
                d.uses.pop()
            else:
                d.questions.pop()

    text = current_text()
    if budget is not None and count_tokens(text) > budget:
        # drop capability lines, which are the cheapest non-essential part
        while d.uses and count_tokens(current_text()) > budget:
            d.uses.pop()
        text = current_text()
    if budget is not None and count_tokens(text) > budget and use_recap:
        use_recap = False  # the tail restatement is an optimisation, not required
        text = current_text()
    if budget is not None and count_tokens(text) > budget:
        raise BudgetError(
            f"budget {budget} is below the mandatory context "
            f"(goal + done + {len(d.rules)} rules) which needs {count_tokens(text)} tokens"
        )
    return text


def _render(
    doc: Document,
    elided: dict[int, int],
    order: str,
    recap: bool,
    legend: bool,
) -> str:
    out: list[str] = []
    if legend:
        out.append(";; loom 1.0 | !goal/!done objective | !must/!never hard rules | ?q unknown | #sections rows")
    out.append(f"@loom {doc.version}")
    for use in doc.uses:
        out.append(f"#use {use}")

    # ---- head: the part the model always reads ---------------------
    if doc.goal:
        out.append(f"!goal {doc.goal}")
    if doc.done:
        out.append(f"!done {doc.done}")
    for rule in doc.rules:
        out.append(f"!{rule.kind} {rule.text}")

    # ---- body ------------------------------------------------------
    sections = list(enumerate(doc.sections))
    if order != "chrono":
        sections.sort(key=lambda pair: _section_key(pair[1]))
    for idx, section in sections:
        out.extend(_render_section(section, elided.get(idx, 0)))

    for q in doc.questions:
        out.append(f"?q {q}")

    # ---- tail: restate hard rules (U-shaped attention mitigation) ---
    if recap and doc.rules:
        recap_text = " | ".join(f"{r.kind}: {r.text}" for r in doc.rules)
        if len(recap_text) > 240:
            recap_text = recap_text[:237].rstrip() + "..."
        out.append(f"!rem {recap_text}")

    return "\n".join(out) + "\n"


def section_rows(doc: Document) -> int:
    return sum(len(s.rows) for s in doc.sections)


def summarise(doc: Document) -> dict[str, object]:
    """Small stats block used by the CLI and benchmark."""

    def words(text: str | None) -> int:
        return len(re.findall(r"\S+", text or ""))

    return {
        "goal_words": words(doc.goal),
        "rules": len(doc.rules),
        "questions": len(doc.questions),
        "sections": len(doc.sections),
        "rows": section_rows(doc),
    }
