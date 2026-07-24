from __future__ import annotations

from enum import Enum
from typing import ClassVar

import pytest

from popperpad.core.result import Accept
from popperpad.core.values import ClosedStrEnum, freeze_json, is_deeply_immutable


class SafePhase(ClosedStrEnum):
    __slots__ = ()

    OPEN: ClassVar[SafePhase]
    CLOSED: ClassVar[SafePhase]
    _symbols = (("OPEN", "open"), ("CLOSED", "closed"))


class MutableValuedEnum(Enum):
    BAD = {"mutable": []}


class MutableString(str):
    pass


def test_closed_string_enum_is_a_sealed_immutable_sum() -> None:
    assert SafePhase.OPEN.value == "open"
    assert SafePhase.OPEN.name == "OPEN"
    assert SafePhase("open") is SafePhase.OPEN
    assert SafePhase["CLOSED"] is SafePhase.CLOSED
    assert tuple(SafePhase) == (SafePhase.OPEN, SafePhase.CLOSED)
    assert SafePhase.OPEN == "open"
    assert not hasattr(SafePhase.OPEN, "__dict__")
    assert is_deeply_immutable(SafePhase.OPEN)

    decision = Accept(next_state=SafePhase.OPEN, effects=(), receipt="receipt")
    assert decision.next_state is SafePhase.OPEN

    with pytest.raises(TypeError, match="immutable"):
        SafePhase.OPEN.extra = "changed"  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="sealed"):
        SafePhase.OPEN = SafePhase.CLOSED  # type: ignore[misc]


def test_untrusted_enums_and_scalar_subclasses_remain_rejected() -> None:
    assert not is_deeply_immutable(MutableValuedEnum.BAD)
    assert not is_deeply_immutable(MutableString("open"))
    with pytest.raises(TypeError, match="deeply immutable"):
        Accept(next_state=MutableValuedEnum.BAD, effects=(), receipt="receipt")
    with pytest.raises(TypeError, match="deeply immutable"):
        Accept(next_state=MutableString("open"), effects=(), receipt="receipt")


def test_canonical_json_normalizes_closed_enum_to_exact_string() -> None:
    frozen = freeze_json({"phase": SafePhase.OPEN})
    phase = frozen["phase"]  # type: ignore[index]
    assert type(phase) is str
    assert phase == "open"
