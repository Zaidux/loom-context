"""English -> Loom (rule-based reference compiler).

This is the *deterministic* half of the translator. It handles the shape that
most agent briefs actually take: headings, wrapped paragraphs, bullets and
key/value blocks.

For free-form prose the right production path is an LLM rewrite pass using the
prompt in ``docs/SPEC.md``. :func:`compile_text` is the fallback, the offline
path, and the round-trip oracle used by the tests.
"""

from __future__ import annotations

import re

from .ast import KV, LIST, TABLE, Document, Row, Rule, Section

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(.+?)\s*$")
_BOLD_ONLY = re.compile(r"^\s{0,3}\*\*(.+?)\*\*\s*:?\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$")
_KV = re.compile(r"^\s*([A-Za-z_][\w .-]{0,40}?)\s*(?:=|:)\s*(.+)$")
_CONFIDENCE = re.compile(r"\s*\((?:confidence|trust)\s*([\d.]+)\)\.?$", re.I)
_SRC = re.compile(r"^([\w./-]+\.\w+:\d+)\s+(?:says|sets|shows|reports)\s+(.*)$", re.I)

# heading keyword -> (target, style); target "goal"/"done"/"rules"/"questions"
# are document-level, everything else is a section.
_HEADINGS: list[tuple[tuple[str, ...], str, str]] = [
    (("objective", "goal", "task", "aim", "mission"), "goal", ""),
    (("definition of done", "acceptance", "success criteria", "done when", "done"), "done", ""),
    (("hard constraint", "constraint", "rule", "requirement", "policy", "guardrail"), "rules", ""),
    (("current state", "state", "status", "context", "environment"), "state", KV),
    (("evidence", "finding", "observation", "source", "data", "result"), "evidence", TABLE),
    (("open question", "unknown", "question", "risk"), "questions", ""),
    (("next", "plan", "step", "todo", "action"), "next", LIST),
    (("note", "background", "misc"), "notes", LIST),
    (("reference", "ref", "link"), "refs", KV),
]

_NEGATIVE = (
    "you must never",
    "you should never",
    "you must not",
    "must never",
    "must not",
    "never",
    "do not",
    "don't",
    "avoid",
)
_POSITIVE = ("you must", "you should", "required to", "need to", "must", "should", "always")


def _classify_heading(text: str) -> tuple[str, str] | None:
    low = text.lower().strip().rstrip(":").strip()
    for keys, target, style in _HEADINGS:
        if any(low == k or low.startswith(k) for k in keys):
            return target, style
    return None


def _add_rule(doc: Document, text: str) -> None:
    text = text.strip().rstrip(".")
    low = text.lower()
    for prefix in _NEGATIVE:
        if low.startswith(prefix):
            doc.rules.append(Rule("never", text[len(prefix):].strip(" :,")))
            return
    for prefix in _POSITIVE:
        if low.startswith(prefix):
            text = text[len(prefix):].strip(" :,")
            break
    doc.rules.append(Rule("must", text))


def _split_confidence(text: str) -> tuple[str, str | None]:
    m = _CONFIDENCE.search(text)
    if not m:
        return text.strip().rstrip("."), None
    return text[: m.start()].strip().rstrip("."), m.group(1)


def _evidence_row(text: str, index: int) -> Row:
    body, trust = _split_confidence(text)
    src = ""
    m = _SRC.match(body)
    if m:
        src, body = m.group(1), m.group(2)
    if trust is None:
        return Row([f"e{index}", body])
    return Row([f"e{index}", src, trust, body])


def compile_text(source: str) -> Document:
    """Compile a heading/bullet brief into a :class:`Document`."""
    doc = Document()
    current: Section | None = None
    mode = "notes"
    buf: list[str] = []
    evidence: list[str] = []
    state_rows: list[list[str]] = []

    def flush() -> None:
        nonlocal buf
        text = " ".join(part.strip() for part in buf if part.strip()).strip()
        buf = []
        if not text:
            return
        if mode == "goal":
            doc.goal = text if not doc.goal else f"{doc.goal} {text}"
        elif mode == "done":
            doc.done = text if not doc.done else f"{doc.done} {text}"
        elif mode == "rules":
            _add_rule(doc, text)
        elif mode == "questions":
            doc.questions.append(text)
        elif mode == "evidence":
            evidence.append(text)
        elif mode == "state":
            kv = _KV.match(text)
            if kv:
                key = re.sub(r"\s+", "_", kv.group(1).strip().lower())
                state_rows.append([key, kv.group(2).strip()])
        else:
            target = current or doc.ensure("notes", LIST)
            target.rows.append(Row([text]))

    for raw in source.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith((";;", "//")):
            flush()
            continue

        # ---- already-Loom pragmas pass straight through --------------
        if stripped.startswith(("@loom", "!goal", "!done", "!must", "!never", "?q", "#use")):
            flush()
            if stripped.startswith("@loom"):
                parts = stripped.split()
                doc.version = parts[1] if len(parts) > 1 else doc.version
            elif stripped.startswith("!goal"):
                doc.goal = stripped[5:].strip()
            elif stripped.startswith("!done"):
                doc.done = stripped[5:].strip()
            elif stripped.startswith("!must"):
                doc.rules.append(Rule("must", stripped[5:].strip()))
            elif stripped.startswith("!never"):
                doc.rules.append(Rule("never", stripped[6:].strip()))
            elif stripped.startswith("?q"):
                doc.questions.append(stripped[2:].strip())
            elif stripped.startswith("#use"):
                doc.uses.append(stripped[4:].strip())
            continue

        # ---- headings ------------------------------------------------
        heading = _HEADING.match(line) or _BOLD_ONLY.match(line)
        if heading and not _BULLET.match(line):
            flush()
            target = _classify_heading(heading.group(1))
            if not target:
                mode, current = "notes", doc.ensure("notes", LIST)
                continue
            name, style = target
            if name in ("goal", "done", "rules", "questions"):
                mode, current = name, None
            else:
                mode, current = name, doc.ensure(name, style or LIST)
            continue

        # ---- bullets -------------------------------------------------
        bullet = _BULLET.match(line)
        if bullet:
            flush()
            buf.append(bullet.group(1))
            continue

        # ---- "Objective: ..." inline labels --------------------------
        if not buf and mode != "evidence":
            inline = _KV.match(stripped)
            if inline:
                target = _classify_heading(inline.group(1))
                if target and target[0] in ("goal", "done", "rules"):
                    flush()
                    if target[0] == "goal":
                        doc.goal = inline.group(2).strip()
                    elif target[0] == "done":
                        doc.done = inline.group(2).strip()
                    else:
                        _add_rule(doc, inline.group(2).strip())
                    continue

        # ---- prose: may be a wrapped continuation --------------------
        buf.append(stripped)

    flush()

    # drop placeholder sections created by headings whose rows were buffered
    doc.sections = [s for s in doc.sections if s.rows]

    if evidence:
        parsed = [_evidence_row(text, i + 1) for i, text in enumerate(evidence)]
        has_trust = all(len(r.cells) == 4 for r in parsed)
        section = Section(name="evidence", style=TABLE, columns=["id", "src", "trust", "text"])
        if not has_trust:
            section = Section(name="evidence", style=LIST, columns=None)
            parsed = [Row([_split_confidence(t)[0]]) for t in evidence]
        section.rows = parsed
        doc.sections.insert(0, section)

    if state_rows:
        doc.sections.insert(0, Section(name="state", style=KV, rows=[Row(r) for r in state_rows]))

    return doc
