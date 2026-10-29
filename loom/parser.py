"""Line-oriented parser for Loom.

The grammar is intentionally line-oriented and small. Every construct is
recognisable from its first two characters, which keeps the syntax cheap to
emit for a model and cheap to recover from when a model makes a small mistake.

Design constraints (from the eval literature):
  * no deep nesting  - nesting is where compact formats lose accuracy
  * no significant punctuation beyond `! ? # = ,`
  * one row per line - truncation degrades gracefully
"""

from __future__ import annotations

import re

from .ast import (
    KV,
    LIST,
    MUST,
    NEVER,
    TABLE,
    Document,
    Row,
    Rule,
    Section,
    VERSION,
)

__all__ = ["LoomSyntaxError", "parse", "parse_meta", "split_cells"]


class LoomSyntaxError(ValueError):
    """Raised with a line number so agents can self-repair."""

    def __init__(self, line: int, message: str):
        self.line = line
        super().__init__(f"line {line}: {message}")


_HEADER = re.compile(
    r"^#([A-Za-z][\w-]*)\s*(?:\[([^\]]*)\])?\s*(?:\{([^}]*)\})?\s*(?:~elided\s+\d+)?\s*$"
)
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_KV = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*=\s*(.*)$")

# Sections that are conventionally key/value.
_KV_SECTIONS = {"state", "defs", "refs", "def", "vars", "env"}
_LIST_SECTIONS = {"open", "next", "notes", "plan", "todo", "risks"}


def split_cells(text: str) -> list[str]:
    """Split a comma separated row, honouring quotes and escaped quotes."""
    cells: list[str] = []
    buf: list[str] = []
    quoted = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if quoted and i + 1 < len(text) and text[i + 1] == '"':
                buf.append('"')
                i += 2
                continue
            quoted = not quoted
        elif ch == "," and not quoted:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def parse_meta(text: str | None) -> dict[str, str]:
    """Parse ``src=tool:bash t=12 trust=0.9`` style metadata."""
    meta: dict[str, str] = {}
    if not text:
        return meta
    for part in split_cells(text):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            meta[k.strip()] = v.strip().strip('"')
        else:
            meta[part.strip()] = "true"
    return meta


def parse(source: str) -> Document:
    """Parse Loom source into a :class:`Document`."""
    doc = Document(version=VERSION)
    current: Section | None = None
    seen_header = False

    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()

        # comments are legal anywhere and cost nothing when stripped
        if stripped.startswith(";;") or stripped.startswith("//"):
            continue

        # ---- document header -------------------------------------
        if stripped.startswith("@loom"):
            parts = stripped.split()
            doc.version = parts[1] if len(parts) > 1 else VERSION
            seen_header = True
            continue

        # ---- top-level pragmas -----------------------------------
        if stripped.startswith("!") or stripped.startswith("?q") or stripped.startswith("#use"):
            current = None  # a pragma closes the open section

        if stripped.startswith("!goal"):
            doc.goal = stripped[len("!goal"):].strip()
            continue
        if stripped.startswith("!done"):
            doc.done = stripped[len("!done"):].strip()
            continue
        if stripped.startswith("!must"):
            doc.rules.append(Rule(MUST, stripped[len("!must"):].strip()))
            continue
        if stripped.startswith("!never"):
            doc.rules.append(Rule(NEVER, stripped[len("!never"):].strip()))
            continue
        if stripped.startswith("?q"):
            doc.questions.append(stripped[2:].strip())
            continue
        if stripped.startswith("#use"):
            doc.uses.append(stripped[len("#use"):].strip())
            continue

        # ---- section header --------------------------------------
        header = _HEADER.match(stripped)
        if header and not line.startswith((" ", "\t")):
            name, meta_raw, cols_raw = header.groups()
            columns = [c.strip() for c in split_cells(cols_raw)] if cols_raw else None
            style = TABLE if columns else LIST
            if name.lower() in _KV_SECTIONS:
                style = KV
            if name.lower() in _LIST_SECTIONS and not columns:
                style = LIST
            current = Section(name=name, style=style, meta=parse_meta(meta_raw), columns=columns)
            doc.sections.append(current)
            continue

        # ---- rows ------------------------------------------------
        if current is None:
            raise LoomSyntaxError(lineno, f"content outside a section: {stripped[:40]!r}")

        # Eviction markers are metadata, not rows: a renderer that dropped
        # rows appends `~elided N`, and re-parsing must not treat it as data.
        if stripped.startswith("~elided"):
            continue

        if current.style == KV:
            m = _KV.match(line)
            if not m:
                raise LoomSyntaxError(lineno, "state rows must be `key = value`")
            current.rows.append(Row([m.group(1), m.group(2).strip()]))
            continue

        if current.style == TABLE:
            cells = split_cells(stripped)
            if len(cells) != len(current.columns or []):
                raise LoomSyntaxError(
                    lineno,
                    f"expected {len(current.columns or [])} cells for {{{','.join(current.columns or [])}}}, got {len(cells)}",
                )
            current.rows.append(Row(cells))
            continue

        # list style: allow bullets or bare lines
        bullet = _BULLET.match(line)
        text = bullet.group(1) if bullet else stripped
        # strip an optional leading ordinal (`1. foo`)
        text = re.sub(r"^\d+[.)]\s+", "", text)
        current.rows.append(Row([text]))

    if not seen_header:
        # tolerate documents without the version line; agents drop it a lot
        pass
    return doc
