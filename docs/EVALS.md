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
| — | token + fidelity (this repo) | 4 pairs | 6.8–39.7% saving, 100% fidelity |
| — | constraint compliance | — | not run |
| — | tool-call accuracy | — | not run |
| — | long-horizon context rot | — | not run |

Append rows here as runs complete; keep the raw JSON next to this file.
