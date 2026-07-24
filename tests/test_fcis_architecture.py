from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest

from popperpad.core import Accept, Amount, CommittedFailure, FrozenDict, Reject, freeze_json, thaw_json
from popperpad.core.check import AggregateVerdict, CheckSummary, RunIntent, decide_check_summary
from popperpad.core.recipe import ProcessObservation, RecipePlan, evaluate_observation, plan_recipe


CORE_MODULES = (
    "popperpad.core.check",
    "popperpad.core.codec",
    "popperpad.core.commit",
    "popperpad.core.evidence",
    "popperpad.core.mechanism",
    "popperpad.core.recipe",
    "popperpad.core.result",
    "popperpad.core.values",
)
FORBIDDEN_ROOT_IMPORTS = {
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
FORBIDDEN_POPPERPAD_IMPORTS = {
    "popperpad.adapters",
    "popperpad.cas",
    "popperpad.cli",
    "popperpad.doctor",
    "popperpad.engine",
    "popperpad.index",
    "popperpad.log",
    "popperpad.pad",
    "popperpad.runner",
    "popperpad.tui",
}
MUTABLE_ORIGINS = {list, dict, set}


def _annotation_contains_mutable(annotation: object) -> bool:
    origin = get_origin(annotation)
    if origin in MUTABLE_ORIGINS:
        return True
    return any(_annotation_contains_mutable(arg) for arg in get_args(annotation))


def test_freeze_json_owns_the_complete_transitive_value() -> None:
    source = {"claim": {"tags": ["formal", "counterexample"]}, "score": 10}
    frozen = freeze_json(source)
    source["claim"]["tags"].append("mutated")  # type: ignore[index,union-attr]
    source["score"] = 999
    assert thaw_json(frozen) == {
        "claim": {"tags": ["formal", "counterexample"]},
        "score": 10,
    }
    assert isinstance(frozen, FrozenDict)
    with pytest.raises(TypeError):
        frozen["score"] = 1  # type: ignore[index]


def test_frozen_dict_rejects_mutable_child_aliases() -> None:
    payload: list[str] = []
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"payload": payload})


def test_committed_values_reject_floating_point() -> None:
    with pytest.raises(TypeError, match="floating-point"):
        freeze_json({"weight": 0.25})


def test_decision_variants_are_data_not_exceptions_or_effects() -> None:
    reject = Reject("MISSING_EVIDENCE")
    accepted = Accept(next_state=Amount(2), effects=("write",), receipt="r1")
    failed = CommittedFailure(
        code="FEE_CHARGED_ON_FAILURE",
        next_state=Amount(1),
        effects=("charge",),
        receipt="r2",
    )
    assert reject.code == "MISSING_EVIDENCE"
    assert accepted.effects == ("write",)
    assert failed.next_state == Amount(1)


def test_recipe_planning_owns_input_and_returns_no_live_dependencies() -> None:
    raw = {
        "argv": ["tool", "--check"],
        "files": {"claim.txt": {"text": "forall x"}},
        "expect": {"exit_code": 0, "stdout_contains": "valid", "files_exist": ["proof.bin"]},
        "env": {"MODE": "verify"},
    }
    planned = plan_recipe(raw)
    assert isinstance(planned, RecipePlan)
    raw["argv"].append("--mutated")  # type: ignore[union-attr]
    raw["files"]["claim.txt"]["text"] = "changed"  # type: ignore[index]
    assert planned.argv == ("tool", "--check")
    assert planned.files["claim.txt"].value == "forall x"


def test_recipe_observation_classification_is_pure() -> None:
    planned = plan_recipe(
        {
            "argv": ["tool"],
            "expect": {"exit_code": 0, "stdout_regex": "counterexample", "files_exist": ["witness.json"]},
        }
    )
    assert isinstance(planned, RecipePlan)
    observation = ProcessObservation(
        exit_code=0,
        stdout_text="counterexample found",
        stderr_text="",
        existing_paths=frozenset({"witness.json"}),
    )
    assert evaluate_observation(planned, observation).status == "PASS"
    assert evaluate_observation(planned, observation) == evaluate_observation(planned, observation)


def test_check_aggregation_is_a_core_decision() -> None:
    assert decide_check_summary(CheckSummary(RunIntent.PROVE, ("pass",))) is AggregateVerdict.PASS
    assert decide_check_summary(CheckSummary(RunIntent.PROVE, ("fail",))) is AggregateVerdict.FAIL
    assert decide_check_summary(CheckSummary(RunIntent.REFUTE, ("pass",))) is AggregateVerdict.PASS
    assert decide_check_summary(CheckSummary(RunIntent.REFUTE, ("inconclusive",))) is AggregateVerdict.INCONCLUSIVE


@pytest.mark.parametrize(
    ("field", "kwargs"),
    (
        ("next_state", {"next_state": [], "effects": (), "receipt": "r1"}),
        ("effects", {"next_state": Amount(1), "effects": ([],), "receipt": "r1"}),
        ("receipt", {"next_state": Amount(1), "effects": (), "receipt": {}}),
    ),
)
def test_accept_rejects_mutable_authority_payloads(field: str, kwargs: dict[str, object]) -> None:
    with pytest.raises(TypeError, match=field):
        Accept(**kwargs)


def test_reject_owns_nested_json_details() -> None:
    source = {"reasons": ["missing"]}
    reject = Reject("INVALID", details=source)  # type: ignore[arg-type]
    source["reasons"].append("mutated")
    assert thaw_json(reject.details) == {"reasons": ["missing"]}


def test_committed_failure_rejects_mutable_authority_payloads() -> None:
    with pytest.raises(TypeError, match="next_state"):
        CommittedFailure(
            code="FAILED",
            next_state=[],
            effects=(),
            receipt="r1",
        )


def test_all_core_dataclasses_are_frozen_slotted_and_have_no_mutable_fields() -> None:
    for module_name in CORE_MODULES:
        module = importlib.import_module(module_name)
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module_name or not dataclasses.is_dataclass(cls):
                continue
            params = cls.__dataclass_params__
            assert params.frozen, f"{module_name}.{cls.__name__} is not frozen"
            assert hasattr(cls, "__slots__"), f"{module_name}.{cls.__name__} is not slotted"
            for field_name, annotation in get_type_hints(cls).items():
                assert not _annotation_contains_mutable(annotation), (
                    f"{module_name}.{cls.__name__}.{field_name} exposes a mutable container"
                )


def test_core_import_graph_contains_no_effect_authority() -> None:
    package_dir = Path(importlib.import_module("popperpad.core").__file__).parent
    for source_path in package_dir.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                root = name.split(".", 1)[0]
                assert root not in FORBIDDEN_ROOT_IMPORTS, f"effect import {name} in {source_path.name}"
                assert not any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_POPPERPAD_IMPORTS), (
                    f"shell import {name} in {source_path.name}"
                )


def test_check_engine_does_not_reconstruct_or_individually_publish_semantic_objects() -> None:
    engine_path = Path(importlib.import_module("popperpad.engine").__file__)
    source = engine_path.read_text(encoding="utf-8")
    assert ".put_object(" not in source
    assert "plan_check_objects(" in source
    assert ".commit_values(" in source
