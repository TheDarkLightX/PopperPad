from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .codec import canonical_hash, canonical_json_bytes, sha256_bytes
from .result import Reject
from .values import DeeplyImmutable, FrozenDict, JsonValue, freeze_json, thaw_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOG_SCHEMA_V2 = "popperpad/log_record/v2"
_RECEIPT_V1 = "popperpad/receipt/v1"
_RECEIPT_V2 = "popperpad/receipt/v2"


def logical_authority_scope(policy_version: object) -> str | None:
    """Project committed import policy into graph authority provenance."""

    if type(policy_version) is not str or not policy_version.startswith(
        "popperpad-import-policy/"
    ):
        return None
    if policy_version.startswith("popperpad-import-policy/v2/trusted-receipt/"):
        return "import_trusted_receipt"
    return "import_quarantined"


@dataclass(frozen=True, slots=True)
class ObjectWrite(DeeplyImmutable):
    ref: str
    schema: str
    payload: bytes

    def __post_init__(self) -> None:
        _require_ref("ref", self.ref)
        _require_string("schema", self.schema)
        if type(self.payload) is not bytes:
            raise TypeError("payload must be bytes")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class BlobWrite(DeeplyImmutable):
    ref: str
    media_type: str
    payload: bytes

    def __post_init__(self) -> None:
        _require_ref("ref", self.ref)
        _require_string("media_type", self.media_type)
        if type(self.payload) is not bytes:
            raise TypeError("payload must be bytes")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class OutboxEffect(DeeplyImmutable):
    effect_id: str
    kind: str
    payload: FrozenDict[JsonValue]

    def __post_init__(self) -> None:
        _require_ref("effect_id", self.effect_id)
        _require_string("kind", self.kind)
        if type(self.payload) is not FrozenDict:
            raise TypeError("payload must be FrozenDict")
        DeeplyImmutable.__post_init__(self)


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

    def __post_init__(self) -> None:
        for field_name in (
            "version",
            "command_hash",
            "policy_version",
            "core_version",
            "replay_id",
            "next_state_root",
            "effect_plan_hash",
        ):
            _require_string(field_name, getattr(self, field_name))
        for field_name in ("pre_state_root", "evidence_root"):
            value = getattr(self, field_name)
            if type(value) is not str:
                raise TypeError(f"{field_name} must be a string")
        DeeplyImmutable.__post_init__(self)

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

    def __post_init__(self) -> None:
        if type(self.expected_head) is not str:
            raise TypeError("expected_head must be a string")
        _require_ref("commit_root", self.commit_root)
        _require_ref("record_hash", self.record_hash)
        _require_value_tuple("objects", self.objects, ObjectWrite)
        _require_value_tuple("blobs", self.blobs, BlobWrite)
        _require_value_tuple("outbox", self.outbox, OutboxEffect)
        if type(self.receipt) is not ReceiptDraft:
            raise TypeError("receipt must be ReceiptDraft")
        if type(self.record) is not FrozenDict:
            raise TypeError("record must be FrozenDict")
        DeeplyImmutable.__post_init__(self)

    def logical_records(self) -> tuple[FrozenDict[JsonValue], ...]:
        rows: list[FrozenDict[JsonValue]] = []
        authority_scope = logical_authority_scope(self.receipt.policy_version)
        for item in self.objects:
            fields: dict[str, JsonValue] = {
                "schema": "popperpad/log_record/v1",
                "op": "add_object",
                "created_at": self.record["created_at"],
                "obj_ref": item.ref,
                "obj_schema": item.schema,
                "commit_record_hash": self.record_hash,
            }
            if authority_scope is not None:
                fields["authority_scope"] = authority_scope
            row = freeze_json(fields)
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


@dataclass(frozen=True, slots=True)
class ValidatedCommitRecord(DeeplyImmutable):
    expected_head: str
    receipt_version: str
    record_hash: str
    record: FrozenDict[JsonValue]

    def __post_init__(self) -> None:
        if not _valid_root(self.expected_head):
            raise TypeError("expected_head must be empty or a sha256 ref")
        if self.receipt_version not in {_RECEIPT_V1, _RECEIPT_V2}:
            raise TypeError("unsupported receipt_version")
        _require_ref("record_hash", self.record_hash)
        if type(self.record) is not FrozenDict:
            raise TypeError("record must be FrozenDict")
        DeeplyImmutable.__post_init__(self)


def _reject(code: str, reason: str) -> Reject:
    details = freeze_json({"reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code, details)


def _require_string(field_name: str, value: object) -> None:
    if type(value) is not str or not value:
        raise TypeError(f"{field_name} must be a non-empty string")


def _require_ref(field_name: str, value: object) -> None:
    if type(value) is not str or not _REF_RE.fullmatch(value):
        raise TypeError(f"{field_name} must be a sha256 ref")


def _require_value_tuple(field_name: str, value: object, item_type: type[object]) -> None:
    if type(value) is not tuple or not all(type(item) is item_type for item in value):
        raise TypeError(f"{field_name} must be a tuple of {item_type.__name__} values")


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


def _frozen_row(value: Mapping[str, Any]) -> FrozenDict[JsonValue]:
    frozen = freeze_json(value)
    assert isinstance(frozen, FrozenDict)
    return frozen


def _derive_commit_record(
    *,
    receipt_version: str,
    expected_head: str,
    created_at: str,
    object_rows: tuple[FrozenDict[JsonValue], ...],
    blob_rows: tuple[FrozenDict[JsonValue], ...],
    outbox_intents: tuple[tuple[str, FrozenDict[JsonValue]], ...],
    evidence_root: str,
    policy_version: str,
    core_version: str,
) -> tuple[
    ReceiptDraft,
    tuple[OutboxEffect, ...],
    str,
    str,
    FrozenDict[JsonValue],
]:
    intent_rows = tuple(
        _frozen_row({"kind": kind, "payload": payload})
        for kind, payload in outbox_intents
    )
    if receipt_version == _RECEIPT_V1:
        command_domain = "commit-command/v1"
        replay_domain = "replay-id/v1"
        effect_id_domain = "outbox-effect-id/v1"
        effect_plan_domain = "effect-plan/v1"
        commit_domain = "commit-bundle/v1"
        command_value: Mapping[str, Any] = {
            "expected_head": expected_head,
            "objects": object_rows,
            "blobs": blob_rows,
            "policy_version": policy_version,
            "core_version": core_version,
        }
    elif receipt_version == _RECEIPT_V2:
        command_domain = "commit-command/v2"
        replay_domain = "replay-id/v2"
        effect_id_domain = "outbox-effect-id/v2"
        effect_plan_domain = "effect-plan/v2"
        commit_domain = "commit-bundle/v2"
        command_value = {
            "expected_head": expected_head,
            "created_at": created_at,
            "evidence_root": evidence_root,
            "objects": object_rows,
            "blobs": blob_rows,
            "outbox": intent_rows,
            "policy_version": policy_version,
            "core_version": core_version,
        }
    else:
        raise ValueError(f"unsupported receipt version: {receipt_version}")

    command_hash = canonical_hash(command_domain, command_value)
    replay_id = canonical_hash(
        replay_domain,
        {"pre_state_root": expected_head, "command_hash": command_hash},
    )
    outbox_effects: list[OutboxEffect] = []
    effect_rows: list[FrozenDict[JsonValue]] = []
    for index, (kind, payload) in enumerate(outbox_intents):
        effect_id = canonical_hash(
            effect_id_domain,
            {
                "replay_id": replay_id,
                "index": index,
                "kind": kind,
                "payload": payload,
            },
        )
        effect = OutboxEffect(effect_id=effect_id, kind=kind, payload=payload)
        outbox_effects.append(effect)
        effect_rows.append(
            _frozen_row({"effect_id": effect_id, "kind": kind, "payload": payload})
        )

    frozen_effect_rows = tuple(effect_rows)
    effect_plan_hash = canonical_hash(effect_plan_domain, frozen_effect_rows)
    commit_value = {
        "expected_head": expected_head,
        "created_at": created_at,
        "command_hash": command_hash,
        "evidence_root": evidence_root,
        "objects": object_rows,
        "blobs": blob_rows,
        "outbox": frozen_effect_rows,
        "policy_version": policy_version,
        "core_version": core_version,
    }
    commit_root = canonical_hash(commit_domain, commit_value)
    receipt = ReceiptDraft(
        version=receipt_version,
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
        "outbox": frozen_effect_rows,
        "receipt": receipt.as_json(),
    }
    record_hash = canonical_hash("log-record/v2", record_core)
    record = freeze_json({**record_core, "record_hash": record_hash})
    assert isinstance(record, FrozenDict)
    return receipt, tuple(outbox_effects), commit_root, record_hash, record


def _require_exact_keys(value: object, expected: frozenset[str], field_name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{field_name} must be an object")
    if frozenset(value) != expected:
        raise ValueError(f"{field_name} has missing or unknown fields")
    return value


def _parse_object_rows(value: object) -> tuple[FrozenDict[JsonValue], ...]:
    if type(value) is not list:
        raise ValueError("objects must be an array")
    rows: list[FrozenDict[JsonValue]] = []
    for index, raw in enumerate(value):
        row = _require_exact_keys(raw, frozenset({"ref", "schema", "bytes"}), f"objects[{index}]")
        _require_ref(f"objects[{index}].ref", row["ref"])
        _require_string(f"objects[{index}].schema", row["schema"])
        if type(row["bytes"]) is not int or row["bytes"] < 0:
            raise ValueError(f"objects[{index}].bytes must be a non-negative integer")
        rows.append(_frozen_row(row))
    return tuple(rows)


def _parse_blob_rows(value: object) -> tuple[FrozenDict[JsonValue], ...]:
    if type(value) is not list:
        raise ValueError("blobs must be an array")
    rows: list[FrozenDict[JsonValue]] = []
    for index, raw in enumerate(value):
        row = _require_exact_keys(raw, frozenset({"ref", "media_type", "bytes"}), f"blobs[{index}]")
        _require_ref(f"blobs[{index}].ref", row["ref"])
        _require_string(f"blobs[{index}].media_type", row["media_type"])
        if type(row["bytes"]) is not int or row["bytes"] < 0:
            raise ValueError(f"blobs[{index}].bytes must be a non-negative integer")
        rows.append(_frozen_row(row))
    return tuple(rows)


def _parse_outbox_rows(
    value: object,
) -> tuple[tuple[str, FrozenDict[JsonValue]], ...]:
    if type(value) is not list:
        raise ValueError("outbox must be an array")
    intents: list[tuple[str, FrozenDict[JsonValue]]] = []
    for index, raw in enumerate(value):
        row = _require_exact_keys(
            raw,
            frozenset({"effect_id", "kind", "payload"}),
            f"outbox[{index}]",
        )
        _require_ref(f"outbox[{index}].effect_id", row["effect_id"])
        _require_string(f"outbox[{index}].kind", row["kind"])
        payload = _freeze_payload(row["payload"])
        if isinstance(payload, Reject):
            raise ValueError(f"outbox[{index}].payload must be an integer-only object")
        intents.append((row["kind"], payload))
    return tuple(intents)


def validate_commit_record(
    record: Mapping[str, Any],
    *,
    allow_legacy_receipt: bool = False,
) -> ValidatedCommitRecord | Reject:
    """Recompute every semantic commitment in one v2 authority record."""

    try:
        if not isinstance(record, Mapping):
            raise ValueError("record must be a mapping")
        owned = freeze_json(record)
        if not isinstance(owned, FrozenDict):
            raise ValueError("record must be an object")
        plain = _require_exact_keys(
            thaw_json(owned),
            frozenset(
                {
                    "schema",
                    "op",
                    "created_at",
                    "prev_record_hash",
                    "commit_root",
                    "objects",
                    "blobs",
                    "outbox",
                    "receipt",
                    "record_hash",
                }
            ),
            "record",
        )
        if plain["schema"] != _LOG_SCHEMA_V2 or plain["op"] != "commit_bundle":
            raise ValueError("record schema/op is not a v2 commit bundle")
        _require_string("created_at", plain["created_at"])
        if type(plain["prev_record_hash"]) is not str or not _valid_root(plain["prev_record_hash"]):
            raise ValueError("prev_record_hash must be empty or a sha256 ref")
        _require_ref("commit_root", plain["commit_root"])
        _require_ref("record_hash", plain["record_hash"])

        object_rows = _parse_object_rows(plain["objects"])
        blob_rows = _parse_blob_rows(plain["blobs"])
        refs = tuple(row["ref"] for row in (*object_rows, *blob_rows))
        if len(set(refs)) != len(refs):
            raise ValueError("object/blob refs must be unique")
        outbox_intents = _parse_outbox_rows(plain["outbox"])

        receipt = _require_exact_keys(
            plain["receipt"],
            frozenset(
                {
                    "version",
                    "pre_state_root",
                    "command_hash",
                    "evidence_root",
                    "policy_version",
                    "core_version",
                    "replay_id",
                    "next_state_root",
                    "effect_plan_hash",
                }
            ),
            "receipt",
        )
        receipt_version = receipt["version"]
        if receipt_version not in {_RECEIPT_V1, _RECEIPT_V2}:
            raise ValueError("unsupported receipt version")
        if receipt_version == _RECEIPT_V1 and not allow_legacy_receipt:
            raise ValueError("new publication requires popperpad/receipt/v2")
        if type(receipt["pre_state_root"]) is not str or not _valid_root(receipt["pre_state_root"]):
            raise ValueError("receipt pre_state_root is invalid")
        if type(receipt["evidence_root"]) is not str or not _valid_root(receipt["evidence_root"]):
            raise ValueError("receipt evidence_root is invalid")
        for field_name in (
            "command_hash",
            "replay_id",
            "next_state_root",
            "effect_plan_hash",
        ):
            _require_ref(f"receipt.{field_name}", receipt[field_name])
        _require_string("receipt.policy_version", receipt["policy_version"])
        _require_string("receipt.core_version", receipt["core_version"])

        derived = _derive_commit_record(
            receipt_version=receipt_version,
            expected_head=plain["prev_record_hash"],
            created_at=plain["created_at"],
            object_rows=object_rows,
            blob_rows=blob_rows,
            outbox_intents=outbox_intents,
            evidence_root=receipt["evidence_root"],
            policy_version=receipt["policy_version"],
            core_version=receipt["core_version"],
        )
        _receipt, _effects, _commit_root, record_hash, expected_record = derived
        if expected_record != owned:
            raise ValueError("record fields do not derive from one semantic commit candidate")
        return ValidatedCommitRecord(
            expected_head=plain["prev_record_hash"],
            receipt_version=receipt_version,
            record_hash=record_hash,
            record=owned,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _reject("INVALID_COMMIT_RECORD", str(exc))


def validate_commit_bundle(bundle: CommitBundle) -> ValidatedCommitRecord | Reject:
    """Bind payload bytes and typed plan values to a semantically valid record."""

    if type(bundle) is not CommitBundle:
        return _reject("INVALID_COMMIT_BUNDLE", "planned commit must be a CommitBundle")
    validated = validate_commit_record(bundle.record)
    if isinstance(validated, Reject):
        return validated
    plain = thaw_json(validated.record)
    expected_objects = [
        {"ref": item.ref, "schema": item.schema, "bytes": len(item.payload)}
        for item in bundle.objects
    ]
    expected_blobs = [
        {"ref": item.ref, "media_type": item.media_type, "bytes": len(item.payload)}
        for item in bundle.blobs
    ]
    expected_outbox = [
        {
            "effect_id": effect.effect_id,
            "kind": effect.kind,
            "payload": thaw_json(effect.payload),
        }
        for effect in bundle.outbox
    ]
    if any(sha256_bytes(item.payload) != item.ref for item in (*bundle.objects, *bundle.blobs)):
        return _reject("INVALID_COMMIT_BUNDLE", "payload bytes do not match their refs")
    if (
        bundle.expected_head != validated.expected_head
        or bundle.commit_root != plain["commit_root"]
        or bundle.record_hash != validated.record_hash
        or thaw_json(bundle.receipt.as_json()) != plain["receipt"]
        or expected_objects != plain["objects"]
        or expected_blobs != plain["blobs"]
        or expected_outbox != plain["outbox"]
    ):
        return _reject("INVALID_COMMIT_BUNDLE", "bundle fields differ from the validated record")
    return validated


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
    """Purely construct one exact atomic v2 commit and receipt plan."""

    return _plan_commit(
        expected_head=expected_head,
        created_at=created_at,
        objects=objects,
        prevalidated_objects=(),
        blobs=blobs,
        outbox=outbox,
        evidence_root=evidence_root,
        policy_version=policy_version,
        core_version=core_version,
    )


def plan_prevalidated_commit(
    *,
    expected_head: str,
    created_at: str,
    objects: tuple[tuple[bytes, str], ...] = (),
    blobs: tuple[tuple[bytes, str], ...] = (),
    evidence_root: str = "",
    policy_version: str = "popperpad-import-policy/v1",
    core_version: str = "popperpad-core/v1",
) -> CommitBundle | Reject:
    """Bind shell-validated legacy canonical object bytes into one commit.

    This compatibility planner does not reinterpret v1 JSON as integer-only v2
    values. The shell must validate each schema and canonical byte string first;
    this core function verifies types, content addresses, and duplicate writes,
    then commits only immutable refs and byte counts.
    """

    return _plan_commit(
        expected_head=expected_head,
        created_at=created_at,
        objects=(),
        prevalidated_objects=objects,
        blobs=blobs,
        outbox=(),
        evidence_root=evidence_root,
        policy_version=policy_version,
        core_version=core_version,
    )


def _plan_commit(
    *,
    expected_head: str,
    created_at: str,
    objects: tuple[Mapping[str, Any], ...],
    prevalidated_objects: tuple[tuple[bytes, str], ...],
    blobs: tuple[tuple[bytes, str], ...],
    outbox: tuple[tuple[str, Mapping[str, Any]], ...],
    evidence_root: str,
    policy_version: str,
    core_version: str,
) -> CommitBundle | Reject:
    """Construct one exact commit from ordinary or prevalidated object bytes."""

    if not _valid_root(expected_head):
        return _reject("INVALID_PRE_STATE_ROOT", "expected_head must be empty or sha256:<64hex>")
    if not isinstance(created_at, str) or not created_at:
        return _reject("INVALID_CREATED_AT", "created_at must be a non-empty string")
    if evidence_root and not _valid_root(evidence_root):
        return _reject("INVALID_EVIDENCE_ROOT", "evidence_root must be empty or sha256:<64hex>")

    object_writes: list[ObjectWrite] = []
    object_rows: list[FrozenDict[JsonValue]] = []
    seen_refs: set[str] = set()
    for payload, schema in prevalidated_objects:
        if not isinstance(payload, bytes):
            return _reject("INVALID_OBJECT", "prevalidated object payload must be bytes")
        if not isinstance(schema, str) or not schema:
            return _reject("INVALID_OBJECT_SCHEMA", "every object must carry a non-empty schema")
        ref = sha256_bytes(payload)
        if ref in seen_refs:
            return _reject("DUPLICATE_WRITE", f"duplicate object ref: {ref}")
        seen_refs.add(ref)
        object_writes.append(ObjectWrite(ref=ref, schema=schema, payload=payload))
        object_rows.append(_frozen_row({"ref": ref, "schema": schema, "bytes": len(payload)}))
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
        object_rows.append(_frozen_row({"ref": ref, "schema": schema, "bytes": len(payload)}))

    blob_writes: list[BlobWrite] = []
    blob_rows: list[FrozenDict[JsonValue]] = []
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
        blob_rows.append(_frozen_row({"ref": ref, "media_type": media_type, "bytes": len(payload)}))

    outbox_intents: list[tuple[str, FrozenDict[JsonValue]]] = []
    for kind, raw_payload in outbox:
        if type(kind) is not str or not kind:
            return _reject("INVALID_EFFECT", "effect kind must be a non-empty string")
        frozen_payload = _freeze_payload(raw_payload)
        if isinstance(frozen_payload, Reject):
            return frozen_payload
        outbox_intents.append((kind, frozen_payload))

    receipt, outbox_effects, commit_root, record_hash, record = _derive_commit_record(
        receipt_version=_RECEIPT_V2,
        expected_head=expected_head,
        created_at=created_at,
        object_rows=tuple(object_rows),
        blob_rows=tuple(blob_rows),
        outbox_intents=tuple(outbox_intents),
        evidence_root=evidence_root,
        policy_version=policy_version,
        core_version=core_version,
    )
    return CommitBundle(
        expected_head=expected_head,
        commit_root=commit_root,
        record_hash=record_hash,
        objects=tuple(object_writes),
        blobs=tuple(blob_writes),
        outbox=outbox_effects,
        receipt=receipt,
        record=record,
    )
