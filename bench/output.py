#!/usr/bin/env python3
"""Does an agent save tokens by *writing* Loom instead of English?

The input-side benchmarks compress context that is sent *to* a model. This one
asks the mirror question: if the model's answer itself is Loom, is the answer
cheaper? The answer is mechanical — it is the same encoder, so the saving is
the same as on the input side — but the *decode* cost is what usually decides
whether it is worth doing:

  agent writes Loom  -> next agent reads Loom          saving = loom vs english
  agent writes Loom  -> human/English consumer reads  also need decompile

Loom can be decompiled deterministically and locally, so the second path costs
no tokens at inference time; it costs a translation step and some fidelity.

Caveat: this measures encoding an existing answer. It does **not** measure
whether a model can produce valid Loom unprompted, or whether it produces a
better/worse answer in Loom. That needs a model run (docs/EVALS.md).

    python bench/output.py
    python bench/output.py --glob 'docs/*.md' --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loom import compile_text, count_tokens, decompile, distill, render, tokenizer_name  # noqa: E402
from loom.fidelity import coverage  # noqa: E402

# Fixed sample corpus: never point this at files that quote its own results,
# or editing the docs changes the numbers and the docs become stale.
DEFAULT_FILES = [
    "examples/auth_refresh.md",
    "examples/migration_english.md",
    "examples/transcript.txt",
    "bench/samples/agent_report.md",
    "bench/samples/postmortem.md",
]


def measure(text: str) -> dict:
    """Encode one English answer both losslessly and lossily."""
    english = count_tokens(text)

    lossless_doc = compile_text(text)
    lossless_text = render(lossless_doc)
    lossless_cov, _ = coverage(text, lossless_text)

    lossy_doc, report = distill(text)
    lossy_text = render(lossy_doc)
    lossy_cov, _ = coverage(text, lossy_text)

    expanded = decompile(lossy_doc)
    expanded_cov, _ = coverage(text, expanded)

    lossless_tokens = count_tokens(lossless_text)
    lossy_tokens = count_tokens(lossy_text)
    expanded_tokens = count_tokens(expanded)

    return {
        "english": english,
        "lossless": lossless_tokens,
        "lossless_save_pct": round(100 * (english - lossless_tokens) / english, 1) if english else 0.0,
        "lossy": lossy_tokens,
        "lossy_save_pct": round(100 * (english - lossy_tokens) / english, 1) if english else 0.0,
        "decode": expanded_tokens,
        "decode_save_pct": round(100 * (english - expanded_tokens) / english, 1)
        if english
        else 0.0,
        "lossy_plus_decode": lossy_tokens + expanded_tokens,
        "lossless_fidelity_pct": round(100 * lossless_cov, 1),
        "lossy_fidelity_pct": round(100 * lossy_cov, 1),
        "roundtrip_fidelity_pct": round(100 * expanded_cov, 1),
        "distill": report,
    }


def collect(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        path = ROOT / pattern
        if any(ch in pattern for ch in "*?["):
            files.extend(sorted(ROOT.glob(pattern)))
        elif path.is_file():
            files.append(path)
    seen: set[Path] = set()
    unique = []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(f)
    return unique


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--glob",
        nargs="+",
        default=DEFAULT_FILES,
        metavar="PATTERN",
        help="files or globs, relative to the repo root",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    files = collect(args.glob)
    if not files:
        print("no matching files", file=sys.stderr)
        return 2

    rows = []
    for path in files:
        try:
            result = measure(path.read_text(encoding="utf-8"))
        except Exception as exc:  # a malformed sample should not kill the run
            print(f"skip {path}: {exc}", file=sys.stderr)
            continue
        result["name"] = str(path.relative_to(ROOT))
        result["words"] = len(path.read_text(encoding="utf-8").split())
        rows.append(result)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"tokenizer: {tokenizer_name()}   files: {len(rows)}\n")
    print(
        f"{'case':<30}{'words':>7}{'english':>9}{'lossless':>10}{'save':>7}"
        f"{'lossy':>8}{'save':>7}{'decode':>8}{'save':>7}"
    )
    print("-" * 96)
    for r in rows:
        print(
            f"{r['name']:<30}{r['words']:>7}{r['english']:>9}{r['lossless']:>10}"
            f"{r['lossless_save_pct']:>6}%{r['lossy']:>8}{r['lossy_save_pct']:>6}%"
            f"{r['decode']:>8}{r['decode_save_pct']:>6}%"
        )

    tot = {k: sum(r[k] for r in rows) for k in ("english", "lossless", "lossy", "decode")}
    save_ll = 100 * (tot["english"] - tot["lossless"]) / tot["english"]
    save_ly = 100 * (tot["english"] - tot["lossy"]) / tot["english"]
    save_dec = 100 * (tot["english"] - tot["decode"]) / tot["english"]
    print("-" * 96)
    print(
        f"{'TOTAL':<30}{sum(r['words'] for r in rows):>7}{tot['english']:>9}"
        f"{tot['lossless']:>10}{save_ll:>6.1f}%{tot['lossy']:>8}{save_ly:>6.1f}%"
        f"{tot['decode']:>8}{save_dec:>6.1f}%"
    )

    print(
        "\nReading a Loom answer saves the same share as an input packet (same codec).\n"
        "Expanding it locally to English is also cheaper than the original prose, but that\n"
        "saving is distillation, not notation, and it costs fidelity. Output-mode Loom is\n"
        "for model-to-model handoff; a human pays the decode step."
    )
    print(
        "Fidelity (lossy / round-trip): "
        f"{sum(r['lossy_fidelity_pct'] for r in rows) / len(rows):.1f}% / "
        f"{sum(r['roundtrip_fidelity_pct'] for r in rows) / len(rows):.1f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
