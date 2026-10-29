"""Loom - a pragmatic context language for AI agents.

Quick start::

    from loom import parse, render, decompile, compile_text, stats

    doc = compile_text(open("brief.md").read())
    wire = render(doc, budget=800, recap=True)
    print(decompile(parse(wire)))
"""

from __future__ import annotations

from .ast import VERSION, Document, Row, Rule, Section
from .budget import count_tokens, estimate_tokens, tokenizer_name
from .compile_ import compile_text
from .decompile import decompile
from .distill import distill
from .ops import dedupe, lint, noise_report
from .parser import LoomSyntaxError, parse
from .render import BudgetError, render, summarise

__version__ = "0.1.0"

__all__ = [
    "VERSION",
    "Document",
    "Row",
    "Rule",
    "Section",
    "LoomSyntaxError",
    "BudgetError",
    "parse",
    "render",
    "decompile",
    "compile_text",
    "distill",
    "dedupe",
    "lint",
    "noise_report",
    "summarise",
    "count_tokens",
    "estimate_tokens",
    "tokenizer_name",
    "stats",
]


def stats(text: str, encoding: str = "o200k_base") -> dict[str, int]:
    """Token stats for a source string."""
    return {
        "chars": len(text),
        "tokens": count_tokens(text, encoding),
        "words": len(text.split()),
        "lines": len(text.splitlines()),
    }
