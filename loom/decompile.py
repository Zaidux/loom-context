"""Loom -> English.

The decompiler is the half of the translator that proves the language is a
*notation*, not a lossy compression: every construct has a plain-English
expansion, and the expansion keeps the structure (so it is still skimmable).

Output style is deliberately flat prose + lists, because that is what humans
review and what every model has seen in training.
"""

from __future__ import annotations

from .ast import KV, TABLE, Document

_LABELS = {
    "state": "Current state",
    "defs": "Definitions",
    "evidence": "Evidence",
    "facts": "Facts",
    "refs": "References",
    "open": "Open questions",
    "questions": "Open questions",
    "next": "Next actions",
    "plan": "Plan",
    "notes": "Notes",
    "risks": "Risks",
}


def _label(name: str) -> str:
    return _LABELS.get(name.lower(), name.replace("-", " ").replace("_", " ").capitalize())


def decompile(doc: Document, prose: bool = True) -> str:
    """Render a document as a plain-English brief."""
    out: list[str] = []

    if doc.goal:
        out.append(f"Objective: {doc.goal}")
    if doc.done:
        out.append(f"Definition of done: {doc.done}")

    if doc.rules:
        out.append("Hard constraints:")
        for rule in doc.rules:
            verb = "You must" if rule.kind == "must" else "You must never"
            out.append(f"- {verb} {rule.text}")

    if doc.uses:
        out.append("Available capabilities: " + ", ".join(doc.uses) + ".")

    for section in doc.sections:
        if not section.rows:
            continue
        label = _label(section.name)
        meta = ""
        if section.meta:
            meta = " (" + ", ".join(f"{k}={v}" for k, v in section.meta.items()) + ")"
        out.append(f"{label}{meta}:")

        if section.style == KV:
            for row in section.rows:
                key = row.cells[0]
                value = row.cells[1] if len(row.cells) > 1 else ""
                out.append(f"- {key} is {value}.")
        elif section.style == TABLE and section.columns:
            for row in section.rows:
                out.append("- " + _decompile_row(section.columns, row))
        else:
            for row in section.rows:
                text = row.cells[0] if row.cells else ""
                out.append(f"- {text}")

    if doc.questions:
        out.append("Unknowns to resolve before acting:")
        for q in doc.questions:
            out.append(f"- {q}")

    if not prose:
        return "\n".join(out) + "\n"
    return "\n".join(out) + "\n"


def _decompile_row(columns: list[str], row) -> str:
    parts: list[str] = []
    for i, col in enumerate(columns):
        value = row.cells[i] if i < len(row.cells) else ""
        if not value:
            continue
        if col in ("text", "desc", "description", "summary", "value"):
            parts.insert(0, value)
        elif col in ("trust", "confidence"):
            parts.append(f"confidence {value}")
        elif col in ("salience", "prio", "priority"):
            parts.append(f"priority {value}")
        elif col == "id":
            continue
        else:
            parts.append(f"{col}: {value}")
    return "; ".join(parts) + "."
