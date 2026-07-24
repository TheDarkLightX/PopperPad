from __future__ import annotations

import os
from pathlib import Path

import pytest

from popperpad.cas import ContentAddressedStore
from popperpad.core.recipe import RecipePlan, plan_recipe
from popperpad.core.result import Reject
from popperpad.core.values import FrozenDict
from popperpad.refs import ValidationError
from popperpad.runner import run_recipe
from popperpad.schemas import SCHEMA_RECIPE_V1
from popperpad.validate import validate_object


def test_invalid_recipe_is_a_rejection_value() -> None:
    result = plan_recipe({"argv": ["tool"], "capture_paths": ["../escape"]})
    assert isinstance(result, Reject)
    assert result.code == "INVALID_RECIPE"


@pytest.mark.parametrize(
    "files",
    (
        {"file": {"text": "one"}, " file ": {"text": "two"}},
        {"dir/file": {"text": "one"}, "dir\\file": {"text": "two"}},
    ),
)
def test_normalized_duplicate_file_paths_are_rejected(files: dict[str, object]) -> None:
    result = plan_recipe({"argv": ["tool"], "files": files})
    assert isinstance(result, Reject)
    assert result.code == "INVALID_RECIPE"
    assert result.details["field"].startswith("files.")
    assert result.details["reason"] == "duplicates a normalized file path"


def test_runner_does_not_inherit_unrequested_host_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POPPERPAD_TEST_SECRET", "must-not-cross-boundary")
    cas = ContentAddressedStore(root=tmp_path / "cas")
    result = run_recipe(
        cas=cas,
        recipe={
  "argv": [
      "${PYTHON}",
      "-c",
      "import os; print(os.environ.get('POPPERPAD_TEST_SECRET', 'absent'))",
  ],
  "expect": {"exit_code": 0, "stdout_contains": "absent"},
        },
    )
    assert result.status == "PASS"
    assert b"must-not-cross-boundary" not in cas.get_bytes(result.stdout_ref)


def test_recipe_can_receive_only_explicit_environment_values(tmp_path: Path) -> None:
    cas = ContentAddressedStore(root=tmp_path / "cas")
    result = run_recipe(
        cas=cas,
        recipe={
  "argv": ["${PYTHON}", "-c", "import os; print(os.environ['MODE'])"],
  "env": {"MODE": "verify"},
  "expect": {"exit_code": 0, "stdout_contains": "verify"},
        },
    )
    assert result.status == "PASS"


def test_runner_result_is_transitively_immutable(tmp_path: Path) -> None:
    cas = ContentAddressedStore(root=tmp_path / "cas")
    result = run_recipe(
        cas=cas,
        recipe={
  "argv": ["${PYTHON}", "-c", "open('out.txt','w').write('witness')"],
  "capture_paths": ["out.txt"],
  "expect": {"exit_code": 0},
        },
    )
    assert result.status == "PASS"
    assert isinstance(result.toolchain, FrozenDict)
    assert isinstance(result.outputs, tuple)
    assert isinstance(result.outputs[0], FrozenDict)
    with pytest.raises(TypeError):
        result.outputs[0]["name"] = "changed"  # type: ignore[index]


def test_plan_is_independent_of_later_input_mutation() -> None:
    argv = ["tool"]
    raw = {"argv": argv, "expect": {"exit_code": 0}}
    result = plan_recipe(raw)
    assert isinstance(result, RecipePlan)
    argv.append("--mutated")
    assert result.argv == ("tool",)


def test_persisted_recipe_rejects_environment_values_the_runtime_cannot_execute() -> None:
    recipe = {
        "schema": SCHEMA_RECIPE_V1,
        "recipe_id": "invalid-env",
        "argv": ["tool"],
        "env": {"COUNT": 3},
    }
    with pytest.raises(ValidationError, match="env values must be strings or null"):
        validate_object(recipe)


def test_persisted_recipe_accepts_string_and_null_environment_values() -> None:
    recipe = {
        "schema": SCHEMA_RECIPE_V1,
        "recipe_id": "valid-env",
        "argv": ["tool"],
        "env": {"MODE": "verify", "REMOVED": None},
    }
    validate_object(recipe)
    planned = plan_recipe(recipe)
    assert isinstance(planned, RecipePlan)
    assert planned.env["MODE"] == "verify"
    assert planned.env["REMOVED"] is None
