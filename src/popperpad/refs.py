from __future__ import annotations

import re
from enum import Enum
from typing import Any


REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ValidationError(ValueError):
    """Raised when a PopperPad object or reference violates a contract."""


def require(condition: bool, message: str) -> None:
    if condition:
        return
    raise ValidationError(message)


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(REF_RE.match(value))


def require_ref(value: Any, message: str) -> None:
    require(is_ref(value), message)


def require_str(value: Any, message: str) -> None:
    require(isinstance(value, str), message)


def require_list(value: Any, message: str) -> None:
    require(isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)), message)


class Ref(str):
    """A content-addressed reference validated as ``sha256:<64hex>``.

    Invalid refs are unrepresentable: construction raises ``ValidationError``.
    ``Ref`` is a ``str`` subclass so it serializes transparently and compares
    equal to its underlying string.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> "Ref":
        require_ref(value, f"invalid ref (expected sha256:<64hex>): {value!r}")
        return super().__new__(cls, value)

    @classmethod
    def parse(cls, value: Any) -> "Ref | None":
        """Return a ``Ref`` for valid refs, ``None`` for missing/empty values."""
        if value is None or value == "":
            return None
        return cls(value)

    @property
    def hex_part(self) -> str:
        return str(self).split(":", 1)[1]

    @property
    def hex_pair(self) -> tuple[str, str]:
        hex_ = self.hex_part
        return hex_[:2], hex_[2:]


class RunMode(str, Enum):
    PROVE = "prove"
    REFUTE = "refute"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"

    @property
    def is_inconclusive(self) -> bool:
        return self in (CheckStatus.SKIP, CheckStatus.TIMEOUT, CheckStatus.ERROR)


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class ClaimState(str, Enum):
    UNKNOWN = "unknown"
    SUPPORTED = "supported"
    FALSIFIED = "falsified"
    DISPUTED = "disputed"
