# PopperPad tutorial and marketing copy

## Tutorial titles

1. **From Unknown to Disputed: The Real PopperPad CLI Workflow**
2. **Append Evidence, Not Verdicts: A PopperPad Walkthrough**
3. **Finding and Retaining Counterexamples with PopperPad**
4. **Content-Addressed Research: Inside a PopperPad Ledger**
5. **Replay, Checkpoint, Doctor: Verifying a PopperPad**
6. **Transfer Paths: Connecting Knowledge Across Domains**

## Short hooks

- Keep hypotheses immutable while evidence continues to accumulate.
- Derive support and falsification from checks that another agent can replay.
- Preserve counterexamples as content-addressed artifacts instead of burying
  them in chat history.
- Let conflicting evidence remain visible as a first-class disputed state.
- Move ideas across domains with typed semantic edges and explicit obligations.
- Verify the CAS, append-only log, references, and schema graph with one command.

## Feature-reel voiceover

PopperPad is an append-only, falsification-first knowledge ledger for agents and
research workflows. Add immutable domains, recipes, contexts, and hypotheses.
Run a support recipe and the ledger derives supported status. Run a refuter and
retain the counterexample as evidence. When both survive, PopperPad says
disputed—not whichever answer arrived last. Content-addressed blobs, typed
semantic edges, checkpoints, and doctor checks make the resulting knowledge
graph local, inspectable, and replayable.

## Suggested captions

### Append-only ledger

Each domain, recipe, and hypothesis is validated, content-addressed, and appended
to a hash-chained log.

### Replayable support

`prove` runs only support recipes and emits evidence plus typed support edges;
`status` derives the resulting state.

### Falsification

`refute` runs refuter recipes, captures a counterexample artifact, and records a
typed refutation edge.

### Disputed status

PopperPad retains both surviving evidence paths and derives `disputed` instead
of overwriting one with the other.

### Semantic transfer

`transfer-paths` finds bounded routes across typed semantic edges and reports any
open proof or check obligations.

### Integrity

`doctor` verifies the hash chain, CAS objects and blobs, schemas, and graph
references. It does not certify the truth of a scientific claim.

