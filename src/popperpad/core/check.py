from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .values import DeeplyImmutable


@dataclass(frozen=True, slots=True)
class RunIntent(DeeplyImmutable):
    value: str

    PROVE: ClassVar[RunIntent]
    REFUTE: ClassVar[RunIntent]

    def __post_init__(self) -> None:
        if type(self.value) is not str or self.value not in {"prove", "refute"}:
            raise ValueError("run intent must be prove or refute")
        DeeplyImmutable.__post_init__(self)


RunIntent.PROVE = RunIntent("prove")
RunIntent.REFUTE = RunIntent("refute")


@dataclass(frozen=True, slots=True)
class AggregateVerdict(DeeplyImmutable):
    value: str

    PASS: ClassVar[AggregateVerdict]
    FAIL: ClassVar[AggregateVerdict]
    INCONCLUSIVE: ClassVar[AggregateVerdict]

    def __post_init__(self) -> None:
        if type(self.value) is not str or self.value not in {"PASS", "FAIL", "INCONCLUSIVE"}:
            raise ValueError("aggregate verdict must be PASS, FAIL, or INCONCLUSIVE")
        DeeplyImmutable.__post_init__(self)


AggregateVerdict.PASS = AggregateVerdict("PASS")
AggregateVerdict.FAIL = AggregateVerdict("FAIL")
AggregateVerdict.INCONCLUSIVE = AggregateVerdict("INCONCLUSIVE")


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
    if intent == RunIntent.PROVE:
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
    if summary.intent == RunIntent.REFUTE:
        if any_pass:
            return AggregateVerdict.PASS
        return AggregateVerdict.INCONCLUSIVE if any_inconclusive else AggregateVerdict.FAIL
    if any_fail:
        return AggregateVerdict.FAIL
    if any_pass:
        return AggregateVerdict.PASS
    return AggregateVerdict.INCONCLUSIVE
