from __future__ import annotations

import json
from pathlib import Path

import pytest

from popperpad.core.outbox import (
    CommittedEffect,
    DeliveryAcknowledgement,
    OutboxSnapshot,
    pending_outbox,
    plan_acknowledgement,
    verify_ack_chain,
)
from popperpad.core.result import Reject
from popperpad.core.values import FrozenDict, freeze_json
from popperpad.outbox import Outbox, RegisteredHandler
from popperpad.pad import PopperPad
from popperpad.refs import ValidationError


def _receipt(**values: object) -> FrozenDict:
    frozen = freeze_json(values)
    assert isinstance(frozen, FrozenDict)
    return frozen


def _effect(char: str = "a") -> CommittedEffect:
    return CommittedEffect(
        effect_id="sha256:" + char * 64,
        commit_record_hash="sha256:" + "b" * 64,
        kind="notify",
        payload=_receipt(message="counterexample verified"),
    )


def test_pending_outbox_is_deterministic_and_fail_closed() -> None:
    effect = _effect()
    snapshot = OutboxSnapshot(effects=(effect,), acknowledgements=())
    planned = pending_outbox(snapshot)
    assert not isinstance(planned, Reject)
    assert planned.effects == (effect,)
    assert pending_outbox(snapshot) == planned

    conflicting = CommittedEffect(
        effect_id=effect.effect_id,
        commit_record_hash=effect.commit_record_hash,
        kind="different",
        payload=effect.payload,
    )
    rejected = pending_outbox(OutboxSnapshot((effect, conflicting), ()))
    assert isinstance(rejected, Reject)
    assert rejected.code == "CONFLICTING_EFFECT_ID"


def test_acknowledgement_is_canonical_and_chain_verified() -> None:
    effect = _effect()
    first = plan_acknowledgement(
        effect=effect,
        handler_id="test-handler/v1",
        delivered_at="2026-07-24T00:00:00Z",
        delivery_receipt=_receipt(remote_id="r1"),
        previous_ack_hash="",
    )
    assert isinstance(first, DeliveryAcknowledgement)
    assert first.ack_hash.startswith("sha256:")
    assert verify_ack_chain((first,)) == (first,)

    corrupt = DeliveryAcknowledgement(
        effect_id=first.effect_id,
        commit_record_hash=first.commit_record_hash,
        handler_id=first.handler_id,
        delivered_at=first.delivered_at,
        delivery_receipt=first.delivery_receipt,
        previous_ack_hash=first.previous_ack_hash,
        ack_hash="sha256:" + "0" * 64,
    )
    rejected = verify_ack_chain((corrupt,))
    assert isinstance(rejected, Reject)
    assert rejected.code == "ACK_HASH_MISMATCH"


def test_committed_effect_is_pending_then_delivered_exactly_once_after_ack(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    committed = pad.commit_values(
        outbox=(("notify", {"claim": "H1"}),),
        created_at="2026-07-24T00:00:00Z",
    )
    outbox = Outbox(log=pad.log, journal_path=pad.root / "outbox-acks.jsonl")
    outbox.init()
    pending = outbox.pending()
    assert len(pending.effects) == 1
    assert pending.effects[0].effect_id == committed.effect_ids[0]

    calls: list[tuple[str, dict]] = []

    def deliver(effect_id: str, payload: dict) -> dict:
        calls.append((effect_id, payload))
        return {"remote_id": "remote-1", "idempotency_key": effect_id}

    run = outbox.deliver_pending(
        handlers={"notify": RegisteredHandler("notify-handler/v1", deliver)},
        delivered_at=lambda: "2026-07-24T00:01:00Z",
    )
    assert run.ok
    assert len(calls) == 1
    assert calls[0][0] == committed.effect_ids[0]
    assert outbox.pending().effects == ()

    again = outbox.deliver_pending(
        handlers={"notify": RegisteredHandler("notify-handler/v1", deliver)},
        delivered_at=lambda: "2026-07-24T00:02:00Z",
    )
    assert again.attempts == ()
    assert len(calls) == 1
    outbox.verify()


def test_ambiguous_crash_retries_same_idempotency_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    committed = pad.commit_values(
        outbox=(("notify", {"claim": "H1"}),),
        created_at="2026-07-24T00:00:00Z",
    )
    outbox = Outbox(log=pad.log, journal_path=pad.root / "outbox-acks.jsonl")
    outbox.init()

    external_state: dict[str, dict] = {}
    calls: list[str] = []

    def idempotent_handler(effect_id: str, payload: dict) -> dict:
        calls.append(effect_id)
        external_state.setdefault(effect_id, payload)
        return {"remote_id": effect_id}

    original_append = outbox.journal.append_idempotent

    def crash_before_ack(**_kwargs: object):
        raise OSError("simulated crash after external delivery")

    monkeypatch.setattr(outbox.journal, "append_idempotent", crash_before_ack)
    first = outbox.deliver_pending(
        handlers={"notify": RegisteredHandler("notify-handler/v1", idempotent_handler)},
        delivered_at=lambda: "2026-07-24T00:01:00Z",
    )
    assert not first.ok
    assert first.attempts[0].status == "failed"
    assert outbox.pending().effects[0].effect_id == committed.effect_ids[0]

    monkeypatch.setattr(outbox.journal, "append_idempotent", original_append)
    second = outbox.deliver_pending(
        handlers={"notify": RegisteredHandler("notify-handler/v1", idempotent_handler)},
        delivered_at=lambda: "2026-07-24T00:02:00Z",
    )
    assert second.ok
    assert calls == [committed.effect_ids[0], committed.effect_ids[0]]
    assert len(external_state) == 1
    assert outbox.pending().effects == ()


def test_missing_handler_keeps_effect_pending(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    pad.commit_values(
        outbox=(("unknown", {"value": 1}),),
        created_at="2026-07-24T00:00:00Z",
    )
    outbox = Outbox(log=pad.log, journal_path=pad.root / "outbox-acks.jsonl")
    outbox.init()
    result = outbox.deliver_pending(handlers={}, delivered_at=lambda: "2026-07-24T00:01:00Z")
    assert result.attempts[0].status == "missing_handler"
    assert len(outbox.pending().effects) == 1


def test_ack_journal_corruption_is_detected(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    pad.commit_values(
        outbox=(("notify", {"value": 1}),),
        created_at="2026-07-24T00:00:00Z",
    )
    outbox = Outbox(log=pad.log, journal_path=pad.root / "outbox-acks.jsonl")
    outbox.init()
    outbox.deliver_pending(
        handlers={
            "notify": RegisteredHandler(
                "notify-handler/v1", lambda effect_id, payload: {"id": effect_id}
            )
        },
        delivered_at=lambda: "2026-07-24T00:01:00Z",
    )

    rows = [json.loads(line) for line in outbox.journal.path.read_text(encoding="utf-8").splitlines()]
    rows[0]["handler_id"] = "tampered"
    outbox.journal.path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="ACK_HASH_MISMATCH"):
        outbox.verify()
