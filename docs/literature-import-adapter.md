# Literature import adapter

The literature adapter imports JSON produced by citracer or MOSAIC. It does not
execute either tool, download papers, or turn search output into scientific
evidence.

## Commands

```bash
popperpad literature-import --pad ./pad --provider citracer --input trace.json
popperpad literature-import --pad ./pad --provider mosaic --input search.json
```

`--input -` reads the exact JSON bytes from standard input.

For a coordinated fleet, use the receipt-bound entry point:

```bash
popperpad-literature-importer \
  --pad PAD --artifact export.json --artifact-sha256 sha256:... \
  --provider citracer --receipt receipt.json \
  --import-id citracer-seed --importer-id popperpad
```

It hashes the frozen input before and after import. The receipt binds the
artifact, provider, import identity, and committed PopperPad references.
Mutation, a digest mismatch, or a rejected import fails closed.

## Imported objects

Every successful import atomically stores:

- the exact provider JSON as a content-addressed blob;
- one `research-discovery/literature-candidate/v1` object per normalized paper;
- citracer edges as `research-discovery/literature-relation/v1` objects;
- one `research-discovery/literature-batch/v1` receipt binding all object refs;
- MOSAIC source errors as batch warnings rather than silently discarding them.

The corresponding JSON Schemas are published under `schemas/v1/`.

A malformed or unsupported export produces a single
`research-discovery/literature-failure/v1` object with status `UNKNOWN`. It
produces no candidates.

## Authority boundary

All four schemas use `authority="triage_only"` and remain outside PopperPad's
hypothesis, evidence, and semantic-edge schemas. A search ranking can prioritize
reading. A parsed citation can suggest a relationship. Neither can support or
refute a hypothesis.

Primary-source review must create a separate hypothesis and use PopperPad's
ordinary recipe and evidence path. The exact provider export remains available
for replay and adapter audits.

## Bounded validation

The adapter rejects duplicate JSON keys, non-finite numbers, unknown providers,
missing paper identities, dangling citracer edges, oversized files, excessive
item counts, and malformed fields. It preserves exact arXiv versions while
using a version-free work key for deduplication.
Missing Boolean metadata remains `null`; absence is not converted into a
negative observation. Unreadable input records `READ_FAILED` without retaining
the local path.

For citracer, an absent retrieval policy is recorded as `unspecified`. The
adapter does not infer that an older trace used a lawful-open-access-only policy.
