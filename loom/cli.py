"""Command line interface: ``python -m loom ...``."""

from __future__ import annotations

import argparse
import json
import sys

from .budget import count_tokens, tokenizer_name
from .compile_ import compile_text
from .distill import distill
from .decompile import decompile
from .ops import dedupe, lint, noise_report
from .parser import LoomSyntaxError, parse
from .render import BudgetError, render, summarise


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path: str | None, text: str) -> None:
    if path and path != "-":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def cmd_compile(args) -> int:
    doc = compile_text(_read(args.file))
    if args.dedupe:
        doc, removed = dedupe(doc)
        print(f";; removed {removed} duplicate rows", file=sys.stderr)
    problems = lint(doc)
    for p in problems:
        print(f";; warn: {p}", file=sys.stderr)
    _write(args.out, render(doc))
    return 0


def cmd_distill(args) -> int:
    doc, report = distill(_read(args.file), terse_output=not args.raw)
    _write(args.out, render(doc, order="salient"))
    print(";; distill report: " + ", ".join(f"{k}={v}" for k, v in report.items()), file=sys.stderr)
    return 0


def cmd_decompile(args) -> int:
    _write(args.out, decompile(parse(_read(args.file))))
    return 0


def cmd_render(args) -> int:
    doc = parse(_read(args.file))
    try:
        text = render(
            doc, budget=args.budget, order=args.order, recap=args.recap, legend=args.legend
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _write(args.out, text)
    if args.stats:
        print(
            json.dumps({"tokens": count_tokens(text), "tokenizer": tokenizer_name()}, indent=2),
            file=sys.stderr,
        )
    return 0


def cmd_check(args) -> int:
    source = _read(args.file)
    try:
        doc = parse(source)
    except LoomSyntaxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    problems = lint(doc)
    for p in problems:
        print(f"warn: {p}")
    print(json.dumps({"summary": summarise(doc), "noise": noise_report(doc)}, indent=2))
    return 1 if problems and args.strict else 0


def cmd_bench(args) -> int:
    english = _read(args.english)
    loom_source = _read(args.loom)
    parse(loom_source)  # validate
    en = count_tokens(english)
    lo = count_tokens(loom_source)
    saving = 100.0 * (en - lo) / en if en else 0.0
    print(f"english : {en:6d} tokens  {len(english.split()):5d} words")
    print(f"loom    : {lo:6d} tokens  {len(loom_source.split()):5d} words")
    print(f"saving  : {saving:6.1f}%   tokenizer={tokenizer_name()}")
    return 0


def cmd_stats(args) -> int:
    text = _read(args.file)
    print(
        json.dumps(
            {"tokens": count_tokens(text), "tokenizer": tokenizer_name(), "chars": len(text)},
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loom", description="Pragmatic context language for AI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="English brief -> Loom")
    c.add_argument("file")
    c.add_argument("-o", "--out")
    c.add_argument("--dedupe", action="store_true")
    c.set_defaults(func=cmd_compile)

    ds = sub.add_parser("distill", help="lossy prose distillation -> Loom")
    ds.add_argument("file")
    ds.add_argument("-o", "--out")
    ds.add_argument("--raw", action="store_true", help="classify but do not rewrite sentences")
    ds.set_defaults(func=cmd_distill)

    d = sub.add_parser("decompile", help="Loom -> English")
    d.add_argument("file")
    d.add_argument("-o", "--out")
    d.set_defaults(func=cmd_decompile)

    r = sub.add_parser("render", help="canonical Loom, optionally under a token budget")
    r.add_argument("file")
    r.add_argument("-o", "--out")
    r.add_argument("-b", "--budget", type=int)
    r.add_argument("--order", choices=["salient", "chrono"], default="salient")
    r.add_argument("--recap", action="store_true")
    r.add_argument("--legend", action="store_true")
    r.add_argument("--stats", action="store_true")
    r.set_defaults(func=cmd_render)

    k = sub.add_parser("check", help="parse + lint")
    k.add_argument("file")
    k.add_argument("--strict", action="store_true")
    k.set_defaults(func=cmd_check)

    b = sub.add_parser("bench", help="compare token counts")
    b.add_argument("english")
    b.add_argument("loom")
    b.set_defaults(func=cmd_bench)

    s = sub.add_parser("stats", help="token stats for any file")
    s.add_argument("file")
    s.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
