# Kurate discovery adapter

The Kurate adapter is a read-only literature-discovery input for PopperPad. It
does not turn a ranking into scientific evidence.

## Authority boundary

Every imported paper uses the shared schema
`research-discovery/candidate/v1` and the authority label `triage_only`.
PopperPad deliberately keeps this schema outside its hypothesis, evidence, and
edge schemas. Therefore a discovery candidate cannot change derived support or
falsification status.

The candidate receipt matches the schema emitted by Research Kernel MCP. It
preserves:

- the exact arXiv identifier and its version-free work key;
- all currently recognized Kurate metrics, including null values;
- scores as integer milli-points from 0 through 10,000;
- the bounded query, result position, Kurate URLs, and snapshot hash.

This shared receipt lets downstream workflows compare the two adapters without
translating score or identity fields. Each system still applies its own import
and validation path. The common schema does not grant either tool promotion
authority.

## Bounded import

```bash
popperpad kurate-discover --pad ./pad \
  --search "formal verification" \
  --category cs.LO \
  --sort-key refutation_value \
  --sort-dir desc \
  --limit 10
```

The adapter:

1. permits only HTTPS requests to `kurate.org`;
2. limits a query to 40 rows and a response to 4 MiB;
3. rejects duplicate JSON keys, unknown rating fields, malformed identifiers,
   out-of-range scores, and duplicate paper candidates;
4. preserves null metrics instead of inventing scores;
5. commits candidates, the batch receipt, and exact response bytes atomically;
6. records network failure and schema drift as `UNKNOWN` negative knowledge.

The endpoint is public but not a versioned PopperPad contract. Upstream schema
drift is quarantined until the adapter and tests are deliberately updated.

## Promotion workflow

A candidate is a pointer for investigation. A separate workflow must:

1. retrieve and identify the exact primary source;
2. state a falsifiable hypothesis;
3. define one or more replayable check recipes;
4. run independent formal, computational, empirical, or review checks;
5. attach the resulting evidence through PopperPad's ordinary evidence path.

Kurate's assessment can help choose what to inspect first. It cannot satisfy
any of those obligations.
