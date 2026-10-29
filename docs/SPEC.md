# Loom 1.0 — specification

Status: stable enough to build against; pre-1.0 semantics may still change.

---

## 1. Grammar

EBNF. `text` runs to end of line. Indentation is two spaces; it is cosmetic but emitted
consistently.

```ebnf
document       = header , { line } ;
header         = "@loom" , version ;
version        = digit , { digit | "." } ;

line           = pragma | rule | question | section | comment | blank ;

pragma         = "#use" , text                    (* capability available to the agent *)
               | "!goal" , text                   (* exactly one per document *)
               | "!done" , text                   (* acceptance criteria *)
               | "!rem" , text ;                  (* recap; emitted only by the renderer *)

rule           = ( "!must" | "!never" ) , text ;

question       = "?q" , text ;

section        = section-header , { row } ;
section-header = "#" , name , [ "[" , meta , "]" ] , [ "{" , columns , "}" ] ,
                 [ "~elided" , integer ] ;   (* trailing marker when every row was evicted *)
meta           = pair , { pair } ;                 (* whitespace separated *)
pair           = key , "=" , value ;
columns        = name , { "," , name } ;

row            = kv-row | table-row | list-row ;
kv-row         = indent , key , "=" , value ;
table-row      = indent , cell , { "," , cell } ;
list-row       = indent , [ "-" ] , text ;

comment        = ( ";;" | "//" ) , text ;
```

### Lexical notes

- `name`, `key`: `[A-Za-z_][\w.-]*`.
- `cell`: any text; wrap in `"` when it contains a comma or quote; `""` escapes a quote.
- Blank lines and comments are ignored.
- A pragma or a new section header ends the current section.

---

## 2. Construct semantics

| Construct | Meaning | Evictable | Position |
|---|---|---|---|
| `@loom 1.0` | format + version | no | first |
| `#use X` | capability the agent may call | yes (0.35) | head |
| `!goal` | the single objective; anchors relevance | **no** | head |
| `!done` | observable acceptance criteria | **no** | head |
| `!must X` | hard requirement | **no** | head + recap |
| `!never X` | hard prohibition | **no** | head + recap |
| `?q X` | unresolved unknown; blocks confident action | yes (0.60) | tail |
| `#state` | mutable working facts (`key = value`) | yes (0.85) | body |
| `#defs` | schema/type definitions | yes (0.90) | body |
| `#evidence{...}` | uniform records with `trust`/`salience` | yes (0.50 × trust) | body |
| `#next` | ordered actions | yes (0.70) | body |
| `#refs` | pointers into an external store | yes (0.55) | body |
| `#notes` | background | yes (0.10) | body |
| `~elided n` | marker: `n` rows were removed | n/a | in section (own line, or trailing the header) |

`~elided` is metadata, not data. Parsers skip a `~elided` row and a trailing `~elided n` on a
section header, so a budget-evicted packet is still valid input on the next turn.

Custom section names are allowed; unknown names get priority 0.50 and sort after known ones.

### Why these and not more

Each construct exists because it changes a decision the renderer or the model makes:

- `!must` / `!never` are never evicted → the model cannot lose a constraint under budget.
- `?q` is separated from `#notes` → unknowns are surfaced, not buried, which counters the
  observed failure mode where long-context agents answer prematurely.
- `trust` is a column, not prose → the eviction engine can rank evidence without a model.

There is deliberately no nesting, no inheritance, no expressions, and no binary encoding.

---

## 3. Canonical form

`render()` produces a deterministic serialisation, so diffs are meaningful and prefix caching
works.

1. `@loom <version>`
2. `#use` lines, in source order
3. `!goal`, `!done`, then all `!must` / `!never` in source order
4. sections sorted by: `state, defs, evidence, facts, refs, open, questions, next, plan, notes`,
   then unknown names alphabetically
5. `?q` lines, in source order
6. `!rem` (only if `recap=True`)

Round-trip invariant: `render(parse(render(doc))) == render(doc)`.

---

## 4. Validation

The parser is strict about structure and raises `LoomSyntaxError` with a line number:

| Error | Example |
|---|---|
| content outside a section | a bare sentence between sections |
| wrong cell count | `#evidence{id,src}` with three cells |
| non-`key = value` in a KV section | `#state` row without `=` |

`lint()` adds non-fatal warnings:

- missing `!goal` or `!done`
- empty section
- row longer than 400 chars (move it to `#refs`)
- the same text declared both `!must` and `!never`
- more than 8 open questions

---

## 5. Translator contract

Loom is a *notation*, not a lossy codec: `decompile` preserves meaning, not phrasing. The
contract for both directions:

1. **Never invent** facts, numbers, paths, identifiers, or constraints.
2. **Preserve modality.** "must", "never", "may", "should" stay distinct.
3. **Preserve uncertainty.** Hedges become `?q`, not assertions.
4. **Preserve provenance.** Keep `file:line`, timestamps and trust where present.
5. **Prefer omission over distortion** when a statement does not fit a construct — drop it and
   report it, do not paraphrase it into something stronger.

### 5.1 English → Loom (model-backed prompt)

```
Rewrite the context below as Loom 1.0. Output Loom only.

Rules:
- One !goal, at most one !done.
- Every hard requirement -> !must, every prohibition -> !never. Keep the original wording;
  do not strengthen or weaken modality.
- Unresolved questions -> ?q. Do not answer them.
- Mutable key/value facts -> #state, one per line as `key = value`.
- Uniform records -> #evidence{id,src,trust,text}; put confidence in `trust` if given.
- Ordered actions -> #next, one per line.
- Background that is needed but not actionable -> #notes.
- Keep numbers, paths, identifiers and quoted strings byte-exact.
- Do not add commentary. Do not summarise away a constraint.
```

### 5.2 Loom → English (model-backed prompt)

```
Expand the Loom document below into plain English. Keep every constraint, number, path and
open question. Say "You must" for !must and "You must never" for !never. Render ?q as
unresolved questions. Do not add new facts.
```

### 5.3 Legend

When a model may be unfamiliar with the format, prepend one line:

```
;; loom 1.0 | !goal/!done objective | !must/!never hard rules | ?q unknown | #sections rows
```

`render(..., legend=True)` does this.

---

## 6. Versioning

- The `@loom` line is mandatory for interchange; parsers tolerate its absence for pasted text.
- Adding a construct is a minor version. Changing the meaning or canonical ordering is a major
  version.
- Readers must ignore unknown sections rather than fail, so a newer producer degrades
  gracefully with an older reader.
