#!/usr/bin/env python3
"""Compare the Python and Rust implementations on the same real workload.

Builds a Loom document from a local Riciplay session, then times N iterations
of `parse + render` in each implementation. The document is written to /tmp and
never committed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loom import count_tokens, parse, render  # noqa: E402
from loom.session import from_session, load_corpus  # noqa: E402

DEFAULT_CORPUS = Path("/root/projects/riciplay-bench/corpus/sessions_corpus.jsonl")
DEFAULT_RUST = ROOT / "rust" / "target" / "release" / "loom-rs"


def build_fixture(corpus: Path, session_id: str) -> tuple[str, dict]:
    records = load_corpus(str(corpus))
    record = next((r for r in records if r.get("id") == session_id), records[0])
    return render(from_session(record)), record


def time_python(text: str, iterations: int) -> float:
    # warm up
    for _ in range(5):
        render(parse(text))
    start = time.perf_counter()
    for _ in range(iterations):
        render(parse(text))
    return (time.perf_counter() - start) / iterations


def time_rust(binary: Path, path: Path, iterations: int) -> tuple[float, float]:
    out = subprocess.run(
        [str(binary), "bench", str(path), "--iterations", str(iterations)],
        capture_output=True,
        text=True,
        check=True,
    )
    m = re.search(r"per_op=([\d.]+)us throughput=([\d.]+)", out.stdout)
    if not m:
        raise RuntimeError(f"unexpected rust bench output: {out.stdout}{out.stderr}")
    return float(m.group(1)) / 1e6, float(m.group(2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--session", default="session-024")
    ap.add_argument("--iterations", type=int, default=1000)
    ap.add_argument("--rust", default=str(DEFAULT_RUST))
    args = ap.parse_args(argv)

    rust = Path(args.rust)
    if not rust.exists():
        print(f"rust binary not found: {rust}\nbuild it with: cd rust && cargo build --release", file=sys.stderr)
        return 2

    text, record = build_fixture(Path(args.corpus), args.session)
    tmp = Path(tempfile.gettempdir()) / "loom_speed.loom"
    tmp.write_text(text)

    py = time_python(text, args.iterations)
    rs, rs_throughput = time_rust(rust, tmp, args.iterations)
    tokens = count_tokens(text)

    print(f"fixture   : {record.get('id')} ({len(text):,} chars, {tokens:,} tokens)")
    print(f"workload  : parse + render, {args.iterations} iterations")
    print(f"python    : {py*1e6:8.2f} us/op  {1/py:10.0f} ops/s")
    print(f"rust      : {rs*1e6:8.2f} us/op  {rs_throughput:10.0f} ops/s")
    print(f"speedup   : {py/rs:8.1f}x")
    print(f"throughput: {len(text)/1024/1024/rs:8.1f} MiB/s (rust)")
    print(json.dumps({"python_us": round(py * 1e6, 2), "rust_us": round(rs * 1e6, 2), "speedup": round(py / rs, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
