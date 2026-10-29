"""Literal-fidelity checks shared by the benchmarks.

Compression without fidelity is just data loss. These expressions extract the
facts that must never be silently lost: numbers, paths, identifiers and quoted
strings. This is a *necessary* check, not a sufficient one — it cannot see a
dropped negation or a weakened modality, which is why the downstream protocol
in ``docs/EVALS.md`` still matters.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ms|s|min|h|rps|%|x)?\b")
_PATH = re.compile(r"\b[\w./-]+/[\w./-]+\b|\b\w+\.(?:py|ts|js|go|rs|yaml|toml|json|md)\b")
_IDENT = re.compile(r"(?<!`)`([^`\n]+)`(?!`)|\b([A-Z][A-Z0-9_]{3,})\b")
_QUOTED = re.compile(r'"([^"]{4,})"')


def facts(text: str) -> set[str]:
    """Extract literals that must not be silently lost."""
    out: set[str] = set()
    out |= {m.group(0).strip().lower() for m in _NUMBER.finditer(text)}
    out |= {m.group(0).strip().lower() for m in _PATH.finditer(text) if len(m.group(0)) > 4}
    for m in _IDENT.finditer(text):
        out.add((m.group(1) or m.group(2) or "").strip().lower())
    out |= {m.group(1).strip().lower() for m in _QUOTED.finditer(text)}
    return {f for f in out if f and len(f) > 2}


def coverage(source: str, target: str) -> tuple[float, list[str]]:
    """Share of ``source`` literals present in ``target``, plus what is missing."""
    wanted = facts(source)
    if not wanted:
        return 1.0, []
    flat = re.sub(r"\s+", " ", target.lower())
    missing = sorted(f for f in wanted if f not in flat)
    return (len(wanted) - len(missing)) / len(wanted), missing
