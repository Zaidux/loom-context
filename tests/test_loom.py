"""Round-trip and semantic tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom import (
    LoomSyntaxError,
    compile_text,
    decompile,
    dedupe,
    lint,
    parse,
    render,
)
from loom.budget import count_tokens

ROOT = Path(__file__).resolve().parents[1]
LOOM_EXAMPLE = ROOT / "examples" / "auth_refresh.loom"
MD_EXAMPLE = ROOT / "examples" / "auth_refresh.md"


def test_parse_example_structure():
    doc = parse(LOOM_EXAMPLE.read_text())
    assert doc.version == "1.0"
    assert doc.goal and "refresh" in doc.goal
    assert len(doc.rules) == 4
    assert {r.kind for r in doc.rules} == {"must", "never"}
    state = doc.section("state")
    assert state is not None and state.style == "kv"
    ev = doc.section("evidence")
    assert ev is not None and ev.columns == ["id", "src", "trust", "text"]
    assert len(ev.rows) == 3


def test_render_parse_is_idempotent():
    first = render(parse(LOOM_EXAMPLE.read_text()), order="chrono")
    second = render(parse(first), order="chrono")
    assert first == second


def test_decompile_contains_every_fact():
    text = decompile(parse(LOOM_EXAMPLE.read_text()))
    for needle in ("test_auth_refresh", "900s", "+42s", "src/auth/public.py", "NTP"):
        assert needle in text
    assert "Objective:" in text
    assert "Hard constraints:" in text


def test_compile_markdown_example():
    doc = compile_text(MD_EXAMPLE.read_text())
    assert doc.goal and "refresh" in doc.goal.lower()
    assert doc.done and "suite" in doc.done.lower()
    kinds = {(r.kind, r.text.lower()) for r in doc.rules}
    assert ("never", "edit `src/auth/public.py`") in kinds
    assert len(doc.rules) == 4
    assert doc.section("state") is not None
    assert len(doc.section("state").rows) == 4
    assert len(doc.questions) == 2


def test_dedupe_collapses_repeated_tool_output():
    doc = compile_text(MD_EXAMPLE.read_text())
    before = sum(len(s.rows) for s in doc.sections)
    doc, removed = dedupe(doc)
    after = sum(len(s.rows) for s in doc.sections)
    assert removed == 1
    assert after == before - 1


def test_lint_flags_missing_goal_and_contradiction():
    doc = parse("!must ship\n!never ship\n#state\n  a = 1\n")
    problems = lint(doc)
    assert any("no !goal" in p for p in problems)
    assert any("contradiction" in p for p in problems)


def test_budget_evicts_and_marks_elision():
    doc = parse(LOOM_EXAMPLE.read_text())
    full = count_tokens(render(doc))
    out = render(doc, budget=full // 2)
    assert count_tokens(out) <= full // 2
    assert "!goal" in out and "!never edit src/auth/public.py" in out
    assert "~elided" in out or "~truncated" in out


def test_budgeted_render_parses_back():
    """A compressed packet must still be valid on the next turn."""
    doc = parse(LOOM_EXAMPLE.read_text())
    full = count_tokens(render(doc))
    out = render(doc, budget=full // 2, recap=True)
    again = parse(out)
    assert again.goal == doc.goal
    assert [r.text for r in again.rules] == [r.text for r in doc.rules]


def test_recap_repeats_rules_at_tail():
    doc = parse(LOOM_EXAMPLE.read_text())
    out = render(doc, recap=True)
    tail = out.strip().splitlines()[-1]
    assert tail.startswith("!rem ") and "edit src/auth/public.py" in tail


def test_malformed_table_reports_line_number():
    with pytest.raises(LoomSyntaxError) as exc:
        parse("#evidence{id,src}\n  only-one-cell\n")
    assert exc.value.line == 2
