# Provenance and check planning

Status: proposed (draft PR).

Two read-only questions about a hypothesis's graph status. Neither one runs a recipe,
records an object or changes a status.

1. **Provenance:** why is this hypothesis supported, falsified or disputed, and what is the
   least you would have to remove to change that?
2. **Check planning:** for hypotheses that are still unknown, which recipe should run next
   so the plan stays good whichever hypotheses turn out true?

Both live in the functional core as pure functions over immutable values. The shell only
gathers inputs and prints results.

## Provenance

`core.provenance.derive_provenance(snapshot)` takes the same `StatusSnapshot` as
`core.graph.derive_status`.

A **derivation** is one reason a status counts. It pairs a support or refute edge with one
evidence record that admits that edge under the hypothesis's accepted recipes. Both
functions use the same admission rule, `core.graph.admitting_evidence`. So the derived state
always equals `derive_status`. The provenance function asserts this, and a property test
checks it on random snapshots.

Each derivation uses exactly one item of each kind: one edge, one evidence record, one
recipe and one source (the edge's `from_ref`). For one side (supports or refutes) and one
kind:

- **Cut.** Removing every distinct item of that kind removes all of that side's
  derivations. Nothing smaller of that kind does. The number of those items is the side's
  cut size for that kind.
- **Single point of failure.** A cut of size 1.
- **Shared items.** The items that every derivation of that side uses.

For example, two independent evidence records from the same recipe give an evidence cut of
2 but a recipe cut of 1. The support rests on one verification method.

`changes` lists, for each side and kind, the state the hypothesis would reach if that cut
were removed. Removing a source removes its edges on both sides. Changes are sorted by cut
size. `smallest_change` is the least cut size.

**Boundary.** Cuts are exact for one kind at a time. A cut that mixes kinds can be smaller,
and finding the smallest one is a hitting-set problem, so it is not reported.

CLI:

```bash
popperpad provenance --pad ./pad <hypothesis_ref> --context <context_ref>
```

## Check planning

`core.experiment_plan.plan_experiments(request)` takes:

- up to 6 unknown hypotheses;
- up to 8 candidate checks, each pairing a hypothesis, one of its accepted recipes, the
  recipe's `verdict_on_pass` and a positive integer cost;
- a `pending_cost` charged for each hypothesis still unsettled when you stop;
- a `regret_budget`.

A **world** fixes which hypotheses hold, so there are 2^k worlds for k hypotheses.

Checks are treated as sound but incomplete. A passing check settles its hypothesis; a
failing check settles nothing. So where a hypothesis holds, its support checks pass and its
refute checks fail. Where it does not hold, the reverse happens. No world is assumed more
likely than another, and outcomes are never assumed independent.

The plan is a finite chart. A cell is the set of checks already run in a fixed order. Each
step either runs one more check or stops. The planner answers over every world at once:

| Field | Meaning |
|---|---|
| `first_check` | The check whose worst-case regret is least. Regret is the extra cost over that world's best plan. |
| `first_check_regret` | That worst-case regret. |
| `run_now` | The zero-regret prefix: checks that keep an optimal plan in every world. |
| `tied_prefixes` | How many zero-regret prefixes tie for longest. |
| `one_plan_optimal_in_every_world` | Whether a single complete plan is optimal in all worlds. |
| `common_plan` | That plan, when it exists. |
| `within_budget` | The longest commitment whose extra cost stays within `regret_budget` in every world. |
| `within_budget_regret` | Its regret in each world. |

A failing check is wasted in every world where it fails. So `run_now` is empty unless some
check passes in every world, which a falsification plan rarely has. The regret-bounded
answers (`first_check`, `within_budget`) are the useful ones.

For example, take one hypothesis with a refute check of cost 1, a support check of cost 5
and `pending_cost=10`. Running the refute check first costs 1 extra where the hypothesis
holds and settles it where it does not. Starting with the support check would cost 5 extra
where the hypothesis fails. So `first_check` is the refute check with regret 1, and
`within_budget` with budget 1 commits to it with per-world regret `(1, 0)`.

From the pad, `PopperPad.plan_checks` plans only hypotheses whose status is unknown. A
check's default cost is the recipe's `timeout_ms` rounded up to whole seconds, with a
minimum of 1. That is a rough proxy, so `--cost REF=INT` overrides it per recipe.

CLI:

```bash
popperpad plan-checks --pad ./pad <hypothesis_ref>... --context <context_ref> \
  --pending-cost 3 --regret-budget 1 --cost <recipe_ref>=2
```

**Boundary.** The planner reasons about which checks to run, not about whether a recipe is
correct. Its answers are only as good as the costs supplied and the soundness of each
recipe's verdict.

## Cross-check against Zeno-ADP

`core.robust_prefix` is a Python port of `robust_prefix` from
[Zeno-ADP](https://github.com/TheDarkLightX/Zeno-ADP) 0.8.0. PopperPad does not depend on
it at run time.

`tools/zeno_adp_vectors` builds a small Rust program against the tagged release. It writes
`vectors/zeno_adp_0_8_0.json`:

- 120 seeded random plan charts with ties, budgets and missing common plans;
- the 12 charts that `experiment_chart` builds from seeded requests, with 2, 4 and 8 worlds.

`tests/test_robust_prefix.py` requires the port to match every field, including tie counts
as exact integers.

To regenerate the vectors, or to confirm they still match:

```bash
python3 tools/zeno_adp_vectors/regenerate.py --check
```
