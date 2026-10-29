"""Tests for the shared literal-fidelity checks."""

from __future__ import annotations

from loom.fidelity import coverage, facts


def test_facts_find_numbers_paths_identifiers_and_quotes():
    f = facts('Set REFRESH_TTL to 900 at `src/auth/refresh.py`, error "expected 200 got 401".')
    assert "900" in f
    assert "src/auth/refresh.py" in f
    assert "refresh_ttl" in f
    assert "expected 200 got 401" in f


def test_facts_ignore_tiny_tokens():
    assert facts("a b 1") == set()


def test_coverage_is_one_when_nothing_to_check():
    score, missing = coverage("hello", "anything")
    assert score == 1.0 and missing == []


def test_coverage_ignores_case_and_whitespace():
    source = "The limit is 150 lines in src/auth/public.py"
    target = "limit:   150 lines, SRC/AUTH/PUBLIC.PY"
    score, missing = coverage(source, target)
    assert score == 1.0
    assert missing == []


def test_coverage_reports_missing_literals():
    score, missing = coverage("timeout is 30s at src/a.py", "timeout is 30s")
    assert score == 0.5
    assert missing == ["src/a.py"]
