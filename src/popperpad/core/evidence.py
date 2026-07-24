from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .check import RunIntent
from .codec import canonical_json_bytes, sha256_bytes
from .result import Reject
from .values import FrozenDict, JsonValue, freeze_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ExecutionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class CapturedOutput:
    name: str
    ref: str
    byte_size: int
    truncated: bool
    path: str
    media_type: str = "application/octet-stream"

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
class CheckExecution:
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


@dataclass(frozen=True, slots=True)
class PlannedCheckObjects:
    objects: tuple[FrozenDict[JsonValue], ...]
    evidence_ref: str
    artifact_ref: str | None
    edge_ref: str | None


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
    if execution.status is not ExecutionStatus.PASS:
        return PlannedCheckObjects(tuple(objects), evidence_ref, None, None)

    if execution.intent is RunIntent.PROVE:
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
