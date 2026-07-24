"""Pure, deterministic PopperPad semantics.

Modules under :mod:`popperpad.core` may depend only on Python's value-oriented
standard-library facilities and other core modules. They must not perform I/O,
read clocks or environment variables, execute processes, use randomness, or
import shell adapters.
"""

from .result import Accept, CommittedFailure, Decision, Reject
from .values import Amount, FrozenDict, JsonValue, freeze_json, thaw_json

__all__ = [
    "Accept",
    "Amount",
    "CommittedFailure",
    "Decision",
    "FrozenDict",
    "JsonValue",
    "Reject",
    "freeze_json",
    "thaw_json",
]
