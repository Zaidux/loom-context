#!/usr/bin/env python3
"""Where does the Rust port start paying for its process startup?

Spawns ``loom-rs`` for every call, so the comparison includes the cost a real
user pays. Inputs are shaped like an actual session: many table rows, quoting
and long tool arguments. Python is measured as ``parse + render``; Rust as the
full subprocess round-trip.

    python bench/backend.py
    python bench/backend.py --sizes 1000 5000 20000 --iterations 20 --json

This justifies ``accel.DEFAULT_MIN_WORDS``. It is not a microbenchmark of the
parser: startup dominates below the crossover, by design.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loom import count_tokens, parse, render  # noqa: E402
from loom.accel import DEFAULT_BINARY, RustError, run_rust  # noqa: E402
from loom.session import from_session, load_corpus  # noqa: E402

DEFAULT_CORPUS = Path("/root/projects/riciplay-bench/corpus/sessions_corpus.jsonl")
DEFAULT_SESSION = "session-024"


def shaped_document(words: int):
    """A real or synthetic session trimmed to roughly ``words`` words."""
    if DEFAULT_CORPUS.exists():
        records = load_corpus(str(DEFAULT_CORPUS))
        record = next((r for r in records if r.get("id") == DEFAULT_SESSION), records[0])
        doc = from_session(record)
    else:
        from loom.ast import Document, Row, Section

        doc = Document()
        doc.goal = "synthetic backend benchmark"
        section = Section(name="notes", rows=[])
        doc.sections.append(section)
        for i in range(0, max(words, 1), 40):
            section.rows.append(Row([" ".join(f"w{j}" for j in range(i, i + 40))]))

    while len(render(doc).split()) > words:
        biggest = max(
            doc.sections,
            key=lambda s: sum(len(" ".join(r.cells).split()) for r in s.rows),
            default=None,
        )
        if biggest is None or not biggest.rows:
            break
        biggest.rows.pop()
    return doc


def time_python(doc, iterations: int) -> float:
    source = render(doc)
    for _ in range(min(3, iterations)):
        render(parse(source))
    start = time.perf_counter()
    for _ in range(iterations):
        render(parse(source))
    return (time.perf_counter() - start) / iterations * 1000.0


def time_rust(source: str, iterations: int, binary: Path) -> float:
    run_rust(binary, "render", source, timeout=60)  # warm
    start = time.perf_counter()
    for _ in range(iterations):
        run_rust(binary, "render", source, timeout=60)
    return (time.perf_counter() - start) / iterations * 1000.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", type=int, default=[1000, 2000, 4000, 8000, 16000, 32000])
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--rust", default=str(DEFAULT_BINARY))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    binary = Path(args.rust)
    if not binary.exists():
        print(f"rust binary not found: {binary}\nbuild it: cd rust && cargo build --release", file=sys.stderr)
        return 2

    rows = []
    for target in args.sizes:
        doc = shaped_document(target)
        source = render(doc)
        words = len(source.split())
        iterations = max(2, min(args.iterations, 400_000 // max(len(source), 1)))
        py = time_python(doc, iterations)
        try:
            rs = time_rust(source, iterations, binary)
        except RustError as exc:
            print(f"rust failed: {exc}", file=sys.stderr)
            return 2
        rows.append(
            {
                "target_words": target,
                "words": words,
                "chars": len(source),
                "tokens": count_tokens(source),
                "python_ms": round(py, 2),
                "rust_ms": round(rs, 2),
                "speedup": round(py / rs, 2) if rs else 0.0,
                "iterations": iterations,
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"{'words':>7}{'chars':>9}{'tokens':>8}{'python':>10}{'rust':>9}{'speedup':>9}")
    print("-" * 52)
    for r in rows:
        print(
            f"{r['words']:>7}{r['chars']:>9}{r['tokens']:>8}"
            f"{r['python_ms']:>9.2f}m{r['rust_ms']:>8.2f}m{r['speedup']:>8.1f}x"
        )
    winners = [r for r in rows if r["speedup"] >= 1.2]
    if winners:
        first = min(winners, key=lambda r: r["words"])
        print(
            f"\nfirst size with >=1.2x: ~{first['words']:,} words "
            f"(python {first['python_ms']} ms, rust {first['rust_ms']} ms)"
        )
    else:
        print("\nrust never reached 1.2x in this range")
    print("default auto threshold: 4000 words (conservative vs. table-heavy crossover)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
