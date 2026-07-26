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

from ..core.adapter_protocol import (
    AdapterBinding,
    AdapterDecisionKind,
    AdapterOperation,
    AdapterRequest,
    DataAdapterProfile,
    ExecutionContext,
)
from ..core.codec import canonical_hash
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
from .market_adapter import apply_data_adapter, abstract_state_hash, parse_market_profile


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
    max_states: int = 10000,
) -> EnumerationResult:
    """Deterministic BFS over all reachable states × commands × time classes."""

    market_profile = parse_market_profile(profile.semantic_profile)

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
        if len(visited) >= max_states:
            budget_exhausted = True
            break
        state = queue.popleft()
        state_hash = abstract_state_hash(state)

        for cmd in command_variants:
            for tc in time_classes:
                now = _time_for_class(market_profile.time_representatives, tc)
                request = AdapterRequest(
                    schema="popperpad/data-adapter-request/v1",
                    protocol_version="v1",
                    request_id=f"enum-{state_hash[:8]}-{cmd.kind.value}-{tc.value}",
                    case_id="enumeration",
                    binding_hash=binding.hash(),
                    operation=AdapterOperation.STEP,
                    state=state.as_json(),
                    command=cmd.as_json(),
                    execution_context=ExecutionContext(
                        time_class=tc.value,
                        now_epoch_s=now,
                    ),
                    expected_pre_state_hash=state_hash,
                )
                response = apply_data_adapter(profile, binding, request)

                # Build complete corpus entry binding all transition data
                entry = freeze_json({
                    "pre_state": state.as_json(),
                    "command": cmd.as_json(),
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

                if response.decision_kind is AdapterDecisionKind.ACCEPT:
                    accept_count += 1
                    enabled_transitions += 1
                    post_hash = response.post_state_hash
                    if post_hash and post_hash not in visited:
                        visited.add(post_hash)
                        post_state = SingleSlotAbstractState.from_json(response.post_state)
                        queue.append(post_state)
                elif response.decision_kind is AdapterDecisionKind.COMMITTED_FAILURE:
                    committed_failure_count += 1
                    enabled_transitions += 1
                    post_hash = response.post_state_hash
                    if post_hash and post_hash not in visited:
                        visited.add(post_hash)
                        post_state = SingleSlotAbstractState.from_json(response.post_state)
                        queue.append(post_state)
                elif response.decision_kind is AdapterDecisionKind.REJECT:
                    reject_count += 1
                    reason = response.reason_code or "unknown"
                    reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                elif response.decision_kind is AdapterDecisionKind.INVALID_INPUT:
                    raise RuntimeError(
                        "enumeration produced INVALID_INPUT for an admitted case: "
                        f"{response.reason_code}: {response.reason_details}"
                    )

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
