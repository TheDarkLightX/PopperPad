# Zeno-ADP cross-check vectors

`src/popperpad/core/robust_prefix.py` is a standard-library port of Zeno-ADP 0.8.0's
`robust_prefix::zero_regret` and `within_budget`, which `core.experiment_plan` uses to
choose the next checks. This directory holds the Rust program that asks
[Zeno-ADP](https://github.com/TheDarkLightX/Zeno-ADP) itself for the answers.
`tests/test_robust_prefix.py` requires the port to match every one exactly.

The vectors are 120 seeded random plan charts and the 12 charts that
`core.experiment_plan.experiment_chart` builds for seeded requests.

```sh
python3 tools/zeno_adp_vectors/regenerate.py --check
python3 tools/zeno_adp_vectors/regenerate.py --zeno-adp-path ../Zeno-ADP   # a local v0.8.0 checkout
```

PopperPad does not depend on Rust or Zeno-ADP at runtime.
