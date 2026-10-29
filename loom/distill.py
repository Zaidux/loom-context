"""Lossy distillation: free-form prose -> Loom.

Unlike :mod:`loom.compile_`, which preserves the source sentence for sentence,
this pass is *lossy by design*. It removes filler, abbreviates units, drops
articles, classifies each sentence by the role it plays, and collapses
near-duplicate statements.

This is the component that actually moves the token count, and it is the
component most likely to lose something important. It is therefore opt-in,
every removal is counted, and the CLI prints the counts so the caller can
decide whether the ratio is acceptable.

The rule set is deliberately conservative: it stays inside English (no symbol
substitution for arbitrary statements) because telegraphic English remains
in-distribution for every model, while invented notation does not. Benchmarks
of compact structural formats (TRON, TOON) show 9-14pp accuracy drops; the
lesson is to remove *words*, not to invent *syntax*.
"""

from __future__ import annotations

import re

from .ast import KV, LIST, TABLE, Document, Row, Rule, Section

# filler that carries no task signal
_FILLER = [
    r"\bplease note that\b",
    r"\bnote that\b",
    r"\bmake sure that\b",
    r"\bmake sure\b",
    r"\bin order to\b",
    r"\bthe fact that\b",
    r"\bit is important that\b",
    r"\bit is worth noting that\b",
    r"\bas you can see\b",
    r"\bfor the purpose of\b",
    r"\bwith respect to\b",
    r"\bin terms of\b",
    r"\bat this point in time\b",
    r"\bdue to the fact that\b",
    r"\bbasically\b",
    r"\bactually\b",
    r"\bsimply\b",
    r"\bquite\b",
    r"\bvery\b",
    r"\breally\b",
    r"\bjust\b",
]

_ABBREV = [
    (r"\brequests? per second\b", "rps"),
    (r"\bmilliseconds?\b", "ms"),
    (r"\bseconds?\b", "s"),
    (r"\bminutes?\b", "min"),
    (r"\bpercent\b", "%"),
    (r"\bat least\b", ">="),
    (r"\bat most\b", "<="),
    (r"\bgreater than\b", ">"),
    (r"\bless than\b", "<"),
]

_ARTICLES = re.compile(r"\b(a|an|the)\s+", re.I)
_SPACING = [
    (re.compile(r"(\d)\s+%"), r"\1%"),
    (re.compile(r"(>=|<=|=|>|<)\s+"), r"\1"),
    (re.compile(r"\brps\b", re.I), "rps"),
]

_GOAL_CUES = ("goal", "objective", "we need to", "we want to", "the task is", "your task")
_DONE_CUES = ("done when", "definition of done", "success criteria", "acceptance", "complete when")
_RULE_START = ("must", "never", "do not", "don't", "avoid", "not allowed", "prohibited", "you must", "we must", "should", "we should", "you should")
_QUESTION_STARTS = (
    "does", "do", "is", "are", "can", "should", "what", "why", "how", "when", "which", "who",
)
_ACTION_STARTS = (
    "add", "check", "run", "verify", "enable", "disable", "raise", "lower", "profile",
    "document", "update", "remove", "delete", "write", "test", "investigate", "confirm",
    "compare", "measure", "migrate", "implement", "fix", "build", "refactor", "split",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_KV = re.compile(r"^\s*([A-Za-z_][\w .-]{0,40}?)\s*(?:=|:)\s*(.+)$")
_CONF = re.compile(r"\s*\((?:confidence|trust)\s*([\d.]+)\)", re.I)
_SRC = re.compile(r"\b([\w./-]+\.\w+:\d+)\b")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*$")
_NARRATION = re.compile(
    r"^(okay so|alright|so anyway|first thing i did|the first thing i did|"
    r"i (ran|looked|checked|did|started|went|spent|have been|'ve been)|"
    r"then i |after that i |let me |here is |here's |and here is |"
    r"just so you have|for reference|i want to be)\b",
    re.I,
)
_EPISTEMIC = re.compile(
    r"^(i|we)\s+(think|believe|suspect|guess|feel|would suggest|suggest|"
    r"want to point out|want to note|want to mention|want to be clear)\s*(that\s+)?",
    re.I,
)
_Q_PREFIX = re.compile(r"^.*\b(open questions?|unknowns?|questions?)\b.*?:\s*", re.I)
_BULLET = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$")

_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("objective", "goal", "task", "aim", "mission"), "goal"),
    (("definition of done", "acceptance", "success criteria", "done"), "done"),
    (("constraint", "rule", "requirement", "policy", "guardrail"), "rule"),
    (("open question", "unknown", "question", "risk"), "question"),
    (("current state", "state", "status", "context", "environment"), "state"),
    (("evidence", "finding", "observation", "source", "data", "result"), "evidence"),
    (("next", "plan", "step", "todo", "action"), "next"),
    (("note", "background", "misc"), "notes"),
]


def _strip_filler(text: str) -> str:
    for pat in _FILLER:
        text = re.sub(pat, " ", text, flags=re.I)
    return text


def terse(text: str, drop_articles: bool = True) -> str:
    """Conservative telegraphic compression of one statement."""
    text = _strip_filler(text).strip()
    for pat, rep in _ABBREV:
        text = re.sub(pat, rep, text, flags=re.I)
    if drop_articles:
        text = _ARTICLES.sub("", text)
    text = re.sub(r"\bthat\b\s+", "", text, flags=re.I)
    for pat, rep in _SPACING:
        text = pat.sub(rep, text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = text.strip(" ,;")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def _content_words(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in",
        "on", "for", "and", "or", "it", "this", "that", "with", "as", "at",
        "by", "from", "we", "you", "our", "your", "all", "any", "not",
    }
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in stop and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _heading_hint(text: str) -> str | None:
    low = text.lower().strip().rstrip(":")
    for keys, target in _HINTS:
        if any(low == k or low.startswith(k) for k in keys):
            return target
    return None


def _blocks(text: str) -> list[tuple[str, str]]:
    """Split into (kind, text) blocks, joining wrapped lines first.

    Wrapped prose is the single biggest cause of bad sentence splitting, so
    paragraphs and bullets are reassembled before anything else happens.
    """
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    buf_kind = "para"
    fence = False

    def flush() -> None:
        nonlocal buf
        if buf:
            sep = "\n" if buf_kind == "verbatim" else " "
            out.append((buf_kind, sep.join(part.strip() for part in buf)))
            buf = []

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```") or line.startswith("~~~"):
            flush()
            fence = not fence
            buf_kind = "verbatim" if fence else "para"
            continue
        if fence:
            buf.append(raw)
            continue
        if not line or line.startswith((";;", "//")):
            flush()
            buf_kind = "para"
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            out.append(("heading", heading.group(1)))
            buf_kind = "para"
            continue
        bullet = _BULLET.match(line)
        if bullet:
            flush()
            buf_kind = "bullet"
            buf.append(bullet.group(1))
            continue
        # 4-space indentation is a markdown code block: verbatim tool output.
        # 2-space indentation is a wrapped continuation and must stay prose.
        if raw.startswith(("    ", "\t")):
            if buf_kind != "verbatim":
                flush()
                buf_kind = "verbatim"
            buf.append(line)
            continue
        buf.append(line)
    flush()
    return out


def _classify(sentence: str) -> str:
    low = sentence.lower().strip()
    if sentence.rstrip().endswith("?"):
        return "question"
    if any(low.startswith(c) or f" {c} " in f" {low} " for c in _DONE_CUES):
        return "done"
    if any(low.startswith(c) for c in _RULE_START) or " must " in low or " is required" in low:
        return "rule"
    if any(low.startswith(c) for c in _GOAL_CUES):
        return "goal"
    if _KV.match(sentence) and len(sentence.split()) <= 8 and low.count(":") <= 1:
        return "state"
    first = low.split()[0] if low.split() else ""
    if first and any(re.match(rf"^{a}\b", low) for a in _ACTION_STARTS):
        return "next"
    if re.search(r"\d", sentence) or _SRC.search(sentence) or any(
        w in low for w in ("error", "observed", "found", "result", "returned", "measured")
    ):
        return "evidence"
    return "notes"


def _as_rule(text: str) -> Rule:
    low = text.lower()
    for cue in ("never", "do not", "don't", "must not", "avoid", "prohibited", "not allowed"):
        idx = low.find(cue)
        if idx != -1:
            return Rule("never", text[idx + len(cue):].strip(" :,").rstrip("."))
    if " must " in low:
        left, right = text.split(" must ", 1)
        body = (left.strip() + " " + right.strip()).rstrip(".")
        body = re.sub(r"^(we|you|they|it)\s+", "", body, flags=re.I)
        return Rule("must", body)
    idx = low.find("must")
    body = text[idx + 4:].strip(" :,").rstrip(".") if idx != -1 else text.rstrip(".")
    return Rule("must", body)


def distill(text: str, terse_output: bool = True, similarity: float = 0.85) -> tuple[Document, dict]:
    """Distil free-form prose into a Loom document.

    Returns the document and a report of what was removed, so callers can
    audit the compression instead of trusting it.
    """
    doc = Document()
    rules: list[Rule] = []
    sections: dict[str, list[str]] = {"state": [], "evidence": [], "next": [], "notes": []}
    seen: list[set[str]] = []
    report = {"blocks": 0, "sentences": 0, "kept": 0, "duplicates": 0, "questions": 0}
    hint: str | None = None

    for kind, block in _blocks(text):
        report["blocks"] += 1
        if kind == "heading":
            hint = _heading_hint(block)
            continue

        if kind == "verbatim":
            clean = re.sub(r"\s*\n\s*", " ", block).strip()
            if clean:
                sections["evidence"].append(clean)
                report["verbatim"] = report.get("verbatim", 0) + 1
            continue

        for sent in _SENTENCE_SPLIT.split(block):
            sent = re.sub(r"^\*\*(.+?)\*\*\s*[:.-]?\s*", r"\1: ", sent.strip())
            if not sent or not re.search(r"[A-Za-z0-9]", sent):
                continue
            report["sentences"] += 1
            sent = _EPISTEMIC.sub("", sent)
            sent = _Q_PREFIX.sub("", sent)
            if _NARRATION.match(sent):
                report["noise"] = report.get("noise", 0) + 1
                continue

            conf = _CONF.search(sent)
            body = _CONF.sub("", sent).strip()
            role = hint or _classify(body)

            words = _content_words(body)
            if any(_jaccard(words, prev) >= similarity for prev in seen):
                report["duplicates"] += 1
                continue
            seen.append(words)

            clean = terse(body) if terse_output else body.strip()
            if not clean:
                continue
            if role in ("notes", "evidence") and len(_content_words(clean)) < 3:
                report["noise"] = report.get("noise", 0) + 1
                continue
            report["kept"] += 1

            if role == "goal":
                doc.goal = clean if not doc.goal else f"{doc.goal} {clean}"
            elif role == "done":
                doc.done = clean if not doc.done else f"{doc.done} {clean}"
            elif role == "rule":
                rules.append(_as_rule(clean))
            elif role == "question":
                doc.questions.append(clean)
                report["questions"] += 1
            elif role == "state":
                m = _KV.match(body)
                if m:
                    key = re.sub(r"\s+", "_", m.group(1).strip().lower())
                    sections["state"].append(key + "=" + m.group(2).strip())
            else:
                sections[role].append(clean + (f" (trust {conf.group(1)})" if conf else ""))

    doc.rules = rules
    if sections["state"]:
        doc.sections.append(
            Section(name="state", style=KV, rows=[Row(s.split("=", 1)) for s in sections["state"]])
        )
    if sections["evidence"]:
        rows = []
        for i, item in enumerate(sections["evidence"], 1):
            m = re.search(r"\s*\(trust ([\d.]+)\)$", item)
            if m:
                item = item[: m.start()]
            rows.append(Row([f"e{i}", m.group(1) if m else "", item]))
        doc.sections.append(
            Section(name="evidence", style=TABLE, columns=["id", "trust", "text"], rows=rows)
        )
    if sections["next"]:
        doc.sections.append(
            Section(name="next", style=LIST, rows=[Row([s]) for s in sections["next"]])
        )
    if sections["notes"]:
        doc.sections.append(
            Section(name="notes", style=LIST, rows=[Row([s]) for s in sections["notes"]])
        )

    from .ops import dedupe

    doc, removed = dedupe(doc)
    report["duplicates"] += removed
    # renumber evidence ids after dedupe so ids stay dense
    ev = doc.section("evidence")
    if ev and ev.columns and "id" in ev.columns:
        i = ev.columns.index("id")
        for n, row in enumerate(ev.rows, 1):
            row.cells[i] = f"e{n}"
    report["rules"] = len(rules)
    return doc, report
