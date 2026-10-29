"""Tests for the lossy distillation pass."""

from __future__ import annotations

from pathlib import Path

from loom import count_tokens, distill, parse, render

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = ROOT / "examples" / "transcript.txt"


def test_distill_cuts_tokens_and_reports_work():
    source = TRANSCRIPT.read_text()
    doc, report = distill(source)
    out = render(doc)
    assert count_tokens(out) < count_tokens(source) * 0.8
    assert report["duplicates"] >= 1
    assert report["noise"] >= 1
    assert report["verbatim"] == 2


def test_distill_keeps_constraints_and_unknowns():
    doc, _ = distill(TRANSCRIPT.read_text())
    texts = " ".join(r.text.lower() for r in doc.rules)
    assert "rotate stripe api keys" in texts
    assert "feature flag" in texts
    assert len(doc.questions) == 3
    assert any("ntp" in q.lower() for q in doc.questions)


def test_distill_output_round_trips():
    doc, _ = distill(TRANSCRIPT.read_text())
    wire = render(doc)
    assert render(parse(wire), order="chrono") == wire


def test_narration_is_dropped():
    doc, report = distill(
        "I ran the test three times. It failed. The parser must reject empty ids."
    )
    assert report["noise"] >= 2
    assert "ran the test" not in render(doc)
    assert any("reject empty ids" in r.text for r in doc.rules)
