"""Encode real agent sessions as Loom.

Input is the Riciplay session corpus format:

    {"id", "source_file", "status", "workspace", "n_messages",
     "intents": [...], "tool_calls": [{"name", "args"}],
     "incidents": [...], "rerequests": [...]}

The encoder is deliberately mechanical: every tool call, task and incident
becomes a row, so nothing is summarised away. The compression comes from
(a) removing per-call JSON scaffolding, (b) collapsing duplicate calls, and
(c) projecting repeated `tasks` payloads into one state table.

Tool output strings are normalised to a single line (whitespace collapsed),
because Loom rows are line-oriented. That is the only lossy step here, and the
session harness measures it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .ast import KV, LIST, TABLE, Document, Row, Section

_ARG_ORDER = ("command", "url", "path", "query", "pattern", "target")


def _one_line(text: Any, limit: int | None = None) -> str:
    s = str(text)
    s = s.replace("\r", " ").replace("\n", " ; ").replace("\t", " ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "..."
    return s


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def call_arg(call: dict) -> str:
    """Render one tool call's arguments as a single dense string."""
    args = call.get("args") or {}
    if not isinstance(args, dict):
        return _one_line(args)
    for key in _ARG_ORDER:
        if key in args and isinstance(args[key], (str, int, float)):
            value = _one_line(args[key])
            if key == "url":
                prefix = args.get("method") or args.get("action")
                if prefix:
                    value = f"{prefix} {value}"
                if "body" in args:
                    value += " body=" + _compact(args["body"])
                if "steps" in args and args["steps"]:
                    value += " steps=" + _compact(args["steps"])
            # keep scalar side-arguments (timeouts, limits, flags) so the row
            # remains faithful to the call
            extras = [
                f"{k}={_compact(v)}"
                for k, v in sorted(args.items())
                if k not in (key, "method", "action", "body", "steps")
                and isinstance(v, (str, int, float, bool))
            ]
            if extras:
                value += " " + " ".join(extras)
            return value
    if "steps" in args:
        return "steps=" + _compact(args["steps"])
    return _compact(args)


def _task_rows(record: dict) -> list[Row]:
    """Collapse every `tasks` payload into one de-duplicated table."""
    latest: dict[str, bool] = {}
    order: list[str] = []
    for call in record.get("tool_calls", []):
        if call.get("name") != "tasks":
            continue
        args = call.get("args") or {}
        for item in args.get("items", []) or []:
            if isinstance(item, dict):
                text = _one_line(item.get("text", ""))
                done = bool(item.get("done", False))
            else:
                text, done = _one_line(item), False
            if not text:
                continue
            if text not in latest:
                order.append(text)
            latest[text] = done  # later calls carry the newer status
    return [Row([t, "done" if latest[t] else "todo"]) for t in order]


def from_session(record: dict) -> Document:
    """Project one session record into a Loom document."""
    doc = Document()
    intents = [i for i in (record.get("intents") or []) if str(i).strip()]
    doc.goal = _one_line(intents[0]) if intents else f"Continue session {record.get('id', '?')}"
    if len(intents) > 1:
        doc.questions.extend(_one_line(i) for i in intents[1:])

    state = doc.ensure("state", KV)
    state.rows = [
        Row(["session", str(record.get("id", ""))]),
        Row(["source", _one_line(record.get("source_file", ""))]),
        Row(["workspace", _one_line(record.get("workspace", ""))]),
        Row(["status", str(record.get("status", ""))]),
        Row(["messages", str(record.get("n_messages", 0))]),
        Row(["tool_calls", str(len(record.get("tool_calls") or []))]),
    ]

    tasks = _task_rows(record)
    if tasks:
        doc.sections.append(Section(name="tasks", style=TABLE, columns=["text", "state"], rows=tasks))

    calls = [
        Row([str(c.get("name", "")), call_arg(c)])
        for c in record.get("tool_calls", [])
        if isinstance(c, dict) and c.get("name") != "tasks"
    ]
    if calls:
        doc.sections.append(Section(name="calls", style=TABLE, columns=["tool", "arg"], rows=calls))

    incidents = []
    for i, inc in enumerate(record.get("incidents") or [], 1):
        if not isinstance(inc, dict):
            incidents.append(Row([f"i{i}", "", "", _one_line(inc)]))
            continue
        incidents.append(
            Row(
                [
                    f"i{i}",
                    str(inc.get("failing_tool", "")),
                    str(inc.get("failure_signature", "")),
                    _one_line(inc.get("failure_msg") or inc.get("failure_snippet") or ""),
                ]
            )
        )
    if incidents:
        doc.sections.append(
            Section(
                name="incidents",
                style=TABLE,
                columns=["id", "tool", "sig", "msg"],
                rows=incidents,
            )
        )

    if record.get("rerequests"):
        doc.sections.append(
            Section(
                name="notes",
                style=LIST,
                rows=[Row(["operator: " + _one_line(r if not isinstance(r, dict) else r.get("text", ""))])
                      for r in record["rerequests"]],
            )
        )
    return doc


def raw_json(record: dict) -> str:
    """The baseline an agent sees from a naive session dump."""
    return json.dumps(record, indent=2, ensure_ascii=False)


def compact_json(record: dict) -> str:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def load_corpus(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
