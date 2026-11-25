"""Choose the next checks to run so the falsification plan stays good in every world.

A *world* fixes which pending hypotheses hold. A check is one accepted recipe of one
hypothesis. Checks are treated as sound but incomplete: a passing check is evidence that
settles its hypothesis, a failing one settles nothing. So in a world where the hypothesis
holds, its support checks pass and its refute checks fail; where it does not hold, the
reverse. Running a check costs its integer cost. Stopping costs ``pending_cost`` for every
hypothesis still unsettled.

Every answer holds over all worlds at once:
- ``first_check`` is the check whose worst-case regret, the extra cost over that world's best
  plan, is least, and ``first_check_regret`` is that regret.
- ``run_now`` is the zero-regret prefix of ``core.robust_prefix``: checks that keep an optimal
  plan in every world.
- ``within_budget`` commits further while each world's extra cost stays within
  ``regret_budget``.

A failing check settles nothing here, so a check is wasted in every world where it fails.
``run_now`` is therefore empty unless a check passes in every world; the regret-bounded
answers are the useful ones. Outcomes are never assumed independent or probable. Nothing is
run or recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from .result import Reject
from .robust_prefix import PlanChart, Step, regret, within_budget, zero_regret
from .values import DeeplyImmutable

MAX_HYPOTHESES = 6
MAX_CHECKS = 8


@dataclass(frozen=True, slots=True)
class CandidateCheck(DeeplyImmutable):
    hypothesis_ref: str
    recipe_ref: str
    verdict_on_pass: str  # support|refute
    cost: int

    def __post_init__(self) -> None:
        for name in ("hypothesis_ref", "recipe_ref"):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise TypeError(f"{name} must be a non-empty string")
        if self.verdict_on_pass not in {"support", "refute"}:
            raise ValueError("verdict_on_pass must be support or refute")
        if type(self.cost) is not int or not 1 <= self.cost <= 1_000_000:
            raise ValueError("check cost must be an integer in 1..1000000")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class ExperimentRequest(DeeplyImmutable):
    hypotheses: tuple[str, ...]
    checks: tuple[CandidateCheck, ...]
    pending_cost: int
    regret_budget: int


@dataclass(frozen=True, slots=True)
class ExperimentPlan(DeeplyImmutable):
    worlds: int
    run_now: tuple[CandidateCheck, ...]
    tied_prefixes: int
    one_plan_optimal_in_every_world: bool
    common_plan: tuple[CandidateCheck, ...] | None
    within_budget: tuple[CandidateCheck, ...]
    within_budget_regret: tuple[int, ...]
    first_check: CandidateCheck | None
    first_check_regret: int | None


def plan_experiments(request: ExperimentRequest) -> ExperimentPlan | Reject:
    hypotheses, checks = request.hypotheses, request.checks
    if not 1 <= len(hypotheses) <= MAX_HYPOTHESES or len(set(hypotheses)) != len(hypotheses):
        return Reject("EXPERIMENT_HYPOTHESES_OUT_OF_BOUNDS", {"limit": MAX_HYPOTHESES})
    if not 1 <= len(checks) <= MAX_CHECKS or len(set(checks)) != len(checks):
        return Reject("EXPERIMENT_CHECKS_OUT_OF_BOUNDS", {"limit": MAX_CHECKS})
    if any(c.hypothesis_ref not in hypotheses for c in checks):
        return Reject("EXPERIMENT_CHECK_FOR_UNKNOWN_HYPOTHESIS")
    if type(request.pending_cost) is not int or not 1 <= request.pending_cost <= 1_000_000:
        return Reject("EXPERIMENT_PENDING_COST_OUT_OF_BOUNDS")
    if type(request.regret_budget) is not int or not 0 <= request.regret_budget <= 1_000:
        return Reject("EXPERIMENT_REGRET_BUDGET_OUT_OF_BOUNDS")
    chart, subsets = experiment_chart(request)
    zero = zero_regret(chart)
    within = within_budget(chart, (request.regret_budget,) * chart.worlds)

    def checks_of(rules) -> tuple[CandidateCheck, ...]:
        chosen = []
        for cell, index in rules:
            child = chart.cells[cell][index].child
            if child is not None:
                chosen.extend(c for c in checks if c in subsets[child] and c not in subsets[cell])
        return tuple(chosen)

    first, first_regret = _first_check(chart, subsets, checks)
    return ExperimentPlan(
        worlds=chart.worlds,
        run_now=checks_of(zero.prefix),
        tied_prefixes=zero.count,
        one_plan_optimal_in_every_world=zero.common_plan is not None,
        common_plan=None if zero.common_plan is None else checks_of(zero.common_plan),
        within_budget=checks_of(within.prefix),
        within_budget_regret=regret(chart, within.prefix),
        first_check=first,
        first_check_regret=first_regret,
    )


def _first_check(chart: PlanChart, subsets, checks) -> tuple[CandidateCheck | None, int | None]:
    """The first check whose worst-case regret over all worlds is least; ties go to check order."""
    best: tuple[int, int, CandidateCheck] | None = None
    root = chart.cells[chart.root]
    for index, step in enumerate(root):
        if step.child is None:
            continue
        (check,) = subsets[step.child] - subsets[chart.root]
        worst = max(regret(chart, ((chart.root, index),)))
        key = (worst, checks.index(check), check)
        if best is None or key[:2] < best[:2]:
            best = key
    return (None, None) if best is None else (best[2], best[0])


def experiment_chart(request: ExperimentRequest) -> tuple[PlanChart, tuple[frozenset[CandidateCheck], ...]]:
    """One cell per set of checks already run, largest sets first, so children come first."""
    checks, hypotheses = request.checks, request.hypotheses
    worlds = tuple(product((True, False), repeat=len(hypotheses)))
    holds = {h: i for i, h in enumerate(hypotheses)}
    masks = sorted(product((0, 1), repeat=len(checks)), key=lambda m: (-sum(m), m))
    subsets = tuple(frozenset(c for c, bit in zip(checks, mask) if bit) for mask in masks)
    index = {s: i for i, s in enumerate(subsets)}

    def passes(check: CandidateCheck, world: tuple[bool, ...]) -> bool:
        return world[holds[check.hypothesis_ref]] == (check.verdict_on_pass == "support")

    def unsettled(ran: frozenset[CandidateCheck], world: tuple[bool, ...]) -> int:
        settled = {c.hypothesis_ref for c in ran if passes(c, world)}
        return len(hypotheses) - len(settled)

    cells = []
    for ran in subsets:
        steps = [Step(tuple(c.cost for _ in worlds), 1, index[ran | {c}]) for c in checks if c not in ran]
        steps.append(Step(tuple(request.pending_cost * unsettled(ran, w) for w in worlds), 0))
        cells.append(tuple(steps))
    return PlanChart(cells=tuple(cells), root=index[frozenset()], worlds=len(worlds)), subsets
