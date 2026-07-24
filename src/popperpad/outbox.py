from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .canonical import canonical_json_bytes
from .core.outbox import (
    CommittedEffect,
    DeliveryAcknowledgement,
    DeliveryAttempt,
    OutboxSnapshot,
    PendingOutbox,
    pending_outbox,
    plan_acknowledgement,
    verify_ack_chain,
)
from .core.result import Reject
from .core.values import FrozenDict, JsonValue, freeze_json, thaw_json
from .refs import ValidationError, is_ref, require


class DeliveryHandler(Protocol):
    """External effect handler.

    ``effect_id`` is the mandatory idempotency key. A handler may be invoked
    again after an ambiguous crash and must return the same external result or
    a receipt describing its prior successful delivery.
    """

    def __call__(self, effect_id: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RegisteredHandler:
    handler_id: str
    deliver: DeliveryHandler


@dataclass(frozen=True, slots=True)
class DeliveryRun:
    attempts: tuple[DeliveryAttempt, ...]

    @property
    def ok(self) -> bool:
        return all(attempt.status in {"delivered", "already_delivered"} for attempt in self.attempts)


def _frozen_mapping(value: Mapping[str, Any]) -> FrozenDict[JsonValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenDict):
        raise ValidationError("expected object-shaped JSON value")
    return frozen


def _parse_ack(raw: Mapping[str, Any]) -> DeliveryAcknowledgement:
    receipt = raw.get("delivery_receipt", {})
    require(isinstance(receipt, Mapping), "outbox acknowledgement receipt must be an object")
    return DeliveryAcknowledgement(
        effect_id=str(raw.get("effect_id", "")),
        commit_record_hash=str(raw.get("commit_record_hash", "")),
        handler_id=str(raw.get("handler_id", "")),
        delivered_at=str(raw.get("delivered_at", "")),
        delivery_receipt=_frozen_mapping(receipt),
        previous_ack_hash=str(raw.get("previous_ack_hash", "")),
        ack_hash=str(raw.get("ack_hash", "")),
    )


def _atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        try:
            directory_descriptor = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except (AttributeError, OSError):
            pass
    finally:
        try:
            if temporary_path.exists():
                temporary_path.unlink()
        except OSError:
            pass


class DeliveryJournal:
    """Crash-safe acknowledgement journal for at-least-once outbox delivery."""

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.lock_path.touch(mode=0o600, exist_ok=True)

    @contextmanager
    def _lock(self):
        try:
            import fcntl
        except Exception:
            fcntl = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read_unlocked(self) -> tuple[DeliveryAcknowledgement, ...]:
        if not self.path.exists():
            return ()
        acknowledgements: list[DeliveryAcknowledgement] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValidationError(
                        f"outbox acknowledgement corruption at line {line_number}: {exc}"
                    ) from exc
                require(isinstance(raw, Mapping), "outbox acknowledgement must be an object")
                acknowledgements.append(_parse_ack(raw))
        verified = verify_ack_chain(tuple(acknowledgements))
        if isinstance(verified, Reject):
            raise ValidationError(f"{verified.code}: {thaw_json(verified.details)}")
        return verified

    def acknowledgements(self) -> tuple[DeliveryAcknowledgement, ...]:
        return self._read_unlocked()

    def head(self) -> str:
        acknowledgements = self._read_unlocked()
        return acknowledgements[-1].ack_hash if acknowledgements else ""

    def append_idempotent(
        self,
        *,
        effect: CommittedEffect,
        handler_id: str,
        delivered_at: str,
        delivery_receipt: Mapping[str, Any],
    ) -> DeliveryAcknowledgement:
        """Append one acknowledgement, or return the existing one for the effect."""

        with self._lock():
            acknowledgements = self._read_unlocked()
            for acknowledgement in acknowledgements:
                if acknowledgement.effect_id != effect.effect_id:
                    continue
                require(
                    acknowledgement.commit_record_hash == effect.commit_record_hash,
                    "existing acknowledgement is bound to another commit",
                )
                return acknowledgement

            previous = acknowledgements[-1].ack_hash if acknowledgements else ""
            planned = plan_acknowledgement(
                effect=effect,
                handler_id=handler_id,
                delivered_at=delivered_at,
                delivery_receipt=_frozen_mapping(delivery_receipt),
                previous_ack_hash=previous,
            )
            if isinstance(planned, Reject):
                raise ValidationError(f"{planned.code}: {thaw_json(planned.details)}")
            existing = self.path.read_bytes() if self.path.exists() else b""
            require(not existing or existing.endswith(b"\n"), "acknowledgement journal is truncated")
            _atomic_replace(self.path, existing + canonical_json_bytes(planned.as_json()))
            return planned

    def verify(self) -> None:
        self._read_unlocked()


class Outbox:
    """Imperative shell for durable, replay-safe delivery of committed effects."""

    def __init__(self, *, log: Any, journal_path: Path):
        self.log = log
        self.journal = DeliveryJournal(journal_path)

    def init(self) -> None:
        self.journal.init()

    def committed_effects(self) -> tuple[CommittedEffect, ...]:
        effects: list[CommittedEffect] = []
        for record in self.log.iter_raw_records():
            if record.get("schema") != "popperpad/log_record/v2" or record.get("op") != "commit_bundle":
                continue
            commit_record_hash = str(record.get("record_hash", ""))
            require(is_ref(commit_record_hash), "commit record has invalid record_hash")
            raw_effects = record.get("outbox", ()) or ()
            require(
                isinstance(raw_effects, (list, tuple)) and not isinstance(raw_effects, (str, bytes)),
                "commit outbox must be an array",
            )
            for raw in raw_effects:
                require(isinstance(raw, Mapping), "committed outbox effect must be an object")
                payload = raw.get("payload", {})
                require(isinstance(payload, Mapping), "committed outbox payload must be an object")
                effects.append(
                    CommittedEffect(
                        effect_id=str(raw.get("effect_id", "")),
                        commit_record_hash=commit_record_hash,
                        kind=str(raw.get("kind", "")),
                        payload=_frozen_mapping(payload),
                    )
                )
        return tuple(effects)

    def snapshot(self) -> OutboxSnapshot:
        return OutboxSnapshot(
            effects=self.committed_effects(),
            acknowledgements=self.journal.acknowledgements(),
        )

    def pending(self) -> PendingOutbox:
        planned = pending_outbox(self.snapshot())
        if isinstance(planned, Reject):
            raise ValidationError(f"{planned.code}: {thaw_json(planned.details)}")
        return planned

    def deliver_pending(
        self,
        *,
        handlers: Mapping[str, RegisteredHandler],
        delivered_at: Callable[[], str],
    ) -> DeliveryRun:
        """Attempt each pending effect once using its stable idempotency key."""

        attempts: list[DeliveryAttempt] = []
        for effect in self.pending().effects:
            registration = handlers.get(effect.kind)
            if registration is None:
                attempts.append(
                    DeliveryAttempt(
                        effect_id=effect.effect_id,
                        status="missing_handler",
                        error=f"no handler registered for {effect.kind}",
                    )
                )
                continue
            try:
                receipt = registration.deliver(effect.effect_id, thaw_json(effect.payload))
                require(isinstance(receipt, Mapping), "delivery handler must return an object receipt")
                acknowledgement = self.journal.append_idempotent(
                    effect=effect,
                    handler_id=registration.handler_id,
                    delivered_at=delivered_at(),
                    delivery_receipt=receipt,
                )
                attempts.append(
                    DeliveryAttempt(
                        effect_id=effect.effect_id,
                        status="delivered",
                        acknowledgement_hash=acknowledgement.ack_hash,
                    )
                )
            except Exception as exc:
                attempts.append(
                    DeliveryAttempt(
                        effect_id=effect.effect_id,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return DeliveryRun(attempts=tuple(attempts))

    def verify(self) -> None:
        planned = pending_outbox(self.snapshot())
        if isinstance(planned, Reject):
            raise ValidationError(f"{planned.code}: {thaw_json(planned.details)}")
