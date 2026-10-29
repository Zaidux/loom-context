# Evaluation protocol

Loom makes two claims. Only one of them is measured today.

| Claim | Status |
|---|---|
| It reduces tokens at equal hard-fact fidelity | **measured** (`bench/eval.py`) |
| It improves or preserves downstream task accuracy | **not yet measured** — this document is the protocol |

The second claim is the one that matters, and the one most compact formats fail. Do not ship
Loom on the strength of the token numbers alone.

---

## 1. Hypotheses

- **H1 — compression at equal fidelity.** For contexts ≥ 1,000 tokens, Loom reduces input
  tokens by ≥ 30% with ≥ 98% of hard literals preserved.
- **H2 — non-inferior accuracy.** On tool-calling and constraint-following tasks, Loom is
  non-inferior to the raw-English baseline within a 2pp margin, and superior when the baseline
  exceeds the effective context (i.e. contains distractors or sits past the model's reliable
  window).
- **H3 — position robustness.** When a critical constraint is placed mid-context, Loom's
  head/tail placement raises constraint recall versus raw English.
- **H4 — noise robustness.** With irrelevant evidence added, Loom's explicit `trust` and
  eviction improve answer accuracy versus an equal-token raw-English truncation.

---

## 2. Test suites

| Suite | Size | What it measures | Grading |
|---|---:|---|---|
| **Constraint compliance** (synthetic) | 300 tasks | Does the model respect every `!must`/`!never`? | deterministic: inspect final diff/args/plan |
| **Needle-in-context** | 200 probes | Recall of one fact placed at head/middle/tail | exact match |
| **Tool-call accuracy** | BFCL + MCPToolBenchPP subset | Correct tool, correct arguments | official validators |
| **Long-horizon** | 50k / 200k accumulated context | Premature answer rate, task completion | rubric + deterministic end-state |
| **Round-trip fidelity** | all examples | Literals and modality survive translation | `bench/eval.py` |

The constraint suite is the most important and the cheapest to build. Sketch:

```yaml
task: migrate-billing-client
context_noise: 6 irrelevant tool outputs
rules:
  - id: r1
    text: "never rotate the Stripe API keys"
    check: "no write to secrets/**"
  - id: r2
    text: "keep the legacy event schema"
    check: "schema_hash == baseline"
gold_action: "enable feature flag in staging"
distractors: ["delete the legacy adapter", "rotate keys now"]
```

Each task is run three ways, at **equal token budget** so the comparison is fair:

1. `raw` — the full English context.
2. `raw_truncated` — the same budget, truncated by recency (the common baseline).
3. `loom` — rendered under the same budget.

If Loom only wins against `raw` (which is longer) it has not proven anything.

---

## 3. Metrics

**Primary**

- `task_accuracy` — graded success.
- `constraint_adherence` — fraction of rules respected (binary per rule, then averaged).
- `premature_answer_rate` — answers given while `?q` unknowns are unresolved.

**Secondary**

- `input_tokens`, `output_tokens`, `cost_usd`
- `latency_p50/p95`
- `parse_failure_rate` — invalid Loom emitted or read
- `cascade_rate` — a parse failure that poisons the next turn (the failure mode that hit TOON)
- `fidelity` — hard-literal survival

---

## 4. Protocol

1. Pin one model family, two sizes (e.g. a small and a large variant). Report both.
2. Temperature 0, three seeds, paired design: same task, same order, only the context form
   differs.
3. Budget-match all conditions (H1 aside, where the point is the saving).
4. Grade deterministically where possible. Where a judge is unavoidable, use two judges and
   human-audit a random 10%.
5. Report **paired bootstrap 95% CIs**, not just means. n ≥ 300 per cell.
6. Publish the failing examples. A format that hides its failures is not a format, it is a demo.

---

## 5. Current harness

`bench/eval.py` measures tokens and literal fidelity only:

```bash
python bench/eval.py \
  --pair examples/transcript.txt examples/transcript.loom \
  --pair examples/migration_english.md examples/migration_distilled.loom
```

Output on the checked-in examples:

| case | source | Loom | saving | fidelity |
|---|---:|---:|---:|---:|
| `auth_refresh` | 272 | 234 | 14.0% | 100% |
| `migration_english` (`compile`) | 528 | 492 | 6.8% | 100% |
| `migration_english` (`distill`) | 528 | 439 | 16.9% | 100% |
| `transcript` | 672 | 405 | 39.7% | 100% |

These are small, author-written cases. They demonstrate the mechanics, not the effect size.
H1 requires the suite above at ≥ 1k tokens.

### 5.1 Real sessions

`bench/sessions.py` covers H1 at scale on real data: 27 Riciplay CLI sessions (3,849 tool calls)
read from a local corpus path at runtime and never committed. Each record is projected into Loom
by `loom/session.py`; fidelity is computed over *all scalar leaves* of the original record,
independently of the encoder, so a field the encoder forgets shows up as a miss.

```bash
python bench/sessions.py                # table
python bench/sessions.py --json         # machine-readable rows
python bench/sessions.py --show-missing # what did not survive, per session
```

| representation | tokens | saving | leaf fidelity |
|---|---:|---:|---:|
| raw JSON (`indent=2`) | 922,618 | — | 100% |
| minified JSON | 823,422 | 10.8% | 100% |
| **Loom** | **713,881** | **22.6%** | **96.0%** |
| raw JSON truncated to Loom's budget | — | equal budget | **69.8%** |

The last row is the important control: it answers "would truncating the original have been as
good?" It would not. Structure retains ~26pp more of the record at the same token cost.

The 4% leaf loss comes from long, JSON-escaped tool output that the encoder normalises onto a
single line. It is deliberate (Loom is line-oriented) and visible in `--show-missing`; it is not
a silent drop of structured fields.

H1's ≥ 30% target is **not** met on this corpus. Real sessions are dominated by unique tool
output, which no whitespace-only scheme can compress much further. The honest claim is
"20–25% against raw JSON, 13% against minified JSON, with far better retention at a fixed
budget", not 30%.

### 5.2 Output-side encoding

`bench/output.py` measures the mirror case: the agent writes Loom instead of English. It runs
the same codec over five fixed sample answers (three examples, two synthetic reports).

| answer form | tokens | vs English | literal fidelity |
|---|---:|---:|---:|
| English | 2,676 | — | 100% |
| Loom, lossless `compile` | 2,588 | 3.3% | 100% |
| Loom, lossy `distill` | 2,158 | 19.4% | 96.0% |
| Loom locally expanded back to English | 2,010 | 24.9% | 96.0% |

What this establishes: the token saving is the same as the input side for the same text, and
there is no separate output-side effect. The apparent 15.9% expansion saving is distillation,
not notation — it is cheaper because content was dropped, and fidelity shows it.

What this does **not** establish: that a model will emit valid Loom, that it will emit it without
being asked twice, or that the answer is as good. Those need a model run and a grader; the
prompt is in `SPEC.md` §5.3. Until then, treat output mode as an interface option, not a
measured improvement.


### What fidelity does and does not catch

It checks a regular-expression set of numbers, paths, identifiers and quoted strings. It will
catch a dropped API key or threshold. It will **not** catch:

- a dropped negation ("do not retry" → "retry"),
- a weakened modality ("must" → "should"),
- a lost causal relation.

Those are exactly why H2 needs a downstream run. The distiller's terse pass is written to never
rewrite negation, numbers, paths or quotes, but "written to" is not "proven".

---

## 6. Threats to validity

| Threat | Mitigation |
|---|---|
| Token counts vary by tokeniser | report `tokenizer_name()`; re-run with the target model's tokeniser |
| Format novelty inflates first-turn cost | include a `--legend` condition; measure multi-turn |
| Synthetic tasks leak the format | hold out task templates; use real repo issues where possible |
| Judge bias | deterministic graders first; dual judges; human audit |
| Short-context overhead | report ratio vs context length; state the break-even point |
| English-only | Loom is English-shaped; the cross-lingual audit suggests translate-then-compress |
| Prefix-cache effects | measure cost, not just tokens; a reordered prefix can cost more than it saves |

---

## 7. Results log

| Date | Run | n | Result |
|---|---:|---:|---|
| — | token + fidelity, curated pairs (this repo) | 4 pairs | 6.8–39.7% saving, 100% fidelity |
| — | token + fidelity, real Riciplay sessions | 27 sessions / 3,849 calls | −22.6% vs raw JSON, −13.3% vs minified, 96.0% leaf fidelity; equal-budget truncation 69.8% |
| — | Python vs Rust parse+render, 113k-token session | 500 iterations | ~20× in-process speedup, 4.26 ms/op |
| — | End-to-end backend crossover (spawn included) | 1k–32k words | ~0.7× → ~8×; threshold 4k chosen |
| — | Output-side encoding (Loom as the answer) | 5 samples | 3.3% lossless, 19.4% lossy at 96.0% fidelity |
| — | constraint compliance | — | not run |
| — | tool-call accuracy | — | not run |
| — | long-horizon context rot | — | not run |

Append rows here as runs complete; keep the raw JSON next to this file.
