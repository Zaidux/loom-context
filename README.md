# Loom

**A pragmatic context language for AI agents.** Loom is a compact, typed, position-aware
representation of a task's context that compiles to and from English.

> Working name. The package, CLI and file extension (`.loom`) are easy to rename.

---

## The problem

Agents fail for two opposite reasons:

1. **Too much context.** Long prompts cost money, increase latency, and degrade recall
   ("context rot"). Everything the agent has ever seen gets re-sent on every turn.
2. **The wrong context.** The sentence that mattered — a hard constraint, a trust level, an
   unresolved question — is buried in the middle of a wall of prose, so the model acts on the
   loudest thing instead of the truest thing.

Most "token saving" formats only attack the first problem, and they pay for it with accuracy:
recent agentic benchmarks show compact structural formats losing **9–14 accuracy points**
against plain JSON while saving 18–27% of tokens. Loom attacks both problems by making
*structure and salience part of the encoding*, and by keeping the surface in English.

## What Loom is

Three separable pieces:

| Layer | Module | Job |
|---|---|---|
| **Notation** | `parser.py`, `render.py` | A line-oriented, typed context packet: goal, done-criteria, hard rules, state, evidence, unknowns, next actions |
| **Budget engine** | `render.py` | Evicts low-priority rows under a token budget, never silently, never dropping a hard rule |
| **Translator** | `compile_.py`, `distill.py`, `decompile.py` | English → Loom (lossless or audited-lossy) and Loom → English |

## Design bets

1. **Structure beats terseness.** Typed sections and explicit roles let a model find the
   constraint without scanning prose. Symbolic DSLs save more tokens but lose accuracy.
2. **Salience is data, not formatting.** `!must` / `!never` / `?q` / `trust=` are parseable,
   so the renderer can guarantee they survive compression.
3. **Nothing is dropped silently.** Eviction leaves `~elided 3`. A model that knows context
   was removed asks for it; a model that does not, guesses.
4. **Position is part of the encoding.** Hard rules go first and can be restated last,
   exploiting the U-shaped attention curve behind the "lost in the middle" effect.
5. **Lossless by default, lossy only on request.** `compile` preserves every sentence;
   `distill` is explicitly lossy and prints an audit report of what it removed.

## Quickstart

```bash
cd loom
python -m loom compile examples/auth_refresh.md      # English brief -> Loom (lossless)
python -m loom distill examples/transcript.txt       # verbose transcript -> Loom (lossy, audited)
python -m loom decompile examples/auth_refresh.loom  # Loom -> English
python -m loom render examples/auth_refresh.loom -b 130 --recap
python -m loom check examples/auth_refresh.loom
python bench/eval.py --pair examples/transcript.txt examples/transcript.loom
python bench/sessions.py --show-missing        # real session corpus, if present
python bench/speed.py                          # Python vs Rust
```

As a library:

```python
from loom import distill, render, parse, decompile, count_tokens

doc, report = distill(open("transcript.txt").read())
wire = render(doc, budget=400, recap=True)
print(count_tokens(wire), report)
print(decompile(parse(wire)))
```

## A concrete pair

English (272 tokens):

> ## Objective
> Fix the failing refresh test in the authentication service without changing any public API surface.
>
> ## Constraints
> - You must preserve backwards compatibility for all public endpoints.
> - You must never edit `src/auth/public.py`.
> ...

Loom (234 tokens, and every constraint is now machine-checkable):

```loom
@loom 1.0
#use repo.read
#use test.run
!goal Fix failing refresh test in auth service; no public API change.
!done auth suite green; public signatures unchanged
!must preserve backwards compatibility on all public endpoints
!never edit src/auth/public.py
!never upgrade the token library
!must keep diff under 150 lines

#state
  repo = acme/api @main
  failing = test_auth_refresh
  attempts = 2

#evidence{id,src,trust,text}
  e1,test_run.ts:41,0.95,"expected 200 got 401"
  e2,config.py:88,0.90,"refresh_ttl = 900s"
  e3,staging:clock,0.80,"skew +42s vs auth server"
```

Under a 130-token budget the renderer keeps the goal, all four rules and the unknowns, and
marks the state/evidence it evicted as `~elided`. It refuses to go below the mandatory floor
(~115 tokens here) rather than silently truncating a constraint.

## Measured results

`python bench/eval.py` — real token counts (`o200k_base`), plus **fidelity**: the share of
hard literals from the source (paths, thresholds, identifiers, quoted values) that survive.

| case | source | Loom | saving | fidelity |
|---|---:|---:|---:|---:|
| `auth_refresh` (short brief) | 272 | 234 | 14.0% | 100% |
| `migration_english` (`compile`, lossless) | 528 | 492 | 6.8% | 100% |
| `migration_english` (`distill`, lossy) | 528 | 439 | 16.9% | 100% |
| `transcript` (rambling agent log) | 672 | 405 | 39.7% | 100% |

**Read this honestly.** Savings scale with how much noise the source contains: ~7% on already
terse specs, ~17% on structured briefs, ~40% on conversational transcripts. Short inputs pay a
"prompt tax" that can erase the gain; Loom targets contexts above roughly 1k tokens. The 9–14pp
accuracy loss seen with other compact formats is *not yet measured for Loom* — the eval protocol
to test it is in [`docs/EVALS.md`](docs/EVALS.md). Until that runs, treat the accuracy claim as a
design hypothesis, not a result.

### Real sessions

`python bench/sessions.py` runs the encoder over **27 real Riciplay agent sessions**
(3,849 tool calls) and compares three representations of the same record: indented JSON, minified
JSON, and Loom. "Fidelity" is the share of every scalar leaf in the record (strings ≥ 4 chars,
numbers) that still appears in the output — it is computed independently of the encoder.

| representation | tokens | vs raw JSON |
|---|---:|---:|
| raw JSON (`indent=2`) | 922,618 | — |
| minified JSON | 823,422 | −10.8% |
| **Loom** | **713,881** | **−22.6%** |

- **−13.3%** against minified JSON, which is the fair "just compress the whitespace" baseline.
- **96.0%** leaf fidelity. The remaining gap is long escaped tool output, collapsed onto one
  line by design; nothing is silently dropped from the structured fields.
- At an **equal token budget**, naive truncation of the JSON retains only **69.8%** of leaves,
  versus 96.0% for Loom. Structure beats truncation when context is tight.

The corpus is read from a local path at runtime and is not vendored into this repository.

### Speed (Rust port)

`rust/` is a dependency-free port of the parser, renderer, decompiler and ops, with the same
CLI surface. `python bench/speed.py` runs parse+render on a real 113k-token session:

| implementation | per op | throughput |
|---|---:|---:|
| Python | 85.8 ms | 12 ops/s |
| **Rust (`loom-rs`, release)** | **4.26 ms** | **235 ops/s**, 81 MiB/s |

That is a **~20× speedup**, enough to re-render context on every turn of a long session without
the budget engine becoming the bottleneck. Rust and Python produce byte-identical output on the
checked-in examples, including under `-b` with `--recap`. One caveat: Python uses `tiktoken`
(`o200k_base`) for exact counts, while Rust uses a dependency-free estimator (~3.8 ASCII
chars/token), so a Rust `-b 800` is approximate and will not evict at exactly the same row as
Python's `-b 800`.

```bash
cd rust && cargo build --release
./target/release/loom-rs render ../examples/auth_refresh.loom -b 130 --recap
./target/release/loom-rs decompile ../examples/auth_refresh.loom
./target/release/loom-rs check ../examples/auth_refresh.loom --strict
./target/release/loom-rs bench ../examples/transcript.loom --iterations 1000
```


## Repository layout

```
loom/
  loom/
    ast.py        document model
    parser.py     Loom -> AST (line numbers in every error)
    render.py     canonical form, budget eviction, head/tail placement
    compile_.py   English brief -> Loom, sentence-preserving
    distill.py    English -> Loom, lossy + audited
    decompile.py  Loom -> English
    ops.py        dedupe, lint, noise report
    budget.py     tiktoken counter with fallback
    session.py    real agent session -> Loom encoder
    cli.py        compile / distill / decompile / render / check / bench
  rust/
    src/          dependency-free port (ast, parser, render, decompile, ops)
    tests/core.rs parity tests over the shared fixtures
  docs/
    DESIGN.md     research review + architecture decisions
    SPEC.md       grammar, semantics, translator contract
    EVALS.md      evaluation protocol and current status
  bench/
    eval.py       token + fidelity harness on curated pairs
    sessions.py   real-session token/fidelity/equal-budget harness
    speed.py      Python vs Rust parse+render benchmark
  examples/       paired English/Loom cases
  tests/          28 tests: round-trip, budget, lint, distillation, sessions
```

## Status

Working prototype, v0.1. Not yet validated for downstream accuracy. The language surface is
stable enough to build against; the distillation heuristics are the part most likely to change.
Token savings, leaf fidelity, equal-budget retention and Rust/Python parity are measured;
downstream task accuracy is not.

See [`docs/DESIGN.md`](docs/DESIGN.md) for why each component was chosen, and what was
deliberately left out.
