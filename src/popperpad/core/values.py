from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Generic, TypeAlias, TypeVar, cast


V = TypeVar("V")


class DeeplyImmutable:
    """Runtime guard for owned, transitively immutable core value graphs.

    ``frozen=True`` blocks ordinary attribute rebinding only. Core values also
    inherit this trusted marker, use slots, own their children, and validate the
    complete reachable graph at construction.
    """

    __slots__ = ()

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not is_deeply_immutable(value):
                raise TypeError(
                    f"{type(self).__name__}.{field.name} must be deeply immutable"
                )


class ClosedStrEnumMeta(type):
    """Build and seal a finite set of immutable string-valued alternatives."""

    def __new__(
        metaclass: type[ClosedStrEnumMeta],
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> ClosedStrEnumMeta:
        declaration = dict(namespace)
        symbols = tuple(declaration.pop("_symbols", ()))
        declaration.setdefault("__slots__", ())
        if any(getattr(base, "_closed_enum_members", ()) for base in bases):
            raise TypeError("closed string enums cannot be extended")
        cls = super().__new__(metaclass, name, bases, declaration)

        members: list[ClosedStrEnum] = []
        by_name: dict[str, ClosedStrEnum] = {}
        by_value: dict[str, ClosedStrEnum] = {}
        names_by_value: dict[str, str] = {}
        for entry in symbols:
            if type(entry) is not tuple or len(entry) != 2:
                raise TypeError("closed enum symbols must be (name, value) pairs")
            member_name, member_value = entry
            if type(member_name) is not str or not member_name.isidentifier():
                raise TypeError("closed enum names must be identifiers")
            if type(member_value) is not str:
                raise TypeError("closed enum values must be exact strings")
            if member_name in by_name:
                raise ValueError(f"duplicate closed enum name: {member_name}")
            if member_value in by_value:
                raise ValueError(f"duplicate closed enum value: {member_value}")
            member = str.__new__(cls, member_value)
            if hasattr(member, "__dict__"):
                raise TypeError("closed enum members must not expose writable instance state")
            members.append(member)
            by_name[member_name] = member
            by_value[member_value] = member
            names_by_value[member_value] = member_name
            type.__setattr__(cls, member_name, member)

        type.__setattr__(cls, "_closed_enum_members", tuple(members))
        type.__setattr__(cls, "_closed_enum_by_name", MappingProxyType(by_name))
        type.__setattr__(cls, "_closed_enum_by_value", MappingProxyType(by_value))
        type.__setattr__(cls, "_closed_enum_names_by_value", MappingProxyType(names_by_value))
        type.__setattr__(cls, "_closed_enum_sealed", True)
        return cls

    def __iter__(cls) -> Iterator[ClosedStrEnum]:
        return iter(cls._closed_enum_members)

    def __len__(cls) -> int:
        return len(cls._closed_enum_members)

    def __getitem__(cls, name: str) -> ClosedStrEnum:
        return cls._closed_enum_by_name[name]

    def __contains__(cls, value: object) -> bool:
        return type(value) is cls and value in cls._closed_enum_members

    def __call__(cls, value: object) -> ClosedStrEnum:
        if type(value) is cls:
            return cast(ClosedStrEnum, value)
        if type(value) is not str:
            raise ValueError(f"{value!r} is not a valid {cls.__name__}")
        try:
            return cls._closed_enum_by_value[value]
        except KeyError as error:
            raise ValueError(f"{value!r} is not a valid {cls.__name__}") from error

    def __setattr__(cls, name: str, value: object) -> None:
        if cls.__dict__.get("_closed_enum_sealed", False) or any(
            getattr(base, "_closed_enum_sealed", False) for base in cls.__bases__
        ):
            raise TypeError(f"{cls.__name__} is a sealed closed enum")
        super().__setattr__(name, value)

    def __delattr__(cls, name: str) -> None:
        if cls.__dict__.get("_closed_enum_sealed", False) or any(
            getattr(base, "_closed_enum_sealed", False) for base in cls.__bases__
        ):
            raise TypeError(f"{cls.__name__} is a sealed closed enum")
        super().__delattr__(name)


class ClosedStrEnum(str, DeeplyImmutable, metaclass=ClosedStrEnumMeta):
    """A closed sum encoded as immutable canonical string alternatives.

    Unlike ``enum.Enum``, members have no writable ``__dict__`` and the member
    registry is sealed after class construction. Values retain string equality
    and JSON compatibility while remaining safe inside authority-bearing plans.
    """

    __slots__ = ()
    _symbols = ()

    @property
    def name(self) -> str:
        return type(self)._closed_enum_names_by_value[str(self)]

    @property
    def value(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}.{self.name}: {str.__repr__(str(self))}>"

    def __setattr__(self, name: str, value: object) -> None:
        raise TypeError(f"{type(self).__name__} members are immutable")

    def __delattr__(self, name: str) -> None:
        raise TypeError(f"{type(self).__name__} members are immutable")

    def __reduce__(self) -> tuple[type[ClosedStrEnum], tuple[str]]:
        return type(self), (self.value,)


@dataclass(frozen=True, slots=True, init=False)
class FrozenDict(DeeplyImmutable, Mapping[str, V], Generic[V]):
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
            if type(key) is not str:
                raise TypeError("FrozenDict keys must be exact strings")
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

    def updated(self, **changes: V) -> FrozenDict[V]:
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

    if value is None or type(value) in (bool, str):
        return cast(JsonScalar, value)
    if isinstance(value, ClosedStrEnum):
        return value.value
    if type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number at {path}")
        raise TypeError(f"floating-point value at {path}; encode exact integer atoms or a decimal string")
    if isinstance(value, Mapping):
        frozen_items: list[tuple[str, JsonValue]] = []
        for key, child in value.items():
            if type(key) is not str:
                raise TypeError(f"non-string object key at {path}")
            frozen_items.append((key, freeze_json(child, path=f"{path}.{key}")))
        return FrozenDict(frozen_items)
    if type(value) in (list, tuple):
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
    if value is None or type(value) in (bool, int, str, bytes, Amount):
        return True
    if isinstance(value, ClosedStrEnum):
        return not hasattr(value, "__dict__") and type(value.value) is str
    value_id = id(value)
    if value_id in _seen:
        return False
    seen = _seen | {value_id}
    if type(value) is tuple:
        return all(is_deeply_immutable(child, _seen=seen) for child in value)
    if type(value) is frozenset:
        return all(is_deeply_immutable(child, _seen=seen) for child in value)
    if type(value) is FrozenDict:
        return all(is_deeply_immutable(child, _seen=seen) for _key, child in value.items_tuple())
    if is_dataclass(value) and not isinstance(value, type):
        params = getattr(type(value), "__dataclass_params__", None)
        return isinstance(value, DeeplyImmutable) and bool(
            params and params.frozen
        ) and not hasattr(value, "__dict__") and all(
            is_deeply_immutable(getattr(value, field.name), _seen=seen) for field in fields(value)
        )
    return False


@dataclass(frozen=True, slots=True, order=True)
class Amount(DeeplyImmutable):
    """An exact non-negative protocol quantity measured in declared atoms."""

    atoms: int

    def __post_init__(self) -> None:
        if type(self.atoms) is not int:
            raise TypeError("amount atoms must be an integer")
        if self.atoms < 0:
            raise ValueError("amount atoms must be non-negative")
        DeeplyImmutable.__post_init__(self)

    @classmethod
    def zero(cls) -> Amount:
        return cls(0)

    def plus(self, other: Amount) -> Amount:
        return Amount(self.atoms + other.atoms)

    def minus(self, other: Amount) -> Amount:
        if other.atoms > self.atoms:
            raise ValueError("amount subtraction would become negative")
        return Amount(self.atoms - other.atoms)
