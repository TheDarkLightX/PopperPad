---
name: popperpad-formal-tools
description: Use PopperPad recipes to run formal and semi-formal tools (Z3, CVC5, Lean, Isabelle) and capture replayable evidence/counterexamples in an append-only pad; trigger when turning a claim into a solver/prover check, designing tool-optional recipes, or recording portable proof/counterexample artifacts.
---

# PopperPad Formal Tools

## Core pattern (portable, fail-closed)

- Put the checker input(s) under `recipe.files` (inline `text` or `ref` to a CAS blob).
- If a tool wants stdin, use `recipe.stdin` (`ref`/`text`/`binding`).
- Use `recipe.requires` so missing tools produce `SKIP` evidence (no hard dependencies).
- Prefer `expect.stdout_contains` over exit codes when tools always exit `0`.
- Capture counterexamples/models/proof artifacts via `capture_paths` (simple) or named `artifacts` (supports per-file `max_bytes` + `media_type`).
- Use `expect.stdout_regex` / `stderr_regex` and `*_not_contains` for tighter checks when tool output is noisy.

## SMT (Z3 / CVC5) recipes

Z3 (expect `unsat`):

```json
{
  "schema":"popperpad/recipe/v1",
  "recipe_id":"z3_unsat",
  "verdict_on_pass":"support",
  "requires":["z3"],
  "argv":["z3","-smt2","query.smt2"],
  "files":{"query.smt2":{"text":"(set-logic QF_UF)\n(assert false)\n(check-sat)\n"}},
  "expect":{"exit_code":0,"stdout_contains":"unsat"}
}
```

CVC5 (expect `sat`):

```json
{
  "schema":"popperpad/recipe/v1",
  "recipe_id":"cvc5_sat",
  "verdict_on_pass":"refute",
  "requires":["cvc5"],
  "argv":["cvc5","--lang","smt2","query.smt2"],
  "files":{"query.smt2":{"text":"(set-logic QF_UF)\n(declare-fun p () Bool)\n(assert p)\n(check-sat)\n"}},
  "expect":{"exit_code":0,"stdout_contains":"sat"}
}
```

If you need a model file, wrap the solver with a one-shot script that writes `model.txt` and add `capture_paths:["model.txt"]`.
If the model/counterexample is large, cap capture size with `max_capture_bytes` or per-artifact `max_bytes`.

## Lean recipes

Lean (single file, no extra deps):

```json
{
  "schema":"popperpad/recipe/v1",
  "recipe_id":"lean_ok",
  "verdict_on_pass":"support",
  "requires":["lean"],
  "argv":["lean","Main.lean"],
  "files":{"Main.lean":{"text":"theorem t : True := by trivial\n"}}
}
```

Lean + mathlib (toolchain may be local; keep optional):

- Require the tool (`lake`) and any local path you rely on via `requires_paths`.
- Run via a wrapper (single command) like `bash -lc` *or* a `${PYTHON}` script placed in `recipe.files` so you can unpack a project tarball and invoke `lake env lean`.

## Isabelle recipes

Isabelle (process a theory file; environment-dependent, so keep optional):

- Install/download: https://isabelle.in.tum.de/overview.html (ensure the `isabelle` CLI is on `PATH`; quick check: `isabelle version`).

```json
{
  "schema":"popperpad/recipe/v1",
  "recipe_id":"isabelle_process",
  "verdict_on_pass":"support",
  "requires":["isabelle"],
  "argv":["isabelle","process","-T","Foo.thy"],
  "files":{"Foo.thy":{"text":"theory Foo imports Main begin\nlemma \"True\" by simp\nend\n"}}
}
```

## Evidence hygiene for agent swarms

- Always run `popperpad doctor --pad ...` before promoting/reusing anything.
- Record toolchain/harness identity in a `popperpad/context/v1` object (digests) and pass `--context` to `prove/refute`.
- Treat “survived tests” as `supported` (corroborated), not proven; falsifiers win.
