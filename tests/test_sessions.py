"""Tests for the real-session encoder.

The local Riciplay corpus lives outside this repository, so tests that need it
skip when it is absent. The synthetic records below pin the encoding contract
without depending on anyone's private data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom import count_tokens, parse, render
from loom.session import call_arg, compact_json, from_session, load_corpus, raw_json

CORPUS = Path("/root/projects/riciplay-bench/corpus/sessions_corpus.jsonl")

RECORD = {
    "id": "session-test",
    "source_file": "abc.json",
    "status": "running",
    "workspace": "/tmp/ws",
    "n_messages": 12,
    "intents": ["Recon target-a.example", "Stop after the first finding"],
    "tool_calls": [
        {"name": "read", "args": {"path": "RULES.md"}},
        {"name": "bash", "args": {"command": "ls -la\npwd", "timeout": 120}},
        {
            "name": "tasks",
            "args": {
                "items": [
                    {"text": "Recon", "done": False},
                    {"text": "Triage", "done": False},
                ]
            },
        },
        {
            "name": "tasks",
            "args": {"items": [{"text": "Recon", "done": True}]},
        },
        {
            "name": "probe_endpoint",
            "args": {"method": "POST", "url": "https://a.example/x", "body": {"a": 1}},
        },
        {"name": "bash", "args": {"command": "ls -la\npwd", "timeout": 120}},
    ],
    "incidents": [
        {
            "failing_tool": "bash",
            "failure_signature": "not_found",
            "failure_msg": "subfinder: command not found",
        }
    ],
    "rerequests": ["keep going"],
}


def test_goal_and_secondary_intent():
    doc = from_session(RECORD)
    assert doc.goal == "Recon target-a.example"
    assert doc.questions == ["Stop after the first finding"]


def test_state_is_populated_for_every_field():
    doc = from_session(RECORD)
    state = {row.cells[0]: row.cells[1] for row in doc.section("state").rows}
    assert state["session"] == "session-test"
    assert state["source"] == "abc.json"
    assert state["workspace"] == "/tmp/ws"
    assert state["status"] == "running"
    assert state["messages"] == "12"
    assert state["tool_calls"] == "6"


def test_tasks_collapse_to_one_row_per_text_with_latest_state():
    doc = from_session(RECORD)
    rows = doc.section("tasks").rows
    assert [r.cells for r in rows] == [["Recon", "done"], ["Triage", "todo"]]


def test_calls_exclude_tasks_and_keep_every_invocation():
    doc = from_session(RECORD)
    rows = doc.section("calls").rows
    # 6 calls minus the 2 `tasks` calls (duplicate bash calls are preserved here;
    # dedupe is an explicit opt-in op, not a silent encoder decision)
    assert len(rows) == 4
    assert [r.cells[0] for r in rows] == ["read", "bash", "probe_endpoint", "bash"]


def test_duplicate_calls_are_removable_by_dedupe():
    from loom import dedupe

    doc = from_session(RECORD)
    doc, removed = dedupe(doc)
    assert removed >= 1
    assert len(doc.section("calls").rows) == 3


def test_multiline_arguments_stay_on_one_line():
    doc = from_session(RECORD)
    for row in doc.section("calls").rows:
        assert "\n" not in row.cells[1]
    bash = doc.section("calls").rows[1].cells[1]
    assert "ls -la ; pwd" in bash
    assert "timeout=120" in bash


def test_url_carries_method_and_body():
    arg = call_arg(
        {"name": "probe_endpoint", "args": {"method": "POST", "url": "https://a/x", "body": {"a": 1}}}
    )
    assert arg.startswith("POST https://a/x")
    assert 'body={"a":1}' in arg


def test_incidents_and_rerequests_are_preserved():
    doc = from_session(RECORD)
    inc = doc.section("incidents").rows
    assert [c for c in inc[0].cells] == [
        "i1",
        "bash",
        "not_found",
        "subfinder: command not found",
    ]
    notes = doc.section("notes").rows
    assert notes[0].cells == ["operator: keep going"]


def test_encoding_roundtrips_through_the_parser():
    doc = from_session(RECORD)
    text = render(doc, order="chrono")
    again = parse(text)
    assert again.goal == doc.goal
    assert len(again.section("calls").rows) == len(doc.section("calls").rows)
    assert [r.cells for r in again.section("tasks").rows] == [r.cells for r in doc.section("tasks").rows]


def test_empty_session_still_produces_a_valid_document():
    doc = from_session({"id": "session-empty"})
    assert doc.goal == "Continue session session-empty"
    text = render(doc)
    assert parse(text).goal == doc.goal


def test_loom_is_smaller_than_both_json_baselines():
    loom = count_tokens(render(from_session(RECORD)))
    assert loom < count_tokens(compact_json(RECORD))
    assert loom < count_tokens(raw_json(RECORD))


@pytest.mark.skipif(not CORPUS.exists(), reason="local Riciplay corpus not present")
def test_real_corpus_roundtrips_and_saves_tokens():
    records = load_corpus(str(CORPUS))
    assert records, "corpus should not be empty"

    total_raw = total_compact = total_loom = 0
    for record in records:
        doc = from_session(record)
        text = render(doc)
        reparsed = parse(text)
        assert reparsed.goal == doc.goal
        if doc.section("calls") is not None:
            assert len(reparsed.section("calls").rows) == len(doc.section("calls").rows)

        total_raw += count_tokens(raw_json(record))
        total_compact += count_tokens(compact_json(record))
        total_loom += count_tokens(text)

    assert total_loom < total_raw * 0.85
    assert total_loom < total_compact * 0.95


@pytest.mark.skipif(not CORPUS.exists(), reason="local Riciplay corpus not present")
def test_real_corpus_survives_a_budget():
    record = load_corpus(str(CORPUS))[0]
    doc = from_session(record)
    full = count_tokens(render(doc))
    text = render(doc, budget=max(120, full // 2), recap=True)
    small = parse(text)
    assert small.goal == doc.goal
    assert "~elided" in text or count_tokens(text) < full
    assert count_tokens(text) < full


@pytest.mark.skipif(not CORPUS.exists(), reason="local Riciplay corpus not present")
def test_corpus_records_have_the_expected_shape():
    record = load_corpus(str(CORPUS))[0]
    for key in ("id", "intents", "tool_calls", "incidents", "rerequests"):
        assert key in record
    assert isinstance(record["tool_calls"], list)
