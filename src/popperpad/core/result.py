from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeAlias, TypeVar

from .values import FrozenDict, JsonValue


S = TypeVar("S")
E = TypeVar("E")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class Reject:
    """A semantic rejection: no authoritative state or effect is committed."""

    code: str
    details: FrozenDict[JsonValue] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if not self.code or not isinstance(self.code, str):
            raise ValueError("rejection code must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Accept(Generic[S, E, R]):
    """An accepted pure decision carrying exact next-state/effect/receipt values."""

    next_state: S
    effects: tuple[E, ...]
    receipt: R


@dataclass(frozen=True, slots=True)
class CommittedFailure(Generic[S, E, R]):
    """A failure whose protocol semantics intentionally commit state/effects."""

    code: str
    next_state: S
    effects: tuple[E, ...]
    receipt: R
    details: FrozenDict[JsonValue] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if not self.code or not isinstance(self.code, str):
            raise ValueError("committed-failure code must be a non-empty string")


Decision: TypeAlias = Reject | Accept[S, E, R] | CommittedFailure[S, E, R]
