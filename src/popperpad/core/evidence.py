from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from .check import RunIntent
from .codec import canonical_json_bytes, sha256_bytes
from .result import Reject
from .values import DeeplyImmutable, FrozenDict, JsonValue, freeze_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ExecutionStatus(DeeplyImmutable):
    value: str

    PASS: ClassVar[ExecutionStatus]
    FAIL: ClassVar[ExecutionStatus]
    SKIP: ClassVar[ExecutionStatus]
    TIMEOUT: ClassVar[ExecutionStatus]
    ERROR: ClassVar[ExecutionStatus]

    def __post_init__(self) -> None:
        if type(self.value) is not str or self.value not in {
            "PASS",
            "FAIL",
            "SKIP",
            "TIMEOUT",
            "ERROR",
        }:
            raise ValueError("invalid execution status")
        DeeplyImmutable.__post_init__(self)


ExecutionStatus.PASS = ExecutionStatus("PASS")
ExecutionStatus.FAIL = ExecutionStatus("FAIL")
ExecutionStatus.SKIP = ExecutionStatus("SKIP")
ExecutionStatus.TIMEOUT = ExecutionStatus("TIMEOUT")
ExecutionStatus.ERROR = ExecutionStatus("ERROR")


@dataclass(frozen=True, slots=True)
class CapturedOutput(DeeplyImmutable):
    name: str
    ref: str
    byte_size: int
    truncated: bool
    path: str
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        for field_name in ("name", "ref", "path", "media_type"):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise TypeError(f"{field_name} must be a non-empty string")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise TypeError("byte_size must be a non-negative integer")
        if type(self.truncated) is not bool:
            raise TypeError("truncated must be a bool")
        DeeplyImmutable.__post_init__(self)

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "name": self.name,
                "ref": self.ref,
                "bytes": self.byte_size,
                "truncated": self.truncated,
                "path": self.path,
                "media_type": self.media_type,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


@dataclass(frozen=True, slots=True)
class CheckExecution(DeeplyImmutable):
    intent: RunIntent
    recipe_ref: str
    hypothesis_ref: str
    context_ref: str | None
    created_at: str
    status: ExecutionStatus
    reason: str
    exit_code: int | None
    stdout_ref: str
    stderr_ref: str
    outputs: tuple[CapturedOutput, ...]
    toolchain: FrozenDict[JsonValue]
    duration_ms: int
    argv: tuple[str, ...]
    stdout_truncated: bool
    stderr_truncated: bool

    def __post_init__(self) -> None:
        if type(self.intent) is not RunIntent:
            raise TypeError("intent must be RunIntent")
        for field_name in ("recipe_ref", "hypothesis_ref", "created_at", "reason"):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise TypeError(f"{field_name} must be a non-empty string")
        if self.context_ref is not None and type(self.context_ref) is not str:
            raise TypeError("context_ref must be null or a string")
        if type(self.status) is not ExecutionStatus:
            raise TypeError("status must be ExecutionStatus")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be null or an integer")
        for field_name in ("stdout_ref", "stderr_ref"):
            if type(getattr(self, field_name)) is not str:
                raise TypeError(f"{field_name} must be a string")
        if type(self.outputs) is not tuple or not all(
            type(output) is CapturedOutput for output in self.outputs
        ):
            raise TypeError("outputs must contain CapturedOutput values")
        if type(self.toolchain) is not FrozenDict:
            raise TypeError("toolchain must be FrozenDict")
        if type(self.duration_ms) is not int or self.duration_ms < 0:
            raise TypeError("duration_ms must be a non-negative integer")
        if type(self.argv) is not tuple or not all(type(arg) is str for arg in self.argv):
            raise TypeError("argv must be a tuple of strings")
        if type(self.stdout_truncated) is not bool or type(self.stderr_truncated) is not bool:
            raise TypeError("truncation flags must be bools")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class PlannedCheckObjects(DeeplyImmutable):
    objects: tuple[FrozenDict[JsonValue], ...]
    evidence_ref: str
    artifact_ref: str | None
    edge_ref: str | None

    def __post_init__(self) -> None:
        if type(self.objects) is not tuple or not all(
            type(value) is FrozenDict for value in self.objects
        ):
            raise TypeError("objects must contain FrozenDict values")
        if type(self.evidence_ref) is not str or not self.evidence_ref:
            raise TypeError("evidence_ref must be a non-empty string")
        for field_name in ("artifact_ref", "edge_ref"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not str or not value):
                raise TypeError(f"{field_name} must be null or a non-empty string")
        DeeplyImmutable.__post_init__(self)


def _reject(code: str, field: str, reason: str) -> Reject:
    details = freeze_json({"field": field, "reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code, details)


def _valid_ref(value: str, *, optional: bool = False) -> bool:
    return (optional and value == "") or bool(_REF_RE.fullmatch(value))


def object_ref(value: FrozenDict[JsonValue]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def plan_check_objects(execution: CheckExecution) -> PlannedCheckObjects | Reject:
    """Purely build the complete evidence/artifact/edge candidate set.

    The shell supplies the captured clock, process observation, toolchain, and
    blob refs. This function performs no I/O and returns all authority-relevant
    objects together so one commit can publish them atomically.
    """

    for field, value in (
        ("recipe_ref", execution.recipe_ref),
        ("hypothesis_ref", execution.hypothesis_ref),
    ):
        if not _valid_ref(value):
            return _reject("INVALID_CHECK_EXECUTION", field, "must be sha256:<64hex>")
    if execution.context_ref is not None and not _valid_ref(execution.context_ref):
        return _reject("INVALID_CHECK_EXECUTION", "context_ref", "must be null or sha256:<64hex>")
    if not execution.created_at:
        return _reject("INVALID_CHECK_EXECUTION", "created_at", "must be non-empty")
    if execution.duration_ms < 0:
        return _reject("INVALID_CHECK_EXECUTION", "duration_ms", "must be non-negative")
    for field, value in (("stdout_ref", execution.stdout_ref), ("stderr_ref", execution.stderr_ref)):
        if not _valid_ref(value, optional=True):
            return _reject("INVALID_CHECK_EXECUTION", field, "must be empty or sha256:<64hex>")
    for index, output in enumerate(execution.outputs):
        if not output.name:
            return _reject("INVALID_CHECK_EXECUTION", f"outputs[{index}].name", "must be non-empty")
        if not _valid_ref(output.ref):
            return _reject("INVALID_CHECK_EXECUTION", f"outputs[{index}].ref", "must be sha256:<64hex>")
        if output.byte_size < 0:
            return _reject("INVALID_CHECK_EXECUTION", f"outputs[{index}].bytes", "must be non-negative")

    evidence_value: dict[str, JsonValue | object] = {
        "schema": "popperpad/evidence/v1",
        "evidence_kind": "check",
        "created_at": execution.created_at,
        "recipe_ref": execution.recipe_ref,
        "context_ref": execution.context_ref,
        "subject_refs": (execution.hypothesis_ref,),
        "result": {
            "status": execution.status.value.lower(),
            "exit_code": execution.exit_code,
        },
        "reason": execution.reason,
        "toolchain": execution.toolchain,
        "duration_ms": execution.duration_ms,
        "argv": execution.argv,
        "stdout_truncated": execution.stdout_truncated,
        "stderr_truncated": execution.stderr_truncated,
        "outputs": tuple(output.as_json() for output in execution.outputs),
    }
    if execution.stdout_ref:
        evidence_value["stdout_ref"] = execution.stdout_ref
    if execution.stderr_ref:
        evidence_value["stderr_ref"] = execution.stderr_ref
    evidence = freeze_json(evidence_value)
    assert isinstance(evidence, FrozenDict)
    evidence_ref = object_ref(evidence)

    objects: list[FrozenDict[JsonValue]] = [evidence]
    artifact_ref: str | None = None
    edge_ref: str | None = None
    if execution.status != ExecutionStatus.PASS:
        return PlannedCheckObjects(tuple(objects), evidence_ref, None, None)

    if execution.intent == RunIntent.PROVE:
        edge_from_ref = evidence_ref
        edge_type = "supports"
    else:
        edge_type = "refutes"
        if execution.outputs:
            first = execution.outputs[0]
            artifact = freeze_json(
                {
                    "schema": "popperpad/artifact/v1",
                    "name": first.name,
                    "kind": "counterexample",
                    "media_type": first.media_type,
                    "blob_ref": first.ref,
                }
            )
            assert isinstance(artifact, FrozenDict)
            artifact_ref = object_ref(artifact)
            objects.append(artifact)
            edge_from_ref = artifact_ref
        else:
            edge_from_ref = evidence_ref

    edge = freeze_json(
        {
            "schema": "popperpad/edge/v1",
            "edge_type": edge_type,
            "from_ref": edge_from_ref,
            "to_ref": execution.hypothesis_ref,
            "context_ref": execution.context_ref,
            "evidence_refs": (evidence_ref,),
        }
    )
    assert isinstance(edge, FrozenDict)
    edge_ref = object_ref(edge)
    objects.append(edge)
    return PlannedCheckObjects(tuple(objects), evidence_ref, artifact_ref, edge_ref)
