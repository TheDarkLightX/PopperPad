# PopperPad

PopperPad is an append-only, falsification-first knowledge ledger for LLM/agent swarms.

It is designed to be:
- **Offline-first**: local directory, no services required.
- **Fail-closed**: “verdicts” are derived from replayable evidence, not asserted.
- **Tool-optional**: checks can use standard CLIs (`z3`, `cvc5`, `lean`, etc.) when available; missing tools produce `SKIP` evidence.
- **Graph-native**: knowledge is a typed multigraph over immutable (content-addressed) objects.

## Model (3 layers)

1. **CAS / Merkle objects**: immutable objects addressed by `sha256:<hex>` of canonical bytes.
2. **Append-only log**: JSONL event log chained by `prev_record_hash`.
3. **Derived semantic graph**: nodes + typed edges + evidence bundles; KRR happens by querying this graph and replaying evidence.

## Key ideas

- Agents record **hypotheses** with explicit **check recipes**.
- Running a recipe emits an **evidence object** (stdout/stderr + captured artifacts + pass/fail/skip).
- “Supported / falsified / disputed” is computed from evidence (and optional `refutes` edges), not written as truth.
- Cross-domain transfer is represented by first-class **semantic edges** tagged with `≅/↦/⊑/⊒/~` plus explicit proof/check obligations.

## Recipe capabilities (v1)

`popperpad/recipe/v1` supports:
- Tool-optional execution via `requires` / `requires_paths` (missing tools ⇒ `SKIP` evidence).
- Input materialization via `files` and optional `stdin` (`ref`/`text`/`binding`).
- Expectations beyond exit codes: `stdout_contains`, `stderr_contains`, `*_not_contains`, `*_regex`, `files_exist`, `files_not_exist`.
- Artifact capture via `capture_paths` and named `artifacts` (per-artifact `max_bytes`, plus `max_capture_bytes` default).

Evidence records include captured blob refs plus run metadata (argv, duration, toolchain hashes, truncation flags).

## CLI (MVP)

Install (editable):

```bash
pip install -e .[dev]
```

Codex skills (optional):

- Skill folders live under `skills/` (`popperpad-core`, `popperpad-formal-tools`).
- Install by copying/symlinking into `$CODEX_HOME/skills/` (or your agent framework’s skills directory).

Create a pad:

```bash
popperpad init --pad ./pad
```

Add objects:

```bash
popperpad add --pad ./pad --json hypothesis.json
popperpad add --pad ./pad --json recipe.json
```

Run checks:

```bash
popperpad prove  --pad ./pad <hypothesis_ref> --context <context_ref>
popperpad refute --pad ./pad <hypothesis_ref> --context <context_ref>
```

Inspect:

```bash
popperpad status  --pad ./pad <hypothesis_ref> --context <context_ref>
popperpad doctor  --pad ./pad
popperpad checkpoint --pad ./pad
```

Blobs (large artifacts):

```bash
popperpad blob-put --pad ./pad --path ./artifact.bin --media-type application/octet-stream
popperpad blob-get --pad ./pad sha256:... --out ./artifact.bin
```

Transfer:

```bash
popperpad transfer-paths --pad ./pad --from <domain_ref> --to <domain_ref> --max-depth 4
```

## Media kit

The repository includes a reproducible
[`media-kit`](media-kit/README.md) with authentic CLI workflows, terminal stills
and videos, fictional example photos, tutorial copy, and publishing guardrails.

## Schemas

JSON Schemas live under `schemas/v1/` (no runtime dependency on `jsonschema`).
