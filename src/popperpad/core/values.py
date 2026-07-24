from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Generic, TypeAlias, TypeVar, cast


V = TypeVar("V")


@dataclass(frozen=True, slots=True, init=False)
class FrozenDict(Mapping[str, V], Generic[V]):
    """Small immutable mapping with canonical key order and owned entries.

    The constructor copies the supplied mapping/iterable, rejects duplicate or
    non-string keys, and stores only a tuple. It therefore retains no mutable
    alias to the caller's dictionary.
    """

    _items: tuple[tuple[str, V], ...]

    def __init__(self, source: Mapping[str, V] | Iterable[tuple[str, V]] = ()) -> None:
        pairs = tuple(source.items()) if isinstance(source, Mapping) else tuple(source)
        owned: dict[str, V] = {}
        for key, value in pairs:
            if not isinstance(key, str):
                raise TypeError("FrozenDict keys must be strings")
            if key in owned:
                raise ValueError(f"duplicate FrozenDict key: {key}")
            if not is_deeply_immutable(value):
                raise TypeError(f"FrozenDict value for {key!r} must be deeply immutable")
            owned[key] = value
        object.__setattr__(self, "_items", tuple(sorted(owned.items(), key=lambda item: item[0])))

    def __getitem__(self, key: str) -> V:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def items_tuple(self) -> tuple[tuple[str, V], ...]:
        return self._items

    def updated(self, **changes: V) -> "FrozenDict[V]":
        next_values = {key: value for key, value in self._items}
        next_values.update(changes)
        return FrozenDict(next_values)


JsonScalar: TypeAlias = None | bool | int | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | FrozenDict["JsonValue"]


def freeze_json(value: Any, *, path: str = "$") -> JsonValue:
    """Own and recursively freeze an integer-only canonical JSON value.

    Binary floating point is deliberately excluded from committed core values.
    Protocol quantities must use integer atoms or an explicitly encoded decimal
    or rational representation.
    """

    if value is None or isinstance(value, (bool, str)):
        return cast(JsonScalar, value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number at {path}")
        raise TypeError(f"floating-point value at {path}; encode exact integer atoms or a decimal string")
    if isinstance(value, Mapping):
        frozen_items: list[tuple[str, JsonValue]] = []
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string object key at {path}")
            frozen_items.append((key, freeze_json(child, path=f"{path}.{key}")))
        return FrozenDict(frozen_items)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(child, path=f"{path}[{index}]") for index, child in enumerate(value))
    raise TypeError(f"unsupported JSON value at {path}: {type(value).__name__}")


def thaw_json(value: JsonValue) -> Any:
    """Return ordinary JSON containers at an encoding or I/O boundary."""

    if isinstance(value, FrozenDict):
        return {key: thaw_json(child) for key, child in value.items_tuple()}
    if isinstance(value, tuple):
        return [thaw_json(child) for child in value]
    return value


def is_deeply_immutable(value: Any, *, _seen: frozenset[int] = frozenset()) -> bool:
    if value is None or isinstance(value, (bool, int, str, bytes, Enum, Amount)):
        return True
    value_id = id(value)
    if value_id in _seen:
        return False
    seen = _seen | {value_id}
    if isinstance(value, tuple):
        return all(is_deeply_immutable(child, _seen=seen) for child in value)
    if isinstance(value, frozenset):
        return all(is_deeply_immutable(child, _seen=seen) for child in value)
    if isinstance(value, FrozenDict):
        return all(is_deeply_immutable(child, _seen=seen) for _key, child in value.items_tuple())
    if is_dataclass(value) and not isinstance(value, type):
        params = getattr(type(value), "__dataclass_params__", None)
        return bool(params and params.frozen) and not hasattr(value, "__dict__") and all(
            is_deeply_immutable(getattr(value, field.name), _seen=seen) for field in fields(value)
        )
    return False


class DeeplyImmutable:
    """Runtime guard for owned, transitively immutable core values.

    ``frozen=True`` prevents attribute rebinding but does not make a retained
    list, mapping, or mutable child immutable. Core value constructors inherit
    this guard so an invalid reachable object graph is rejected at the boundary
    instead of becoming mutable authority state.
    """

    __slots__ = ()

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not is_deeply_immutable(value):
                raise TypeError(
                    f"{type(self).__name__}.{field.name} must be deeply immutable"
                )


@dataclass(frozen=True, slots=True, order=True)
class Amount(DeeplyImmutable):
    """An exact non-negative protocol quantity measured in declared atoms."""

    atoms: int

    def __post_init__(self) -> None:
        if not isinstance(self.atoms, int) or isinstance(self.atoms, bool):
            raise TypeError("amount atoms must be an integer")
        if self.atoms < 0:
            raise ValueError("amount atoms must be non-negative")
        DeeplyImmutable.__post_init__(self)

    @classmethod
    def zero(cls) -> "Amount":
        return cls(0)

    def plus(self, other: "Amount") -> "Amount":
        return Amount(self.atoms + other.atoms)

    def minus(self, other: "Amount") -> "Amount":
        if other.atoms > self.atoms:
            raise ValueError("amount subtraction would become negative")
        return Amount(self.atoms - other.atoms)
