"""Robust plan prefixes: a standard-library port of Zeno-ADP 0.8.0 ``robust_prefix``.

A plan chart has cells of steps. A step has one integer cost per world, a nonnegative
integer credit for useful work, and either a child cell with a smaller index or no child
(it finishes). A prefix is a step sequence from the root, possibly empty. In each world,
``V(x)`` is the least cost of finishing from cell ``x``, and a step's slack is its cost plus
``V`` of its child minus ``V`` of its cell. Committing to a prefix and then finishing
optimally costs the world's optimum plus the prefix's slacks in that world.

``zero_regret`` returns the prefix of greatest credit whose steps have zero slack in every
world. ``within_budget`` returns the prefix of greatest credit whose summed slack stays
within each world's own budget. Both report their tie count and the first prefix in prefix
order: stopping before continuing, then step order. ``vectors/zeno_adp_0_8_0.json`` holds
answers computed by Zeno-ADP itself, and the tests require this port to match them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .values import DeeplyImmutable

Rules = tuple[tuple[int, int], ...]  # (cell, step ordinal) pairs


@dataclass(frozen=True, slots=True)
class Step(DeeplyImmutable):
    costs: tuple[int, ...]
    credit: int
    child: int | None = None

    def __post_init__(self) -> None:
        if type(self.costs) is not tuple or not self.costs or not all(type(c) is int for c in self.costs):
            raise TypeError("step costs must be a nonempty tuple of integers")
        if type(self.credit) is not int or self.credit < 0:
            raise ValueError("step credit must be a nonnegative integer")
        if self.child is not None and (type(self.child) is not int or self.child < 0):
            raise ValueError("step child must be null or a cell index")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class PlanChart(DeeplyImmutable):
    cells: tuple[tuple[Step, ...], ...]
    root: int
    worlds: int

    def __post_init__(self) -> None:
        if type(self.worlds) is not int or self.worlds < 1 or type(self.root) is not int:
            raise ValueError("plan chart needs at least one world and an integer root")
        if not 0 <= self.root < len(self.cells):
            raise ValueError("plan chart root is not a cell")
        for cell, steps in enumerate(self.cells):
            for step in steps:
                if type(step) is not Step or len(step.costs) != self.worlds:
                    raise ValueError(f"cell {cell}: every step needs one cost per world")
                if step.child is not None and step.child >= cell:
                    raise ValueError(f"cell {cell}: a step's child must have a smaller index")
        DeeplyImmutable.__post_init__(self)
        if any(v is None for v in plan_values(self)[self.root]):
            raise ValueError("some world has no plan from the root")


@dataclass(frozen=True, slots=True)
class ZeroRegret(DeeplyImmutable):
    best_credit: int
    count: int
    prefix: Rules
    common_plan: Rules | None
    completions: tuple[Rules, ...]


@dataclass(frozen=True, slots=True)
class WithinBudget(DeeplyImmutable):
    budget: tuple[int, ...]
    best: int
    count: int
    prefix: Rules
    regret: tuple[int, ...]


def plan_values(chart: PlanChart) -> tuple[tuple[int | None, ...], ...]:
    values: list[tuple[int | None, ...]] = []
    for steps in chart.cells:
        row = []
        for world in range(chart.worlds):
            best = None
            for step in steps:
                tail = 0 if step.child is None else values[step.child][world]
                if tail is not None and (best is None or step.costs[world] + tail < best):
                    best = step.costs[world] + tail
            row.append(best)
        values.append(tuple(row))
    return tuple(values)


def _slack(chart: PlanChart, values, cell: int, index: int, world: int) -> int | None:
    step = chart.cells[cell][index]
    tail = 0 if step.child is None else values[step.child][world]
    if tail is None or values[cell][world] is None:
        return None
    return step.costs[world] + tail - values[cell][world]


def regret(chart: PlanChart, rules: Rules) -> tuple[int, ...]:
    """The sum of each world's slacks along a rule sequence from the root."""
    values, total, cell = plan_values(chart), [0] * chart.worlds, chart.root
    for at, index in rules:
        if at != cell:
            raise ValueError("rule sequence does not start at the root or skips a cell")
        for world in range(chart.worlds):
            value = _slack(chart, values, at, index, world)
            if value is None:
                raise ValueError("rule leads to a cell with no plan")
            total[world] += value
        cell = chart.cells[at][index].child
    return tuple(total)


def zero_regret(chart: PlanChart) -> ZeroRegret:
    values = plan_values(chart)
    zero = [[all(_slack(chart, values, c, i, w) == 0 for w in range(chart.worlds))
             for i in range(len(steps))] for c, steps in enumerate(chart.cells)]
    n = len(chart.cells)
    credit, counts, reach = [0] * n, [0] * n, [False] * n
    for cell, steps in enumerate(chart.cells):
        best, count = 0, 1  # Stopping is a prefix of credit zero.
        for index, step in enumerate(steps):
            if not zero[cell][index]:
                continue
            value = step.credit + (0 if step.child is None else credit[step.child])
            ways = 1 if step.child is None else counts[step.child]
            if value > best:
                best, count = value, ways
            elif value == best:
                count += ways
            reach[cell] = reach[cell] or step.child is None or reach[step.child]
        credit[cell], counts[cell] = best, count
    prefix: list[tuple[int, int]] = []
    cell: int | None = chart.root
    while cell is not None and credit[cell] > 0:
        for index, step in enumerate(chart.cells[cell]):
            tail = 0 if step.child is None else credit[step.child]
            if zero[cell][index] and step.credit + tail == credit[cell]:
                prefix.append((cell, index))
                cell = step.child
                break
    end = chart.cells[prefix[-1][0]][prefix[-1][1]].child if prefix else chart.root
    completions = tuple(tuple(prefix) + _complete(chart, values, end, w) for w in range(chart.worlds))
    common: Rules | None = None
    if reach[chart.root]:
        plan, cell = [], chart.root
        while cell is not None:
            index = next(i for i, step in enumerate(chart.cells[cell])
                         if zero[cell][i] and (step.child is None or reach[step.child]))
            plan.append((cell, index))
            cell = chart.cells[cell][index].child
        common = tuple(plan)
    return ZeroRegret(best_credit=credit[chart.root], count=counts[chart.root], prefix=tuple(prefix),
                      common_plan=common, completions=completions)


def _complete(chart: PlanChart, values, start: int | None, world: int) -> Rules:
    plan, cell = [], start
    while cell is not None:
        index = next(i for i in range(len(chart.cells[cell])) if _slack(chart, values, cell, i, world) == 0)
        plan.append((cell, index))
        cell = chart.cells[cell][index].child
    return tuple(plan)


def within_budget(chart: PlanChart, budget: tuple[int, ...]) -> WithinBudget:
    if type(budget) is not tuple or len(budget) != chart.worlds or not all(type(b) is int and b >= 0 for b in budget):
        raise ValueError("budget needs one nonnegative integer per world")
    values = plan_values(chart)
    memo: dict[tuple[int, tuple[int, ...]], tuple[int, int, Rules]] = {}

    def best(cell: int, left: tuple[int, ...]) -> tuple[int, int, Rules]:
        key = (cell, left)
        if key not in memo:
            top, count, first = 0, 1, ()
            for index, step in enumerate(chart.cells[cell]):
                slacks = [_slack(chart, values, cell, index, w) for w in range(chart.worlds)]
                if any(s is None for s in slacks):
                    continue
                rest = tuple(b - s for b, s in zip(left, slacks))
                if any(r < 0 for r in rest):
                    continue
                if step.child is None:
                    value, ways, tail = step.credit, 1, ()
                else:
                    sub, ways, tail = best(step.child, rest)
                    value = step.credit + sub
                if value > top:
                    top, count, first = value, ways, ((cell, index),) + tail
                elif value == top:
                    count += ways
            memo[key] = (top, count, first)
        return memo[key]

    top, count, prefix = best(chart.root, budget)
    return WithinBudget(budget=budget, best=top, count=count, prefix=prefix, regret=regret(chart, prefix))
