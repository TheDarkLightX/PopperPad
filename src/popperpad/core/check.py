from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .values import ClosedStrEnum, DeeplyImmutable


class RunIntent(ClosedStrEnum):
    __slots__ = ()

    PROVE: ClassVar[RunIntent]
    REFUTE: ClassVar[RunIntent]
    _symbols = (("PROVE", "prove"), ("REFUTE", "refute"))


class AggregateVerdict(ClosedStrEnum):
    __slots__ = ()

    PASS: ClassVar[AggregateVerdict]
    FAIL: ClassVar[AggregateVerdict]
    INCONCLUSIVE: ClassVar[AggregateVerdict]
    _symbols = (
        ("PASS", "PASS"),
        ("FAIL", "FAIL"),
        ("INCONCLUSIVE", "INCONCLUSIVE"),
    )


@dataclass(frozen=True, slots=True)
class CheckSummary(DeeplyImmutable):
    intent: RunIntent
    categories: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.intent) is not RunIntent:
            raise TypeError("intent must be RunIntent")
        if type(self.categories) is not tuple or not all(
            type(category) is str and category in {"pass", "fail", "inconclusive"}
            for category in self.categories
        ):
            raise TypeError("categories must contain only pass, fail, or inconclusive")
        DeeplyImmutable.__post_init__(self)


def recipe_applies(verdict_on_pass: str, intent: RunIntent) -> bool:
    if intent is RunIntent.PROVE:
        return verdict_on_pass == "support"
    return verdict_on_pass == "refute"


def decide_check_summary(summary: CheckSummary) -> AggregateVerdict:
    """Pure stable aggregation of per-recipe pass/fail/inconclusive values."""

    has_evidence = bool(summary.categories)
    any_pass = "pass" in summary.categories
    any_fail = "fail" in summary.categories
    any_inconclusive = "inconclusive" in summary.categories

    if not has_evidence:
        return AggregateVerdict.INCONCLUSIVE
    if summary.intent is RunIntent.REFUTE:
        if any_pass:
            return AggregateVerdict.PASS
        return AggregateVerdict.INCONCLUSIVE if any_inconclusive else AggregateVerdict.FAIL
    if any_fail:
        return AggregateVerdict.FAIL
    if any_pass:
        return AggregateVerdict.PASS
    return AggregateVerdict.INCONCLUSIVE
