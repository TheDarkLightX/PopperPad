from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeAlias, TypeVar

from .values import FrozenDict, JsonValue, freeze_json, is_deeply_immutable


S = TypeVar("S")
E = TypeVar("E")
R = TypeVar("R")


def _own_details(details: object) -> FrozenDict[JsonValue]:
    frozen = freeze_json(details)
    if not isinstance(frozen, FrozenDict):
        raise TypeError("decision details must be a JSON object")
    return frozen


def _require_deeply_immutable(field_name: str, value: object) -> None:
    if not is_deeply_immutable(value):
        raise TypeError(f"{field_name} must be deeply immutable")


@dataclass(frozen=True, slots=True)
class Reject:
    """A semantic rejection: no authoritative state or effect is committed."""

    code: str
    details: FrozenDict[JsonValue] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("rejection code must be a non-empty string")
        object.__setattr__(self, "details", _own_details(self.details))


@dataclass(frozen=True, slots=True)
class Accept(Generic[S, E, R]):
    """An accepted pure decision carrying exact next-state/effect/receipt values."""

    next_state: S
    effects: tuple[E, ...]
    receipt: R

    def __post_init__(self) -> None:
        _require_deeply_immutable("next_state", self.next_state)
        _require_deeply_immutable("effects", self.effects)
        _require_deeply_immutable("receipt", self.receipt)


@dataclass(frozen=True, slots=True)
class CommittedFailure(Generic[S, E, R]):
    """A failure whose protocol semantics intentionally commit state/effects."""

    code: str
    next_state: S
    effects: tuple[E, ...]
    receipt: R
    details: FrozenDict[JsonValue] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("committed-failure code must be a non-empty string")
        _require_deeply_immutable("next_state", self.next_state)
        _require_deeply_immutable("effects", self.effects)
        _require_deeply_immutable("receipt", self.receipt)
        object.__setattr__(self, "details", _own_details(self.details))


Decision: TypeAlias = Reject | Accept[S, E, R] | CommittedFailure[S, E, R]
