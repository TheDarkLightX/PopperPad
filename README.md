# PopperPad

PopperPad is scientific memory for humans and agents: an append-only,
falsification-first knowledge ledger for hypotheses, recipes, evidence,
counterexamples, artifacts, and typed relationships between claims.

> [!WARNING]
> **Public alpha: run only recipes and bundles you have written or audited.**
> Recipe execution currently invokes host subprocesses and is not an operating-system
> sandbox. A temporary working directory does not prevent filesystem access, network
> access, environment-secret access, or uncontrolled child processes. Do not execute
> untrusted third-party recipes. Remote signatures, hostile bundle import, automated
> bounty settlement, and trustless federation are not production security boundaries yet.

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
- Verifiers such as Lean, Z3, replay harnesses, fuzzers, or benchmark runners
  decide scoped check results. PopperPad stores those proof-carrying results and
  derives “supported / falsified / disputed” graph status from them.
- Cross-domain transfer is represented by first-class **semantic edges** tagged with `≅/↦/⊑/⊒/~` plus explicit proof/check obligations.

## Scientific memory

PopperPad does not make claims true. It stores the knowledge of verifier-checked
truths, refutations, reproductions, skips, and disputes. It preserves the
evidence needed to ask:

- what exactly was claimed;
- how the claim can be checked;
- what evidence supports or refutes it;
- which context, toolchain, dataset, or harness produced the evidence;
- which newer claim supersedes or narrows an older claim;
- who or what attested to the result.

The core discipline is local-first and append-only. Users can keep private pads,
mirror public pads, or import remote evidence while applying their own trust
policy.

## Decentralization and falsification markets

PopperPad can grow from a local scientific-memory tool into decentralized
scientific infrastructure. The recommended path is:

1. keep PopperPad objects content-addressed and locally verifiable;
2. publish bundles to IPFS or other content-addressed storage;
3. anchor bundle roots on Tau Net, EVM chains, Bitcoin timestamping layers,
   Solana, Cosmos, Substrate chains, Arweave, Filecoin, and other immutable
   substrates through adapters;
4. use token or credit fuel immediately for real network costs: storage,
   compute, model calls, verifier runs, indexing, and agent labor;
5. add smart-contract escrow for bounties, bonds, challenge windows, and
   settlement events;
6. introduce a native PopperPad token only if the epistemic-work economy grows
   enough to need its own monetary policy.

The token, chain, and Pad must not decide truth by themselves. Verifiers decide
scoped check results. PopperPad stores the resulting knowledge and derives graph
status from verifier evidence, context, recipes, signatures, and local trust
policy.

Design specs:

- [Falsification market](docs/falsification-market.md)
- [Algorithmic game theory decentralization](docs/algorithmic-game-theory-decentralization.md)
- [Token fuel economics](docs/token-fuel-economics.md)
- [Gamification economics](docs/gamification-economics.md)
- [Decentralized adapter](docs/decentralized-adapter-spec.md)
- [IPFS adapter](docs/ipfs-adapter-spec.md)
- [Blockchain anchor adapter](docs/blockchain-anchor-spec.md)
- [Chain adapter matrix](docs/chain-adapter-matrix.md)
- [Tau Net adapter](docs/tau-net-adapter-spec.md)

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
