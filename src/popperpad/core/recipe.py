from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .result import Reject
from .values import FrozenDict, JsonValue, freeze_json


@dataclass(frozen=True, slots=True)
class InputSpec:
    kind: str  # ref|text|binding
    value: str


@dataclass(frozen=True, slots=True)
class ArtifactPlan:
    path: str
    max_bytes: int | None = None
    media_type: str = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class Expectations:
    exit_code: int = 0
    stdout_contains: str | None = None
    stderr_contains: str | None = None
    stdout_not_contains: str | None = None
    stderr_not_contains: str | None = None
    stdout_regex: str | None = None
    stderr_regex: str | None = None
    files_exist: tuple[str, ...] = ()
    files_not_exist: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecipePlan:
    argv: tuple[str, ...]
    timeout_ms: int
    max_output_bytes: int
    max_capture_bytes: int
    expectations: Expectations
    capture_paths: tuple[str, ...]
    artifacts: FrozenDict[ArtifactPlan]
    stdin: InputSpec | None
    env: FrozenDict[str | None]
    files: FrozenDict[InputSpec]
    requires: tuple[str, ...]
    requires_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    exit_code: int
    stdout_text: str
    stderr_text: str
    existing_paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class RecipeEvaluation:
    status: str  # PASS|FAIL
    reason: str


def _reject(code: str, *, field: str, reason: str) -> Reject:
    details = freeze_json({"field": field, "reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code=code, details=details)


def _positive_int(value: Any, default: int, field: str) -> int | Reject:
    candidate = default if value is None else value
    if not isinstance(candidate, int) or isinstance(candidate, bool) or candidate <= 0:
        return _reject("INVALID_RECIPE", field=field, reason="must be a positive integer")
    return candidate


def _string_tuple(value: Any, field: str) -> tuple[str, ...] | Reject:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        return _reject("INVALID_RECIPE", field=field, reason="must be an array of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return _reject("INVALID_RECIPE", field=field, reason="must contain only strings")
        out.append(item)
    return tuple(out)


def normalize_relative_path(value: Any, field: str) -> str | Reject:
    if not isinstance(value, str) or not value.strip():
        return _reject("INVALID_RECIPE", field=field, reason="must be a non-empty relative path")
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        return _reject("INVALID_RECIPE", field=field, reason="must not be absolute or contain '..'")
    return normalized


def _input_spec(value: Any, field: str) -> InputSpec | Reject:
    if not isinstance(value, Mapping):
        return _reject("INVALID_RECIPE", field=field, reason="must be an object")
    present = tuple(key for key in ("ref", "text", "binding") if key in value)
    if len(present) != 1:
        return _reject("INVALID_RECIPE", field=field, reason="must contain exactly one of ref, text, binding")
    key = present[0]
    raw = value.get(key)
    if not isinstance(raw, str):
        return _reject("INVALID_RECIPE", field=f"{field}.{key}", reason="must be a string")
    return InputSpec(kind=key, value=raw)


def _expectations(value: Any) -> Expectations | Reject:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        return _reject("INVALID_RECIPE", field="expect", reason="must be an object")
    exit_code = value.get("exit_code", 0)
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return _reject("INVALID_RECIPE", field="expect.exit_code", reason="must be an integer")

    strings: dict[str, str | None] = {}
    for key in (
        "stdout_contains",
        "stderr_contains",
        "stdout_not_contains",
        "stderr_not_contains",
        "stdout_regex",
        "stderr_regex",
    ):
        raw = value.get(key)
        if raw is not None and not isinstance(raw, str):
            return _reject("INVALID_RECIPE", field=f"expect.{key}", reason="must be a string")
        if key.endswith("_regex") and raw is not None:
            try:
                re.compile(raw)
            except re.error as exc:
                return _reject("INVALID_RECIPE", field=f"expect.{key}", reason=f"invalid regex: {exc}")
        strings[key] = raw

    files_exist = _string_tuple(value.get("files_exist"), "expect.files_exist")
    if isinstance(files_exist, Reject):
        return files_exist
    files_not_exist = _string_tuple(value.get("files_not_exist"), "expect.files_not_exist")
    if isinstance(files_not_exist, Reject):
        return files_not_exist
    normalized_exist: list[str] = []
    normalized_not_exist: list[str] = []
    for index, path in enumerate(files_exist):
        normalized = normalize_relative_path(path, f"expect.files_exist[{index}]")
        if isinstance(normalized, Reject):
            return normalized
        normalized_exist.append(normalized)
    for index, path in enumerate(files_not_exist):
        normalized = normalize_relative_path(path, f"expect.files_not_exist[{index}]")
        if isinstance(normalized, Reject):
            return normalized
        normalized_not_exist.append(normalized)

    return Expectations(
        exit_code=exit_code,
        files_exist=tuple(normalized_exist),
        files_not_exist=tuple(normalized_not_exist),
        **strings,
    )


def plan_recipe(recipe: Mapping[str, Any]) -> RecipePlan | Reject:
    """Parse untrusted recipe data once into an owned immutable execution plan."""

    argv = _string_tuple(recipe.get("argv"), "argv")
    if isinstance(argv, Reject):
        return argv
    if not argv:
        return _reject("INVALID_RECIPE", field="argv", reason="must be non-empty")

    timeout_ms = _positive_int(recipe.get("timeout_ms"), 30_000, "timeout_ms")
    if isinstance(timeout_ms, Reject):
        return timeout_ms
    max_output_bytes = _positive_int(recipe.get("max_output_bytes"), 65_536, "max_output_bytes")
    if isinstance(max_output_bytes, Reject):
        return max_output_bytes
    max_capture_bytes = _positive_int(recipe.get("max_capture_bytes"), 1_048_576, "max_capture_bytes")
    if isinstance(max_capture_bytes, Reject):
        return max_capture_bytes

    expectations = _expectations(recipe.get("expect"))
    if isinstance(expectations, Reject):
        return expectations

    raw_capture = _string_tuple(recipe.get("capture_paths"), "capture_paths")
    if isinstance(raw_capture, Reject):
        return raw_capture
    capture_paths: list[str] = []
    for index, path in enumerate(raw_capture):
        normalized = normalize_relative_path(path, f"capture_paths[{index}]")
        if isinstance(normalized, Reject):
            return normalized
        capture_paths.append(normalized)

    raw_files = recipe.get("files", {}) or {}
    if not isinstance(raw_files, Mapping):
        return _reject("INVALID_RECIPE", field="files", reason="must be an object")
    files: list[tuple[str, InputSpec]] = []
    for name, raw_spec in raw_files.items():
        normalized = normalize_relative_path(name, f"files.{name}")
        if isinstance(normalized, Reject):
            return normalized
        parsed = _input_spec(raw_spec, f"files.{name}")
        if isinstance(parsed, Reject):
            return parsed
        files.append((normalized, parsed))

    raw_stdin = recipe.get("stdin")
    stdin: InputSpec | None = None
    if raw_stdin is not None:
        parsed_stdin = _input_spec(raw_stdin, "stdin")
        if isinstance(parsed_stdin, Reject):
            return parsed_stdin
        stdin = parsed_stdin

    raw_env = recipe.get("env", {}) or {}
    if not isinstance(raw_env, Mapping):
        return _reject("INVALID_RECIPE", field="env", reason="must be an object")
    env: list[tuple[str, str | None]] = []
    for key, value in raw_env.items():
        if not isinstance(key, str) or not key:
            return _reject("INVALID_RECIPE", field="env", reason="keys must be non-empty strings")
        if value is not None and not isinstance(value, str):
            return _reject("INVALID_RECIPE", field=f"env.{key}", reason="must be a string or null")
        env.append((key, value))

    raw_artifacts = recipe.get("artifacts", {}) or {}
    if not isinstance(raw_artifacts, Mapping):
        return _reject("INVALID_RECIPE", field="artifacts", reason="must be an object")
    artifacts: list[tuple[str, ArtifactPlan]] = []
    for artifact_id, raw_spec in raw_artifacts.items():
        if not isinstance(artifact_id, str) or not artifact_id:
            return _reject("INVALID_RECIPE", field="artifacts", reason="keys must be non-empty strings")
        if not isinstance(raw_spec, Mapping):
            return _reject("INVALID_RECIPE", field=f"artifacts.{artifact_id}", reason="must be an object")
        path = normalize_relative_path(raw_spec.get("path"), f"artifacts.{artifact_id}.path")
        if isinstance(path, Reject):
            return path
        max_bytes_raw = raw_spec.get("max_bytes")
        max_bytes: int | None = None
        if max_bytes_raw is not None:
            parsed_max = _positive_int(max_bytes_raw, 0, f"artifacts.{artifact_id}.max_bytes")
            if isinstance(parsed_max, Reject):
                return parsed_max
            max_bytes = parsed_max
        media_type = raw_spec.get("media_type", "application/octet-stream")
        if not isinstance(media_type, str) or not media_type:
            return _reject("INVALID_RECIPE", field=f"artifacts.{artifact_id}.media_type", reason="must be a string")
        artifacts.append((artifact_id, ArtifactPlan(path=path, max_bytes=max_bytes, media_type=media_type)))

    requires = _string_tuple(recipe.get("requires"), "requires")
    if isinstance(requires, Reject):
        return requires
    requires_paths = _string_tuple(recipe.get("requires_paths"), "requires_paths")
    if isinstance(requires_paths, Reject):
        return requires_paths

    return RecipePlan(
        argv=argv,
        timeout_ms=timeout_ms,
        max_output_bytes=max_output_bytes,
        max_capture_bytes=max_capture_bytes,
        expectations=expectations,
        capture_paths=tuple(capture_paths),
        artifacts=FrozenDict(artifacts),
        stdin=stdin,
        env=FrozenDict(env),
        files=FrozenDict(files),
        requires=requires,
        requires_paths=requires_paths,
    )


def evaluate_observation(plan: RecipePlan, observation: ProcessObservation) -> RecipeEvaluation:
    """Purely classify one captured process observation against the plan."""

    expected = plan.expectations
    if observation.exit_code != expected.exit_code:
        return RecipeEvaluation("FAIL", f"exit_code {observation.exit_code} != {expected.exit_code}")

    checks = (
        _contains(observation.stdout_text, expected.stdout_contains, True, "stdout_contains"),
        _contains(observation.stderr_text, expected.stderr_contains, True, "stderr_contains"),
        _contains(observation.stdout_text, expected.stdout_not_contains, False, "stdout_not_contains"),
        _contains(observation.stderr_text, expected.stderr_not_contains, False, "stderr_not_contains"),
        _regex(observation.stdout_text, expected.stdout_regex, "stdout_regex"),
        _regex(observation.stderr_text, expected.stderr_regex, "stderr_regex"),
        _paths(observation.existing_paths, expected.files_exist, True, "files_exist"),
        _paths(observation.existing_paths, expected.files_not_exist, False, "files_not_exist"),
    )
    for ok, reason in checks:
        if not ok:
            return RecipeEvaluation("FAIL", reason)
    return RecipeEvaluation("PASS", "pass")


def _contains(text: str, needle: str | None, should_contain: bool, label: str) -> tuple[bool, str]:
    if needle is None:
        return True, ""
    present = needle in text
    ok = present if should_contain else not present
    return ok, "" if ok else f"{label} mismatch"


def _regex(text: str, pattern: str | None, label: str) -> tuple[bool, str]:
    if pattern is None:
        return True, ""
    ok = re.search(pattern, text) is not None
    return ok, "" if ok else f"{label} mismatch"


def _paths(existing: frozenset[str], expected: tuple[str, ...], should_exist: bool, label: str) -> tuple[bool, str]:
    for path in expected:
        if (path in existing) != should_exist:
            return False, f"{label} mismatch: {path}"
    return True, ""
