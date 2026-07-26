from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest

from popperpad.core import market
from popperpad.core.values import DeeplyImmutable


MUTABLE_ORIGINS = {list, dict, set}
FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "datetime",
    "multiprocessing",
    "os",
    "pathlib",
    "random",
    "requests",
    "socket",
    "sqlite3",
    "subprocess",
    "tempfile",
    "threading",
    "time",
    "urllib",
    "web3",
}


def _contains_mutable(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin in MUTABLE_ORIGINS:
        return True
    return any(_contains_mutable(value) for value in get_args(annotation))


def test_market_core_records_are_runtime_guarded_frozen_slotted_and_collection_safe() -> None:
    for _name, cls in inspect.getmembers(market, inspect.isclass):
        if cls.__module__ != market.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert cls.__dataclass_params__.frozen, cls.__name__
        assert hasattr(cls, "__slots__"), cls.__name__
        assert issubclass(cls, DeeplyImmutable), cls.__name__
        for field_name, annotation in get_type_hints(cls).items():
            assert not _contains_mutable(annotation), f"{cls.__name__}.{field_name}"


def test_market_effect_rejects_mutable_nested_metadata() -> None:
    with pytest.raises(TypeError, match="metadata"):
        market.MarketEffect(
            kind="payout",
            account_ref="did:example:recipient",
            amount=market.Amount(1),
            subject_ref="submission-1",
            metadata={"reasons": []},  # type: ignore[arg-type]
        )


def test_market_core_has_no_effect_authority() -> None:
    path = Path(importlib.import_module("popperpad.core.market").__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        for name in names:
            assert name.split(".", 1)[0] not in FORBIDDEN_IMPORT_ROOTS, name
            assert not name.startswith("popperpad.") or name.startswith("popperpad.core"), name


def test_market_transition_requires_explicit_state_command_policy_and_evidence() -> None:
    parameters = inspect.signature(market.apply_market_command).parameters
    assert tuple(parameters) == ("state", "command", "policy", "evidence")
    assert "now" not in parameters
    assert "storage" not in parameters
    assert "verifier" not in parameters
    assert "payment" not in parameters
