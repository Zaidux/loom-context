# Design

Why Loom looks the way it does. Every non-obvious decision is tied to either a published
result or a measured property of this repository.

---

## 1. What the literature actually says

### 1.1 Context is a finite, position-sensitive resource

- Models attend unevenly across long inputs: retrieval accuracy is U-shaped, worse in the
  middle, even for explicitly long-context models
  ([Liu et al., TACL 2024](https://aclanthology.org/2024.tacl-1.9/)).
- Recall degrades as input grows — "context rot" — across 18 models
  ([Chroma 2025](https://research.trychroma.com/context-rot)). Anthropic frames context as
  "a finite resource with diminishing marginal returns"
  ([2025](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)).
- Long-horizon search agents *give up or answer prematurely* as context accumulates; a mixed
  "keep-latest + summarise" policy is the best cost/rot trade-off
  ([Xia et al., 2026](https://arxiv.org/abs/2606.29718)).

**Implication:** ordering and restatement are not cosmetic. They are part of the encoding.

### 1.2 Removing tokens is not free

- LLMLingua reports up to 20× compression with "little" loss, but the useful production range
  is 4–10× before quality breaks
  ([Jiang et al., EMNLP 2023](https://arxiv.org/abs/2310.05736);
  [practitioner summary, 2026](https://whysogeek.com/prompt-compression-cut-llm-tokens-2026)).
- Token-level pruning breaks contextual integrity and can discard information that is never
  recoverable; chunk-level *generative* rewriting outperforms it, especially at high ratios
  ([SCOPE, COLM 2026](https://arxiv.org/abs/2508.15813)).
- Compression is language-dependent: aggressive learned compression can fall to *below
  no-context utility* in non-English languages, and translate-then-compress beats native
  compression for several languages
  ([Lukauskas, 2026](https://arxiv.org/abs/2608.26175)).

**Implication:** prefer semantic rewriting over token deletion, keep an audit trail, and do not
assume a compression ratio transfers across domains or languages.

### 1.3 Invented compact syntax costs accuracy in agent loops

- On four agentic benchmarks and five open-weight models, TRON cut tokens by up to 27% with
  accuracy within **14 percentage points** of JSON; TOON cut up to 18% at a **9pp** cost and
  additionally *cascaded* on multi-turn parse failures and collapsed parallel tool calls
  ([Kutschka & Geiger, 2026](https://arxiv.org/abs/2605.29676)).
- TOON's own generation benchmark finds plain JSON still wins on one-shot and final accuracy,
  with TOON's advantage concentrated in uniform tabular data
  ([Matveev, 2026](https://arxiv.org/abs/2603.03306)).
- Third-party retrieval tests found TOON was never the best-performing format and was weak on
  nested retrieval ([Improving Agents, 2025](https://www.improvingagents.com/blog/toon-benchmarks)).

**Implication — the central bet:** do **not** replace English with a symbolic DSL. Keep the
surface English-shaped and spend the compression budget on (a) removing redundancy, (b) making
structure explicit, (c) putting the important thing where attention actually lands.

### 1.4 Restating important context at the tail helps

RAL-Writer duplicates the top-k most important chunks at the prompt tail and shows reduced
middle-position degradation in long generation
([2025](https://arxiv.org/abs/2503.06868)).

**Implication:** `--recap` re-emits the hard rules after the body. It is optional because it
spends tokens; the budget engine drops it before dropping content.

---

## 2. Components borrowed, and what changed

| Source | Idea taken | How Loom uses it | What we did differently |
|---|---|---|---|
| TOON / CTON | Tabular rows for uniform records; `key=value` for objects | `#evidence{id,src,trust,text}` tables, `#state` KV | Only for *uniform* data; deep nesting stays prose. Tables are typed and evictable. |
| LLMLingua | Per-token importance scoring | Per-*row* priority from `trust`, `salience`, `prio` | No auxiliary model; importance is declared by the producer, so it is auditable |
| SCOPE | Chunk-level generative rewriting | `distill.py` rewrites sentences, classifies, dedupes | Deterministic rules, not a summariser model; emits an audit report |
| RAL-Writer | Restate top-k at the tail | `!rem` recap line | Rules only, capped at ~240 chars |
| Anthropic context editing | Remove stale tool results, keep decisions | Budget eviction with `~elided` markers | Eviction is priority-based, not recency-only; elision is visible |
| Prefix caching | Stable prefix = cheap tokens | `--order cache` keeps invariants first | Loom does *not* reorder a cached prefix by relevance |

---

## 3. Architecture

```
            English / transcript / tool output
                          |
             +------------+-------------+
             |                          |
      compile (lossless)          distill (lossy, audited)
      headings + bullets          classify -> terse -> dedupe
             |                          |
             +------------+-------------+
                          v
                   +--------------+
                   |  Document    |   goal, done, rules, questions,
                   |  (AST)       |   sections: state/evidence/next/notes
                   +--------------+
                     |          |
        render(budget)          decompile
             |                       |
      canonical Loom            English brief
      (head/tail aware)         (for humans)
```

### 3.1 Layer model

Context is layered by *volatility*, because that determines both eviction order and cache
behaviour:

| Layer | Contents | Volatility | Cache |
|---|---|---|---|
| **L0 invariants** | `!goal`, `!done`, `!must`, `!never`, `#defs` | never changes in a task | stable prefix |
| **L1 working state** | `#state` | changes per turn | middle |
| **L2 evidence** | `#evidence`, ranked by trust | grows and ages | middle |
| **L3 references** | `#refs`, ids into an external store | cheap, stable | tail |

The renderer emits L0 first. Under a cache-oriented order it never moves L0, which keeps the
prefix cache valid even as L1/L2 churn.

### 3.2 Budget algorithm

```
if mandatory(goal + done + rules) > budget: raise BudgetError   # never truncate a rule
while tokens(doc) > budget:
    victim = min(items, key=priority)     # rows, #use lines, ?q lines
    remove(victim); mark section ~elided n
if still over: drop recap, then #use lines
```

Priorities (higher survives):

| Item | Priority | Rationale |
|---|---:|---|
| `#defs` | 0.90 | schema errors poison every later parse |
| `#state` | 0.85 | ground truth; cheap and dense |
| `#next` / `#plan` | 0.70 | the action the agent must take |
| `?q` unknowns | 0.60 | cheap insurance against confident wrong answers |
| `#evidence` | 0.50 × (0.5 + trust) | high-trust evidence outranks low-trust |
| `#refs` | 0.55 | pointers, not payloads |
| `#use` capabilities | 0.35 | re-discoverable from the tool registry |
| `#notes` | 0.10 | background |

Two invariants matter more than the numbers:

1. **No silent loss.** Every evicted section renders `~elided n`; a fully evicted section
   collapses to one line (`#evidence{...} ~elided 3`).
2. **No infeasible budgets.** If the budget cannot hold goal + rules, the renderer raises
   instead of quietly dropping a constraint.

### 3.3 Position policy

- `!goal`, `!done`, `!must`, `!never` are always in the first lines.
- `?q` is emitted after the body — unknown questions near the end are the last thing the model
  reads before acting.
- `--recap` appends `!rem` with the rules again (U-shape mitigation).
- `--order cache` keeps the invariant prefix byte-identical across turns; `salient` (default)
  sorts by section type; `chrono` preserves author order.

### 3.4 Noise model

Every evidence row may carry:

- `trust` — float 0..1, from the tool or the source.
- `salience` / `prio` — how much this row matters to *this* task.
- section meta `[src=... t=...]` — provenance.

`ops.noise_report()` counts low-trust rows and duplicate candidates before you spend them.
`ops.dedupe()` collapses exact repeats, ignoring the `id` column.

### 3.5 Session projection

Real agent transcripts are not prose and not JSON schemas; they are a long sequence of
`(tool, args)` pairs with repeated task lists and occasional failures. `loom/session.py`
projects one session record into the same ast used everywhere else:

| record field | Loom |
|---|---|
| first intent | `!goal` |
| remaining intents | `?q` (they constrain, they do not restate the goal) |
| id / source / workspace / status / counts | `#state` |
| all `tasks` calls | one `#tasks` table, later status wins |
| every other tool call | `#calls{tool,arg}`, one line per invocation |
| incidents | `#incidents` with failing tool and signature |
| re-requests | `#notes` |

The encoder is mechanical on purpose. It does not summarise, choose, or reorder; it removes
JSON scaffolding (`{"name": ..., "args": {...}}`) and collapses repeated task payloads. Duplicate
calls are *kept* by the encoder and removed only by an explicit `dedupe()`, so a "give me the
whole session" ask never loses an invocation.

Validation: 96.0% of scalar leaves survive, and at an equal token budget the encoding keeps
96.0% versus 69.8% for naive truncation. Both numbers come from `bench/sessions.py`, which
computes them independently of this module's field extraction.

### 3.6 Rust port

`rust/` mirrors the Python implementation with no third-party crates: `ast`, `parser`, `render`,
`decompile`, `ops`, `tokens`. The contract is *output* parity, not code parity — the two
implementations must emit byte-identical Loom for the same input, and share fixtures in
`examples/` so a divergence breaks both test suites.

Rust buys throughput: ~20× in-process on a 113k-token session (4.26 ms vs 85.8 ms per
parse+render), 81 MiB/s. End-to-end through a subprocess the win depends on size: ~0.7× at 1k
words, 2.2× at 4k, ~8× at 32k (`bench/backend.py`), because process startup is fixed cost. The
cost is token accounting: Python uses `tiktoken` when available for exact budget counts; Rust
uses the same dependency-free estimator as Python's fallback (~3.8 ASCII chars/token). A
budgeted render is therefore approximate in Rust. That was accepted deliberately — shipping a
model file would have turned a zero-dependency, offline-safe binary into a network-coupled one.

### 3.7 Backend selection

The fast path is opt-in by size, not always-on:

```
if backend == python:                 python
elif words < threshold (4000):        python      # spawn costs more than it saves
elif probe(loom-rs, 350ms) fails:     python      # missing, hung, or non-zero exit
else:                                 rust
if rust raises during the call:       python      # never lose a render to an optimisation
```

The probe parses a three-line document and is cached per binary mtime, so a long process pays
it once. An explicit `--backend rust` bypasses the word threshold but still probes; an explicit
`--rust PATH` is authoritative and does not silently fall back to the repo build.

Why a subprocess rather than FFI: PyO3 or a C ABI would remove the ~2 ms startup and make the
crossover much lower, but it would couple the Python package to a platform-specific compiled
artifact. Loom is meant to be installable with `pip` and no toolchain; spawning a static binary
is the boring, portable option. If the detector ever becomes the bottleneck, `bench/backend.py`
is the harness that will show it.

### 3.8 Answers written in Loom

The same encoding can be used for model *output* rather than input. `bench/output.py` measures
it on five fixed answer samples: lossless `compile` saves 3.3%, audited `distill` saves 19.4% at
96.0% literal fidelity, and local expansion back to English lands at 24.9% because the content
was already distilled. Two conclusions:

1. There is no special output-side multiplier. Loom is a notation; it compresses the text it is
   given, whether that text is a prompt or an answer.
2. The naive "Loom + decompile" pipeline is not a win. Expansion is a local operation, so it
   costs no model tokens, but it does not recover what distillation dropped, and it adds a
   translation step. Output Loom is a model-to-model handoff format.

What is unmeasured is the part that decides adoption: can a model emit valid Loom unprompted,
and is its answer better or worse than prose? `docs/SPEC.md` §5.3 carries the prompt and
`loom check --strict` is the guardrail; the accuracy protocol is in `EVALS.md`.

---

## 4. Translator

### 4.1 `compile` — lossless

Parses markdown headings, wrapped paragraphs, bullets, and `key: value` lines. Maps headings to
roles, extracts `(confidence 0.9)` into a `trust` column, and emits one Loom row per source
statement. Nothing is paraphrased. This is the default because it is the safe one.

### 4.2 `distill` — lossy, audited

Four passes:

1. **Block normalisation** — join wrapped lines; fenced/4-space blocks are verbatim tool output
   (never sentence-split, never rewritten).
2. **Classification** — heading hints first, then cue words: questions, done-criteria, hard
   rules, state, actions, evidence, notes.
3. **Terse rewrite** — a conservative phrase list (filler removal, unit abbreviation, article
   dropping). It never touches negation, numbers, paths, or quoted literals.
4. **Dedupe** — Jaccard ≥ 0.85 on content words, then exact-row dedupe.

Every pass reports counts (`duplicates`, `noise`, `verbatim`) so the caller can reject an
over-aggressive run.

### 4.3 `decompile` — English

One-to-one expansion: rules become "You must / You must never", tables become "text; confidence
0.95; source …". The output is intentionally plain and still skimmable, so a human can audit a
Loom packet without learning the syntax.

### 4.4 Model-backed compilation

For free-form prose the intended production path is an LLM rewrite with the prompt in
[`SPEC.md`](SPEC.md). The deterministic compiler exists because it is testable, runs offline,
and gives the LLM path an oracle to compare against.

---

## 5. What we deliberately did not do

| Rejected | Why |
|---|---|
| A symbolic/positional DSL | 9–14pp accuracy loss in agentic benchmarks; models are not trained on it |
| Binary or base64 packing | Unreadable, unrepairable, and terrible for prefix caching |
| Deep nesting | Accuracy collapses on nested retrieval; every level costs delimiters |
| Token-level pruning of prose | Breaks grammar and drops unrecoverable information |
| Always-on summarisation | Irreversible and unauditable; `distill` is opt-in instead |
| Reordering by relevance each turn | Destroys the prefix cache; token savings can be net-negative |

---

## 6. Known failure modes

1. **Misclassification.** A sentence containing "must" inside a question ("does it must…") can
   become a rule. Mitigation: lint detects `must`/`never` contradictions; classification is
   conservative and auditable.
2. **Terse distortion.** Removing articles can make a clause ambiguous. Mitigation: negation,
   numbers, paths and quoted strings are never rewritten; fidelity harness checks literals.
3. **Eviction of the one thing you needed.** Priority is a heuristic. Mitigation: `~elided`
   markers let the agent request the missing section instead of guessing.
4. **Format unfamiliarity.** A model that has never seen Loom may mis-parse it. Mitigation:
   `--legend` adds a one-line key; the surface stays English-like so zero-shot parsing works.
5. **Short-context overhead.** Below ~1k tokens the header cost can exceed the savings. Measure
   before deploying; do not apply Loom to a 200-token prompt.
6. **Non-English sources.** Loom is English-shaped. The literature suggests translating first,
   then compressing, rather than inventing per-language notation.

---

## 7. Roadmap

- **Accuracy eval** (blocking): run the protocol in `EVALS.md` on tool-calling and QA suites.
- **Content-addressed refs**: `#refs` + `@h1a2` for repeated file blobs and large tool output.
- **Delta state**: `^key = value` so a turn sends only what changed.
- **Learned eviction**: replace the hand-tuned priorities with a small scorer trained on
  downstream accuracy.
- **Constrained decoding**: a grammar so models emit valid Loom on the first try (see
  metamodel-guided decoding results, [arXiv:2610.29749](https://arxiv.org/html/2610.29749v1)).
- **Multilingual**: canonical English intermediate, per the translate-then-compress result.

---

## References

1. Liu et al. *Lost in the Middle: How Language Models Use Long Contexts.* TACL 2024. https://aclanthology.org/2024.tacl-1.9/
2. Chroma. *Context Rot.* 2025. https://research.trychroma.com/context-rot
3. Anthropic. *Effective context engineering for AI agents.* 2025. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
4. Jiang et al. *LLMLingua.* EMNLP 2023. https://arxiv.org/abs/2310.05736
5. Jiang et al. *LongLLMLingua.* ACL 2024. https://aclanthology.org/2024.acl-long.91/
6. *SCOPE: A Generative Approach for LLM Prompt Compression.* COLM 2026. https://arxiv.org/abs/2508.15813
7. Kutschka & Geiger. *Notation Matters: Token-Optimized Formats in Agentic AI Systems.* 2026. https://arxiv.org/abs/2605.29676
8. Matveev. *TOON vs JSON: A Benchmark of Plain and Constrained Decoding Generation.* 2026. https://arxiv.org/abs/2603.03306
9. *Lost-in-the-Middle in Long-Text Generation (RAL-Writer).* 2025. https://arxiv.org/abs/2503.06868
10. Lukauskas. *Lost in Compression: A Cross-Lingual Audit of Extractive Prompt Compressors.* 2026. https://arxiv.org/abs/2608.26175
11. Xia et al. *Diagnosing and Mitigating Context Rot in Long-horizon Search.* 2026. https://arxiv.org/abs/2606.29718
12. *Metamodel-Guided LLM Decoding for Consistent DSL Generation.* 2026. https://arxiv.org/html/2610.29749v1
