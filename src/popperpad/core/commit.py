from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .codec import canonical_hash, canonical_json_bytes, sha256_bytes
from .result import Reject
from .values import DeeplyImmutable, FrozenDict, JsonValue, freeze_json, thaw_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOG_SCHEMA_V2 = "popperpad/log_record/v2"


@dataclass(frozen=True, slots=True)
class ObjectWrite(DeeplyImmutable):
    ref: str
    schema: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class BlobWrite(DeeplyImmutable):
    ref: str
    media_type: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class OutboxEffect(DeeplyImmutable):
    effect_id: str
    kind: str
    payload: FrozenDict[JsonValue]


@dataclass(frozen=True, slots=True)
class ReceiptDraft(DeeplyImmutable):
    version: str
    pre_state_root: str
    command_hash: str
    evidence_root: str
    policy_version: str
    core_version: str
    replay_id: str
    next_state_root: str
    effect_plan_hash: str

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "version": self.version,
                "pre_state_root": self.pre_state_root,
                "command_hash": self.command_hash,
                "evidence_root": self.evidence_root,
                "policy_version": self.policy_version,
                "core_version": self.core_version,
                "replay_id": self.replay_id,
                "next_state_root": self.next_state_root,
                "effect_plan_hash": self.effect_plan_hash,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


@dataclass(frozen=True, slots=True)
class CommitBundle(DeeplyImmutable):
    expected_head: str
    commit_root: str
    record_hash: str
    objects: tuple[ObjectWrite, ...]
    blobs: tuple[BlobWrite, ...]
    outbox: tuple[OutboxEffect, ...]
    receipt: ReceiptDraft
    record: FrozenDict[JsonValue]

    def logical_records(self) -> tuple[FrozenDict[JsonValue], ...]:
        rows: list[FrozenDict[JsonValue]] = []
        for item in self.objects:
            row = freeze_json(
                {
                    "schema": "popperpad/log_record/v1",
                    "op": "add_object",
                    "created_at": self.record["created_at"],
                    "obj_ref": item.ref,
                    "obj_schema": item.schema,
                    "commit_record_hash": self.record_hash,
                }
            )
            assert isinstance(row, FrozenDict)
            rows.append(row)
        for item in self.blobs:
            row = freeze_json(
                {
                    "schema": "popperpad/log_record/v1",
                    "op": "add_blob",
                    "created_at": self.record["created_at"],
                    "blob_ref": item.ref,
                    "media_type": item.media_type,
                    "commit_record_hash": self.record_hash,
                }
            )
            assert isinstance(row, FrozenDict)
            rows.append(row)
        return tuple(rows)


def _reject(code: str, reason: str) -> Reject:
    details = freeze_json({"reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code, details)


def _valid_root(value: str) -> bool:
    return value == "" or bool(_REF_RE.fullmatch(value))


def _freeze_payload(value: Mapping[str, Any]) -> FrozenDict[JsonValue] | Reject:
    try:
        frozen = freeze_json(value)
    except (TypeError, ValueError) as exc:
        return _reject("INVALID_OBJECT", str(exc))
    if not isinstance(frozen, FrozenDict):
        return _reject("INVALID_OBJECT", "object payload must be a mapping")
    return frozen


def plan_commit(
    *,
    expected_head: str,
    created_at: str,
    objects: tuple[Mapping[str, Any], ...] = (),
    blobs: tuple[tuple[bytes, str], ...] = (),
    outbox: tuple[tuple[str, Mapping[str, Any]], ...] = (),
    evidence_root: str = "",
    policy_version: str = "popperpad-policy/v1",
    core_version: str = "popperpad-core/v1",
) -> CommitBundle | Reject:
    """Purely construct one exact atomic commit and receipt plan."""

    if not _valid_root(expected_head):
        return _reject("INVALID_PRE_STATE_ROOT", "expected_head must be empty or sha256:<64hex>")
    if not isinstance(created_at, str) or not created_at:
        return _reject("INVALID_CREATED_AT", "created_at must be a non-empty string")
    if evidence_root and not _valid_root(evidence_root):
        return _reject("INVALID_EVIDENCE_ROOT", "evidence_root must be empty or sha256:<64hex>")

    object_writes: list[ObjectWrite] = []
    object_rows: list[dict[str, JsonValue]] = []
    seen_refs: set[str] = set()
    for raw in objects:
        frozen = _freeze_payload(raw)
        if isinstance(frozen, Reject):
            return frozen
        schema = frozen.get("schema")
        if not isinstance(schema, str) or not schema:
            return _reject("INVALID_OBJECT_SCHEMA", "every object must carry a non-empty schema")
        payload = canonical_json_bytes(frozen)
        ref = sha256_bytes(payload)
        if ref in seen_refs:
            return _reject("DUPLICATE_WRITE", f"duplicate object ref: {ref}")
        seen_refs.add(ref)
        object_writes.append(ObjectWrite(ref=ref, schema=schema, payload=payload))
        object_rows.append({"ref": ref, "schema": schema, "bytes": len(payload)})

    blob_writes: list[BlobWrite] = []
    blob_rows: list[dict[str, JsonValue]] = []
    for payload, media_type in blobs:
        if not isinstance(payload, bytes):
            return _reject("INVALID_BLOB", "blob payload must be bytes")
        if not isinstance(media_type, str) or not media_type:
            return _reject("INVALID_MEDIA_TYPE", "blob media type must be a non-empty string")
        ref = sha256_bytes(payload)
        if ref in seen_refs:
            return _reject("DUPLICATE_WRITE", f"duplicate object/blob ref: {ref}")
        seen_refs.add(ref)
        blob_writes.append(BlobWrite(ref=ref, media_type=media_type, payload=payload))
        blob_rows.append({"ref": ref, "media_type": media_type, "bytes": len(payload)})

    command_value = {
        "expected_head": expected_head,
        "objects": object_rows,
        "blobs": blob_rows,
        "policy_version": policy_version,
        "core_version": core_version,
    }
    command_hash = canonical_hash("commit-command/v1", command_value)
    replay_id = canonical_hash(
        "replay-id/v1",
        {"pre_state_root": expected_head, "command_hash": command_hash},
    )

    outbox_effects: list[OutboxEffect] = []
    effect_rows: list[dict[str, JsonValue]] = []
    for index, (kind, raw_payload) in enumerate(outbox):
        if not isinstance(kind, str) or not kind:
            return _reject("INVALID_EFFECT", "effect kind must be a non-empty string")
        frozen_payload = _freeze_payload(raw_payload)
        if isinstance(frozen_payload, Reject):
            return frozen_payload
        effect_id = canonical_hash(
            "outbox-effect-id/v1",
            {"replay_id": replay_id, "index": index, "kind": kind, "payload": frozen_payload},
        )
        outbox_effects.append(OutboxEffect(effect_id=effect_id, kind=kind, payload=frozen_payload))
        effect_rows.append({"effect_id": effect_id, "kind": kind, "payload": frozen_payload})

    effect_plan_hash = canonical_hash("effect-plan/v1", effect_rows)
    commit_value = {
        "expected_head": expected_head,
        "created_at": created_at,
        "command_hash": command_hash,
        "evidence_root": evidence_root,
        "objects": object_rows,
        "blobs": blob_rows,
        "outbox": effect_rows,
        "policy_version": policy_version,
        "core_version": core_version,
    }
    commit_root = canonical_hash("commit-bundle/v1", commit_value)
    receipt = ReceiptDraft(
        version="popperpad/receipt/v1",
        pre_state_root=expected_head,
        command_hash=command_hash,
        evidence_root=evidence_root,
        policy_version=policy_version,
        core_version=core_version,
        replay_id=replay_id,
        next_state_root=commit_root,
        effect_plan_hash=effect_plan_hash,
    )
    record_core = {
        "schema": _LOG_SCHEMA_V2,
        "op": "commit_bundle",
        "created_at": created_at,
        "prev_record_hash": expected_head,
        "commit_root": commit_root,
        "objects": object_rows,
        "blobs": blob_rows,
        "outbox": effect_rows,
        "receipt": receipt.as_json(),
    }
    record_hash = canonical_hash("log-record/v2", record_core)
    record = freeze_json({**record_core, "record_hash": record_hash})
    assert isinstance(record, FrozenDict)
    return CommitBundle(
        expected_head=expected_head,
        commit_root=commit_root,
        record_hash=record_hash,
        objects=tuple(object_writes),
        blobs=tuple(blob_writes),
        outbox=tuple(outbox_effects),
        receipt=receipt,
        record=record,
    )
