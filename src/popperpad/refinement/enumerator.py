"""Deterministic BFS finite-state enumerator for the single-slot profile.

Enumerates every reachable abstract state × command variant × time class,
applies the adapter, records the complete transition, and adds accepted/
committed-failure successor states until a fixed point is reached.

The corpus hash binds ALL of:
  - accepted/upheld command subvariants
  - complete pre-state
  - complete command
  - time class
  - decision kind
  - reason code
  - complete post-state
  - ordered effects
  - effect-plan hash
  - receipt
  - response commitment

Different transition systems cannot produce the same corpus summary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..core.adapter_protocol import (
    AdapterBinding,
    AdapterDecisionKind,
    AdapterOperation,
    AdapterRequest,
    DataAdapterProfile,
    ExecutionContext,
)
from ..core.codec import canonical_hash
from ..core.market import VerifierReceipt, verifier_statement_signing_bytes
from ..core.verifier import ed25519_verifier_ref
from ..core.values import FrozenDict, JsonValue, freeze_json
from ..core.values import DeeplyImmutable
from .finite_state import (
    AbstractCommandKind,
    COMMAND_SLOTS,
    SingleSlotAbstractCommand,
    SingleSlotAbstractState,
    TimeClass,
    initial_abstract_state,
)
from .market_adapter import (
    abstract_state_hash,
    apply_data_adapter,
    command_json_with_verifier_receipt,
    parse_market_profile,
    verifier_statement_for_abstract_command,
)


CORPUS_DOMAIN = "popperpad-enumeration-corpus/v1"


@dataclass(frozen=True, slots=True)
class EnumerationResult(DeeplyImmutable):
    reachable_states: int
    command_variants: int
    time_classes: int
    total_cases: int
    enabled_transitions: int
    accept_count: int
    reject_count: int
    reject_reasons: FrozenDict[JsonValue]
    committed_failure_count: int
    corpus_hash: str
    search_complete: bool
    budget_exhausted: bool

    def __post_init__(self) -> None:
        if type(self.reject_reasons) is not FrozenDict:
            raise TypeError("EnumerationResult.reject_reasons must be a FrozenDict")
        DeeplyImmutable.__post_init__(self)


def enumerate_all_transitions(
    profile: DataAdapterProfile,
    binding: AdapterBinding,
    *,
    verifier_private_key: bytes,
    max_states: int = 10000,
) -> EnumerationResult:
    """Deterministic BFS over all reachable states × commands × time classes."""

    if type(max_states) is not int or max_states < 1:
        raise ValueError("max_states must be a positive integer")

    market_profile = parse_market_profile(profile.semantic_profile)
    if type(verifier_private_key) is not bytes or len(verifier_private_key) != 32:
        raise ValueError("verifier_private_key must be exactly 32 bytes")
    signer = Ed25519PrivateKey.from_private_bytes(verifier_private_key)
    public_key = signer.public_key().public_bytes_raw()
    if ed25519_verifier_ref(public_key) != market_profile.verifier_ref:
        raise ValueError(
            "verifier_private_key does not match the bounded profile verifier"
        )

    visited: set[str] = set()
    queue: deque[SingleSlotAbstractState] = deque()
    initial = initial_abstract_state()
    queue.append(initial)
    visited.add(abstract_state_hash(initial))

    command_variants: list[SingleSlotAbstractCommand] = []
    for kind in COMMAND_SLOTS:
        if kind is AbstractCommandKind.VERIFY_SUBMISSION:
            command_variants.append(SingleSlotAbstractCommand(kind=kind, accepted=True))
            command_variants.append(SingleSlotAbstractCommand(kind=kind, accepted=False))
        elif kind is AbstractCommandKind.RESOLVE_CHALLENGE:
            command_variants.append(SingleSlotAbstractCommand(kind=kind, upheld=True))
            command_variants.append(SingleSlotAbstractCommand(kind=kind, upheld=False))
        else:
            command_variants.append(SingleSlotAbstractCommand(kind=kind))

    time_classes = list(TimeClass)
    corpus_entries: list[FrozenDict[JsonValue]] = []
    accept_count = 0
    reject_count = 0
    reject_reasons: dict[str, int] = {}
    committed_failure_count = 0
    enabled_transitions = 0
    budget_exhausted = False

    while queue:
        state = queue.popleft()
        state_hash = abstract_state_hash(state)

        for cmd in command_variants:
            for tc in time_classes:
                now = _time_for_class(market_profile.time_representatives, tc)
                command_json = cmd.as_json()
                statement = verifier_statement_for_abstract_command(
                    market_profile, state, cmd, now
                )
                if statement is not None:
                    receipt = VerifierReceipt(
                        statement=statement,
                        public_key=public_key,
                        signature=signer.sign(
                            verifier_statement_signing_bytes(statement)
                        ),
                    )
                    command_json = command_json_with_verifier_receipt(
                        cmd, receipt
                    )
                command_hash = canonical_hash(
                    "popperpad-enumeration-command/v1", command_json
                )
                request = AdapterRequest(
                    schema="popperpad/data-adapter-request/v1",
                    protocol_version="v1",
                    request_id=f"enum-{state_hash}-{command_hash}-{tc.value}",
                    case_id="enumeration",
                    binding_hash=binding.hash(),
                    operation=AdapterOperation.STEP,
                    state=state.as_json(),
                    command=command_json,
                    execution_context=ExecutionContext(
                        time_class=tc.value,
                        now_epoch_s=now,
                    ),
                    expected_pre_state_hash=state_hash,
                )
                response = apply_data_adapter(profile, binding, request)
                if statement is not None and response.reason_code in (
                    "INVALID_EVIDENCE",
                    "MISSING_EVIDENCE",
                ):
                    raise RuntimeError(
                        "generated verifier evidence was not admitted"
                    )

                # Build complete corpus entry binding all transition data
                entry = freeze_json({
                    "pre_state": state.as_json(),
                    "command": command_json,
                    "time_class": tc.value,
                    "decision_kind": response.decision_kind.value,
                    "reason_code": response.reason_code,
                    "post_state": response.post_state,
                    "effects": list(response.effects),
                    "effect_plan_hash": response.effect_plan_hash,
                    "receipt": response.receipt,
                    "response_commitment": response.response_commitment,
                })
                assert isinstance(entry, FrozenDict)
                corpus_entries.append(entry)

                successor_hash: str | None = None
                if response.decision_kind is AdapterDecisionKind.ACCEPT:
                    accept_count += 1
                    enabled_transitions += 1
                    successor_hash = response.post_state_hash
                elif response.decision_kind is AdapterDecisionKind.COMMITTED_FAILURE:
                    committed_failure_count += 1
                    enabled_transitions += 1
                    successor_hash = response.post_state_hash
                elif response.decision_kind is AdapterDecisionKind.REJECT:
                    reject_count += 1
                    reason = response.reason_code or "unknown"
                    reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                elif response.decision_kind is AdapterDecisionKind.INVALID_INPUT:
                    raise RuntimeError(
                        "enumeration produced INVALID_INPUT for an admitted case: "
                        f"{response.reason_code}: {response.reason_details}"
                    )

                if successor_hash and successor_hash not in visited:
                    if len(visited) >= max_states:
                        budget_exhausted = True
                        break
                    visited.add(successor_hash)
                    post_state = SingleSlotAbstractState.from_json(response.post_state)
                    queue.append(post_state)

            if budget_exhausted:
                break

        if budget_exhausted:
            break

    corpus_hash = canonical_hash(CORPUS_DOMAIN, tuple(corpus_entries))

    frozen_reject_reasons = freeze_json(reject_reasons)
    assert isinstance(frozen_reject_reasons, FrozenDict)
    return EnumerationResult(
        reachable_states=len(visited),
        command_variants=len(command_variants),
        time_classes=len(time_classes),
        total_cases=len(corpus_entries),
        enabled_transitions=enabled_transitions,
        accept_count=accept_count,
        reject_count=reject_count,
        reject_reasons=frozen_reject_reasons,
        committed_failure_count=committed_failure_count,
        corpus_hash=corpus_hash,
        search_complete=not budget_exhausted,
        budget_exhausted=budget_exhausted,
    )


def _time_for_class(
    time_representatives: FrozenDict[JsonValue],
    tc: TimeClass,
) -> int:
    """Return the exact epoch committed by the supplied semantic profile."""

    value = time_representatives.get(tc.value)
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid or missing time representative for {tc.value}")
    return value
