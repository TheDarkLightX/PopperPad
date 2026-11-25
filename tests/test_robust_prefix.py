from __future__ import annotations

import json
from pathlib import Path

import pytest

from popperpad.core.robust_prefix import (
    PlanChart,
    Step,
    regret,
    within_budget,
    zero_regret,
)

VECTORS = json.loads((Path(__file__).parents[1] / "vectors" / "zeno_adp_0_8_0.json").read_text(encoding="utf-8"))
CASES = VECTORS["robust_prefix"] + VECTORS["experiment_charts"]


def _chart(case: dict) -> PlanChart:
    cells = tuple(tuple(Step(tuple(r["costs"]), r["credit"], r["child"]) for r in rules) for rules in case["cells"])
    return PlanChart(cells=cells, root=case["root"], worlds=case["worlds"])


def _pairs(rules):
    return None if rules is None else [list(p) for p in rules]


@pytest.mark.parametrize("case", CASES, ids=lambda c: str(c["case"]))
def test_port_matches_zeno_adp(case: dict) -> None:
    chart = _chart(case)
    zero, expected = zero_regret(chart), case["zero_regret"]
    assert (zero.best_credit, str(zero.count)) == (expected["best_credit"], expected["count"])
    assert _pairs(zero.prefix) == expected["prefix"]
    assert _pairs(zero.common_plan) == expected["common_plan"]
    assert [_pairs(c) for c in zero.completions] == expected["completions"]
    within, expected = within_budget(chart, tuple(case["budget"])), case["within_budget"]
    assert (within.best, str(within.count)) == (expected["best"], expected["count"])
    assert _pairs(within.prefix) == expected["prefix"]
    assert list(within.regret) == expected["regret"]


def test_vectors_exercise_ties_budgets_and_missing_common_plans() -> None:
    assert sum(int(c["zero_regret"]["count"]) > 1 for c in CASES) >= 10
    assert sum(c["zero_regret"]["common_plan"] is None for c in CASES) >= 10
    assert sum(c["within_budget"]["best"] > c["zero_regret"]["best_credit"] for c in CASES) >= 10
    assert len(VECTORS["experiment_charts"]) == 12


@pytest.mark.parametrize(
    "build",
    [
        lambda: Step((), 0),
        lambda: Step((1,), -1),
        lambda: Step((1.5,), 0),  # type: ignore[arg-type]
        lambda: PlanChart(cells=((Step((1,), 0, 0),),), root=0, worlds=1),
        lambda: PlanChart(cells=((Step((1, 2), 0),),), root=0, worlds=1),
        lambda: PlanChart(cells=((),), root=0, worlds=1),
        lambda: PlanChart(cells=((Step((1,), 0),),), root=1, worlds=1),
    ],
)
def test_malformed_charts_are_rejected(build) -> None:
    with pytest.raises((TypeError, ValueError)):
        build()


def test_regret_and_budget_are_per_world() -> None:
    # A step with slack (0, 3), then one with slack (3, 0): together each world pays 3.
    chart = PlanChart(
        cells=(
            (Step((0, 0), 0), Step((3, 0), 1)),
            (Step((0, 3), 1, 0), Step((0, 0), 0)),
        ),
        root=1,
        worlds=2,
    )
    assert regret(chart, ((1, 0), (0, 1))) == (3, 3)
    assert within_budget(chart, (2, 2)).best == 0  # the first step alone costs world 1 three
    assert within_budget(chart, (0, 3)).best == 1  # it fits world 1's budget, the second step does not fit world 0's
    assert within_budget(chart, (3, 0)).best == 0
    assert within_budget(chart, (3, 3)).best == 2
    with pytest.raises(ValueError):
        within_budget(chart, (1,))
