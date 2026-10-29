#!/usr/bin/env python3
"""Benchmark Loom against real Riciplay agent sessions.

Reads the local session corpus (default:
``/root/projects/riciplay-bench/corpus/sessions_corpus.jsonl``) and compares
three representations of the same session:

  raw      json.dumps(record, indent=2)      what a naive harness sends
  compact  json.dumps(record, separators)    a fair "just minify it" baseline
  loom     loom.session.from_session(...)    this project

Fidelity is measured over *all scalar leaves* of the record (every string of
length >= 4 and every number), not just the fields the encoder knows about.
That keeps the check independent of the encoder's own extraction logic.

The corpus is read from disk and is not vendored into the repository.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loom import count_tokens, render, tokenizer_name  # noqa: E402
from loom.session import compact_json, from_session, load_corpus, raw_json  # noqa: E402

DEFAULT_CORPUS = Path("/root/projects/riciplay-bench/corpus/sessions_corpus.jsonl")


def _norm(text: str) -> str:
    # "; " is the encoder's single-line stand-in for a newline in tool args
    text = text.replace('"', " ").replace(";", " ")
    # json-escaped whitespace ("\n") and real whitespace normalise the same way
    text = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def leaves(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            leaves(v, out)
    elif isinstance(obj, list):
        for v in obj:
            leaves(v, out)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, str):
        if len(obj) >= 4:
            out.add(_norm(obj))
    else:
        out.add(_norm(str(obj)))


def fidelity(record: dict, loom_text: str) -> tuple[float, list[str]]:
    wanted: set[str] = set()
    leaves(record, wanted)
    wanted = {w for w in wanted if w}
    if not wanted:
        return 1.0, []
    hay = _norm(loom_text)
    missing = sorted(w for w in wanted if w not in hay)
    return (len(wanted) - len(missing)) / len(wanted), missing


def truncate_to(text: str, budget: int) -> str:
    """Longest prefix of ``text`` that fits the budget (binary search)."""
    if count_tokens(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def run(corpus: Path) -> list[dict]:
    rows = []
    for record in load_corpus(str(corpus)):
        loom_text = render(from_session(record))
        raw = raw_json(record)
        compact = compact_json(record)
        cov, missing = fidelity(record, loom_text)
        loom_tokens = count_tokens(loom_text)
        trunc = truncate_to(raw, loom_tokens)
        cov_budget, _ = fidelity(record, trunc)
        rows.append(
            {
                "id": record.get("id"),
                "messages": record.get("n_messages", 0),
                "calls": len(record.get("tool_calls") or []),
                "raw": count_tokens(raw),
                "compact": count_tokens(compact),
                "loom": count_tokens(loom_text),
                "fidelity": round(100 * cov, 1),
                "fidelity_equal_budget": round(100 * cov_budget, 1),
                "missing": missing[:6],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-missing", action="store_true")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 2

    rows = run(corpus)
    if args.limit:
        rows = rows[: args.limit]

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"tokenizer: {tokenizer_name()}   sessions: {len(rows)}\n")
    print(f"{'session':<14}{'msgs':>6}{'calls':>7}{'raw':>9}{'compact':>9}{'loom':>9}{'save(raw)':>11}{'save(cmp)':>11}{'fid':>7}{'fid@budget':>12}")
    print("-" * 92)
    for r in rows:
        sv_raw = 100 * (r["raw"] - r["loom"]) / r["raw"] if r["raw"] else 0
        sv_cmp = 100 * (r["compact"] - r["loom"]) / r["compact"] if r["compact"] else 0
        print(
            f"{r['id']:<14}{r['messages']:>6}{r['calls']:>7}{r['raw']:>9}{r['compact']:>9}"
            f"{r['loom']:>9}{sv_raw:>10.1f}%{sv_cmp:>10.1f}%{r['fidelity']:>6.1f}%"
            f"{r['fidelity_equal_budget']:>11.1f}%"
        )
        if args.show_missing and r["missing"]:
            print("   missing:", "; ".join(m[:60] for m in r["missing"]))

    tot = {k: sum(r[k] for r in rows) for k in ("raw", "compact", "loom")}
    print("-" * 92)
    print(
        f"{'TOTAL':<14}{'':>6}{sum(r['calls'] for r in rows):>7}"
        f"{tot['raw']:>9}{tot['compact']:>9}{tot['loom']:>9}"
        f"{100*(tot['raw']-tot['loom'])/tot['raw']:>10.1f}%"
        f"{100*(tot['compact']-tot['loom'])/tot['compact']:>10.1f}%"
        f"{sum(r['fidelity'] for r in rows)/len(rows):>6.1f}%"
        f"{sum(r['fidelity_equal_budget'] for r in rows)/len(rows):>11.1f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
