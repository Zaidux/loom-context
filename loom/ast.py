"""Core data model for Loom.

Loom is a *pragmatic* context language: it does not merely compress text, it
records the role each piece of context plays (goal, hard rule, evidence,
unknown, next action) so that a renderer can place, rank or drop it safely.

The AST is deliberately tiny and JSON-serialisable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VERSION = "1.0"

# Row styles a section may use.
KV = "kv"        # key = value          (mutable state, definitions, refs)
LIST = "list"    # - item               (open questions, plans, notes)
TABLE = "table"  # id,src,trust,text    (uniform evidence / facts)

# Rule kinds, ordered by how hard they are.
MUST = "must"
NEVER = "never"


@dataclass
class Rule:
    """A hard constraint. Rules are never evicted by the budget engine."""

    kind: str
    text: str

    def to_json(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text}


@dataclass
class Row:
    """One line of a section, kept as raw cells so Loom stays lossless."""

    cells: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def get(self, columns: list[str], name: str, default: str = "") -> str:
        if name not in columns:
            return default
        i = columns.index(name)
        return self.cells[i] if i < len(self.cells) else default

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"cells": self.cells}
        if self.meta:
            out["meta"] = self.meta
        return out


@dataclass
class Section:
    """A named group of rows.

    ``meta`` holds render hints and provenance, e.g. ``src=tool:bash t=12``.
    ``columns`` is set for table sections only.
    """

    name: str
    style: str = LIST
    meta: dict[str, str] = field(default_factory=dict)
    columns: list[str] | None = None
    rows: list[Row] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "style": self.style}
        if self.columns:
            out["columns"] = self.columns
        if self.meta:
            out["meta"] = self.meta
        out["rows"] = [r.to_json() for r in self.rows]
        return out


@dataclass
class Document:
    """A complete Loom context object."""

    version: str = VERSION
    goal: str | None = None
    done: str | None = None
    rules: list[Rule] = field(default_factory=list)
    uses: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)

    # -- convenience -------------------------------------------------
    def section(self, name: str) -> Section | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def ensure(self, name: str, style: str = LIST) -> Section:
        found = self.section(name)
        if found is not None:
            return found
        s = Section(name=name, style=style)
        self.sections.append(s)
        return s

    def all_rules(self) -> list[str]:
        return [f"{r.kind}: {r.text}" for r in self.rules]

    def is_empty(self) -> bool:
        return not (
            self.goal
            or self.done
            or self.rules
            or self.questions
            or any(s.rows for s in self.sections)
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal,
            "done": self.done,
            "rules": [r.to_json() for r in self.rules],
            "uses": self.uses,
            "questions": self.questions,
            "sections": [s.to_json() for s in self.sections],
        }
