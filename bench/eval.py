#!/usr/bin/env python3
"""Token + fidelity harness for Loom.

Compression without fidelity is just data loss. This harness reports three
numbers for every (source, loom) pair:

  tokens   - real token count under a named tokeniser
  saving   - percentage removed
  fidelity - share of source "hard facts" (paths, numbers, identifiers,
             quoted literals) that survive in the Loom form

Fidelity is a *necessary* check, not a sufficient one: it catches the obvious
sin of dropping an API key or a threshold, but only a downstream accuracy run
(see docs/EVALS.md) can show that the remaining context is actually usable.

Usage:
    python bench/eval.py --pair examples/migration_english.md examples/migration.loom
    python bench/eval.py --pair ... --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom import count_tokens, tokenizer_name  # noqa: E402

_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:ms|s|min|h|rps|%|x)?\b")
_PATH = re.compile(r"\b[\w./-]+/[\w./-]+\b|\b\w+\.(?:py|ts|js|go|rs|yaml|toml|json|md)\b")
_IDENT = re.compile(r"(?<!`)`([^`\n]+)`(?!`)|\b([A-Z][A-Z0-9_]{3,})\b")
_QUOTED = re.compile(r'"([^"]{4,})"')


def facts(text: str) -> set[str]:
    """Extract literals that must not be silently lost."""
    out: set[str] = set()
    out |= {m.group(0).strip().lower() for m in _NUMBER.finditer(text)}
    out |= {m.group(0).strip().lower() for m in _PATH.finditer(text) if len(m.group(0)) > 4}
    for m in _IDENT.finditer(text):
        out.add((m.group(1) or m.group(2) or "").strip().lower())
    out |= {m.group(1).strip().lower() for m in _QUOTED.finditer(text)}
    return {f for f in out if f and len(f) > 2}


def coverage(source: str, target: str) -> tuple[float, list[str]]:
    wanted = facts(source)
    if not wanted:
        return 1.0, []
    flat = re.sub(r"\s+", " ", target.lower())
    missing = sorted(f for f in wanted if f not in flat)
    return (len(wanted) - len(missing)) / len(wanted), missing


def compare(source: str, loom: str) -> dict:
    cov, missing = coverage(source, loom)
    en = count_tokens(source)
    lo = count_tokens(loom)
    return {
        "source_tokens": en,
        "loom_tokens": lo,
        "saving_pct": round(100 * (en - lo) / en, 1) if en else 0.0,
        "fidelity_pct": round(100 * cov, 1),
        "missing": missing,
        "tokenizer": tokenizer_name(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", nargs=2, action="append", metavar=("SOURCE", "LOOM"), required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    for src, lo in args.pair:
        name = Path(src).stem
        r = compare(Path(src).read_text(), Path(lo).read_text())
        r["name"] = name
        rows.append(r)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"tokenizer: {tokenizer_name()}\n")
    print(f"{'case':<22}{'src':>7}{'loom':>7}{'saving':>9}{'fidelity':>10}")
    print("-" * 55)
    for r in rows:
        print(
            f"{r['name']:<22}{r['source_tokens']:>7}{r['loom_tokens']:>7}"
            f"{r['saving_pct']:>8}%{r['fidelity_pct']:>9}%"
        )
        if r["missing"]:
            print(f"  missing: {', '.join(r['missing'][:8])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
