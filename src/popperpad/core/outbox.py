from __future__ import annotations

import re
from dataclasses import dataclass

from .codec import canonical_hash
from .result import Reject
from .values import DeeplyImmutable, FrozenDict, JsonValue, freeze_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CommittedEffect(DeeplyImmutable):
    effect_id: str
    commit_record_hash: str
    kind: str
    payload: FrozenDict[JsonValue]


@dataclass(frozen=True, slots=True)
class DeliveryAcknowledgement(DeeplyImmutable):
    effect_id: str
    commit_record_hash: str
    handler_id: str
    delivered_at: str
    delivery_receipt: FrozenDict[JsonValue]
    previous_ack_hash: str
    ack_hash: str

    def core_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": "popperpad/outbox-ack/v1",
                "effect_id": self.effect_id,
                "commit_record_hash": self.commit_record_hash,
                "handler_id": self.handler_id,
                "delivered_at": self.delivered_at,
                "delivery_receipt": self.delivery_receipt,
                "previous_ack_hash": self.previous_ack_hash,
            }
        )
        assert isinstance(value, FrozenDict)
        return value

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json({**dict(self.core_json().items_tuple()), "ack_hash": self.ack_hash})
        assert isinstance(value, FrozenDict)
        return value


@dataclass(frozen=True, slots=True)
class OutboxSnapshot(DeeplyImmutable):
    effects: tuple[CommittedEffect, ...]
    acknowledgements: tuple[DeliveryAcknowledgement, ...]


@dataclass(frozen=True, slots=True)
class PendingOutbox(DeeplyImmutable):
    effects: tuple[CommittedEffect, ...]


@dataclass(frozen=True, slots=True)
class DeliveryAttempt(DeeplyImmutable):
    effect_id: str
    status: str  # delivered|failed|missing_handler|already_delivered
    acknowledgement_hash: str = ""
    error: str = ""


def _reject(code: str, reason: str) -> Reject:
    details = freeze_json({"reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code=code, details=details)


def _valid_ref(value: str, *, optional: bool = False) -> bool:
    return (optional and value == "") or bool(_REF_RE.fullmatch(value))


def pending_outbox(snapshot: OutboxSnapshot) -> PendingOutbox | Reject:
    """Return the deterministic pending effect set from a complete snapshot.

    Duplicate effect IDs are permitted only when every immutable field agrees,
    which makes re-importing the same committed history idempotent. Conflicting
    duplicates fail closed.
    """

    effects_by_id: dict[str, CommittedEffect] = {}
    for effect in snapshot.effects:
        if not _valid_ref(effect.effect_id):
            return _reject("INVALID_EFFECT_ID", effect.effect_id)
        if not _valid_ref(effect.commit_record_hash):
            return _reject("INVALID_COMMIT_RECORD_HASH", effect.commit_record_hash)
        if not effect.kind:
            return _reject("INVALID_EFFECT_KIND", "effect kind must be non-empty")
        previous = effects_by_id.get(effect.effect_id)
        if previous is not None and previous != effect:
            return _reject("CONFLICTING_EFFECT_ID", effect.effect_id)
        effects_by_id[effect.effect_id] = effect

    acknowledged: dict[str, DeliveryAcknowledgement] = {}
    for acknowledgement in snapshot.acknowledgements:
        if not _valid_ref(acknowledgement.effect_id):
            return _reject("INVALID_ACK_EFFECT_ID", acknowledgement.effect_id)
        effect = effects_by_id.get(acknowledgement.effect_id)
        if effect is None:
            return _reject("ACK_FOR_UNKNOWN_EFFECT", acknowledgement.effect_id)
        if acknowledgement.commit_record_hash != effect.commit_record_hash:
            return _reject("ACK_COMMIT_MISMATCH", acknowledgement.effect_id)
        previous = acknowledged.get(acknowledgement.effect_id)
        if previous is not None and previous != acknowledgement:
            return _reject("CONFLICTING_ACK", acknowledgement.effect_id)
        acknowledged[acknowledgement.effect_id] = acknowledgement

    return PendingOutbox(
        effects=tuple(
            effect
            for effect_id, effect in sorted(effects_by_id.items())
            if effect_id not in acknowledged
        )
    )


def plan_acknowledgement(
    *,
    effect: CommittedEffect,
    handler_id: str,
    delivered_at: str,
    delivery_receipt: FrozenDict[JsonValue],
    previous_ack_hash: str,
) -> DeliveryAcknowledgement | Reject:
    """Purely bind an external delivery receipt to one committed effect."""

    if not _valid_ref(effect.effect_id):
        return _reject("INVALID_EFFECT_ID", effect.effect_id)
    if not _valid_ref(effect.commit_record_hash):
        return _reject("INVALID_COMMIT_RECORD_HASH", effect.commit_record_hash)
    if not handler_id:
        return _reject("INVALID_HANDLER_ID", "handler_id must be non-empty")
    if not delivered_at:
        return _reject("INVALID_DELIVERED_AT", "delivered_at must be non-empty")
    if not _valid_ref(previous_ack_hash, optional=True):
        return _reject("INVALID_ACK_HEAD", previous_ack_hash)

    core = freeze_json(
        {
            "schema": "popperpad/outbox-ack/v1",
            "effect_id": effect.effect_id,
            "commit_record_hash": effect.commit_record_hash,
            "handler_id": handler_id,
            "delivered_at": delivered_at,
            "delivery_receipt": delivery_receipt,
            "previous_ack_hash": previous_ack_hash,
        }
    )
    assert isinstance(core, FrozenDict)
    ack_hash = canonical_hash("outbox-ack/v1", core)
    return DeliveryAcknowledgement(
        effect_id=effect.effect_id,
        commit_record_hash=effect.commit_record_hash,
        handler_id=handler_id,
        delivered_at=delivered_at,
        delivery_receipt=delivery_receipt,
        previous_ack_hash=previous_ack_hash,
        ack_hash=ack_hash,
    )


def verify_ack_chain(
    acknowledgements: tuple[DeliveryAcknowledgement, ...],
) -> tuple[DeliveryAcknowledgement, ...] | Reject:
    """Verify canonical hashes and linear acknowledgement ancestry."""

    previous = ""
    seen_effects: dict[str, DeliveryAcknowledgement] = {}
    for index, acknowledgement in enumerate(acknowledgements):
        if acknowledgement.previous_ack_hash != previous:
            return _reject("ACK_CHAIN_PREDECESSOR_MISMATCH", f"index={index}")
        expected_hash = canonical_hash("outbox-ack/v1", acknowledgement.core_json())
        if acknowledgement.ack_hash != expected_hash:
            return _reject("ACK_HASH_MISMATCH", acknowledgement.effect_id)
        prior = seen_effects.get(acknowledgement.effect_id)
        if prior is not None and prior != acknowledgement:
            return _reject("CONFLICTING_ACK", acknowledgement.effect_id)
        seen_effects[acknowledgement.effect_id] = acknowledgement
        previous = acknowledgement.ack_hash
    return acknowledgements
