---
name: popperpad-core
description: Use PopperPad to maintain an append-only, falsification-first knowledge ledger (hypotheses, recipes, evidence, and typed edges) and to compute derived support/falsification status from replayable checks; trigger when recording agent discoveries, preventing repeated dead ends, or promoting reusable claims with fail-closed evidence.
---

# PopperPad Core

## Minimal workflow (MVP)

- Initialize: `popperpad init --pad ./pad`
- Add objects: `popperpad add --pad ./pad --json <file>.json` (prints the new `sha256:...` ref)
- Run checks:
  - Support: `popperpad prove --pad ./pad <hyp_ref> --context <ctx_ref>`
  - Refute: `popperpad refute --pad ./pad <hyp_ref> --context <ctx_ref>`
- Inspect: `popperpad status --pad ./pad <hyp_ref> --context <ctx_ref>`
- Verify integrity before trusting/promoting: `popperpad doctor --pad ./pad`

## Append-only discipline

- Never edit or delete existing pad files/objects; only add new objects and connect them with edges.
- Supersede instead of mutating: add a new object and add an `edge_type="supersedes"` edge (`from_ref=new`, `to_ref=old`).

## Falsifiability gate (how to model “scientific claims”)

- Encode any promotable claim as a `popperpad/hypothesis/v1` with one or more `check_recipe_refs`.
- If a claim has no concrete test, do not store it as a hypothesis (store it as a plain note/blob in your project instead).

## Tool-optional checks (no hard deps)

- Use `recipe.requires` to skip cleanly if an executable is missing (`SKIP` evidence).
- Use `recipe.requires_paths` to skip if a local toolchain path is missing (e.g. a local mathlib checkout).
- Treat `SKIP` as “no signal”, not support.

## Blobs and artifacts (large evidence)

- Store large files in the pad CAS: `popperpad blob-put --pad ./pad --path <file> --media-type <type>`
- Retrieve later: `popperpad blob-get --pad ./pad <sha256:...> --out <file>`
- Attach metadata with a `popperpad/artifact/v1` object referencing `blob_ref`.

## JSON templates (copy/adjust)

Domain (`popperpad/domain/v1`):

```json
{"schema":"popperpad/domain/v1","domain_id":"demo","name":"Demo domain","tags":["demo"]}
```

Context (`popperpad/context/v1`):

```json
{"schema":"popperpad/context/v1","context_key":"demo:local","domain_ref":null,"toolchain":{},"harness":{}}
```

Recipe (`popperpad/recipe/v1`) using Python (portable baseline):

```json
{"schema":"popperpad/recipe/v1","recipe_id":"py_ok","verdict_on_pass":"support","argv":["${PYTHON}","-c","print('ok')"],"expect":{"exit_code":0,"stdout_contains":"ok"}}
```

Hypothesis (`popperpad/hypothesis/v1`) (must reference at least one recipe):

```json
{"schema":"popperpad/hypothesis/v1","hypothesis_id":"H1","kind":"tactic","title":"My claim","statement":{"lang":"text","body":"..."},"domain_ref":null,"tags":["demo"],"check_recipe_refs":["sha256:..."]}
```

Supersedes edge (`popperpad/edge/v1`):

```json
{"schema":"popperpad/edge/v1","edge_type":"supersedes","from_ref":"sha256:NEW","to_ref":"sha256:OLD","context_ref":null,"evidence_refs":[]}
```
