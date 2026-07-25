"""Finite single-slot falsification-market abstract state.

The abstract state is a genuinely finite closed value — not a mirror of
arbitrary concrete ``BountyState`` JSON. All concrete identities (submission
IDs, challenge IDs, command IDs, refs, timestamps) are supplied by the
profile, not by the state. The state only tracks the finite phase, status,
amount, and time-class dimensions that ESSO can enumerate.

State dimensions (all finite):
  - phase: 6 values (draft, open, payable, settled, expired, canceled)
  - escrow_atoms: bounded by profile (0 or reward_atoms)
  - submission_status: 4 values (none, pending, verified, rejected)
  - submission_time_class: 6 values (none + 5 time classes)
  - bond_atoms: bounded by profile (0 or bond_atoms)
  - challenge_status: 4 values (none, open, upheld, rejected)
  - challenge_opened_time_class: 6 values (none + 5 time classes)
  - deposit_atoms: bounded by profile (0 or deposit_atoms)
  - payable: 2 values (false, true)
  - settled: 2 values (false, true)
  - processed_command_mask: bounded bitset over declared command slots

The time-class fields preserve the temporal context in which a submission
or challenge was created. This is semantically necessary because challenge
resolution compares the command time with a deadline computed from the
challenge's actual ``opened_at`` time, and advancement distinguishes an
adjudication window from a timed-out challenge.

The profile supplies fixed concrete identities for concretization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..core.values import ClosedStrEnum, DeeplyImmutable, FrozenDict, JsonValue, freeze_json


class AbstractPhase(ClosedStrEnum):
    __slots__ = ()

    DRAFT: ClassVar[AbstractPhase]
    OPEN: ClassVar[AbstractPhase]
    PAYABLE: ClassVar[AbstractPhase]
    SETTLED: ClassVar[AbstractPhase]
    EXPIRED: ClassVar[AbstractPhase]
    CANCELED: ClassVar[AbstractPhase]
    _symbols = (
        ("DRAFT", "draft"),
        ("OPEN", "open"),
        ("PAYABLE", "payable"),
        ("SETTLED", "settled"),
        ("EXPIRED", "expired"),
        ("CANCELED", "canceled"),
    )


class AbstractSubmissionStatus(ClosedStrEnum):
    __slots__ = ()

    NONE: ClassVar[AbstractSubmissionStatus]
    PENDING: ClassVar[AbstractSubmissionStatus]
    VERIFIED: ClassVar[AbstractSubmissionStatus]
    REJECTED: ClassVar[AbstractSubmissionStatus]
    _symbols = (
        ("NONE", "none"),
        ("PENDING", "pending"),
        ("VERIFIED", "verified"),
        ("REJECTED", "rejected"),
    )


class AbstractChallengeStatus(ClosedStrEnum):
    __slots__ = ()

    NONE: ClassVar[AbstractChallengeStatus]
    OPEN: ClassVar[AbstractChallengeStatus]
    UPHELD: ClassVar[AbstractChallengeStatus]
    REJECTED: ClassVar[AbstractChallengeStatus]
    _symbols = (
        ("NONE", "none"),
        ("OPEN", "open"),
        ("UPHELD", "upheld"),
        ("REJECTED", "rejected"),
    )


class AbstractCommandKind(ClosedStrEnum):
    __slots__ = ()

    OPEN_BOUNTY: ClassVar[AbstractCommandKind]
    SUBMIT_CANDIDATE: ClassVar[AbstractCommandKind]
    VERIFY_SUBMISSION: ClassVar[AbstractCommandKind]
    OPEN_CHALLENGE: ClassVar[AbstractCommandKind]
    RESOLVE_CHALLENGE: ClassVar[AbstractCommandKind]
    ADVANCE_BOUNTY: ClassVar[AbstractCommandKind]
    SETTLE_BOUNTY: ClassVar[AbstractCommandKind]
    CANCEL_BOUNTY: ClassVar[AbstractCommandKind]
    _symbols = (
        ("OPEN_BOUNTY", "open_bounty"),
        ("SUBMIT_CANDIDATE", "submit_candidate"),
        ("VERIFY_SUBMISSION", "verify_submission"),
        ("OPEN_CHALLENGE", "open_challenge"),
        ("RESOLVE_CHALLENGE", "resolve_challenge"),
        ("ADVANCE_BOUNTY", "advance_bounty"),
        ("SETTLE_BOUNTY", "settle_bounty"),
        ("CANCEL_BOUNTY", "cancel_bounty"),
    )


class TimeClass(ClosedStrEnum):
    __slots__ = ()

    PRE_DEADLINE: ClassVar[TimeClass]
    AT_DEADLINE: ClassVar[TimeClass]
    CHALLENGE_WINDOW: ClassVar[TimeClass]
    POST_CHALLENGE_WINDOW: ClassVar[TimeClass]
    POST_RESOLUTION_DEADLINE: ClassVar[TimeClass]
    _symbols = (
        ("PRE_DEADLINE", "pre_deadline"),
        ("AT_DEADLINE", "at_deadline"),
        ("CHALLENGE_WINDOW", "challenge_window"),
        ("POST_CHALLENGE_WINDOW", "post_challenge_window"),
        ("POST_RESOLUTION_DEADLINE", "post_resolution_deadline"),
    )


class TimeClassOrNone(ClosedStrEnum):
    """Time class or 'none' for when no submission/challenge exists."""

    __slots__ = ()

    NONE: ClassVar[TimeClassOrNone]
    PRE_DEADLINE: ClassVar[TimeClassOrNone]
    AT_DEADLINE: ClassVar[TimeClassOrNone]
    CHALLENGE_WINDOW: ClassVar[TimeClassOrNone]
    POST_CHALLENGE_WINDOW: ClassVar[TimeClassOrNone]
    POST_RESOLUTION_DEADLINE: ClassVar[TimeClassOrNone]
    _symbols = (
        ("NONE", "none"),
        ("PRE_DEADLINE", "pre_deadline"),
        ("AT_DEADLINE", "at_deadline"),
        ("CHALLENGE_WINDOW", "challenge_window"),
        ("POST_CHALLENGE_WINDOW", "post_challenge_window"),
        ("POST_RESOLUTION_DEADLINE", "post_resolution_deadline"),
    )


# Command slots — each transition uses a fixed command ID from the profile.
COMMAND_SLOTS: tuple[AbstractCommandKind, ...] = tuple(AbstractCommandKind)


@dataclass(frozen=True, slots=True)
class SingleSlotAbstractState(DeeplyImmutable):
    """Genuinely finite single-slot market state.

    No arbitrary IDs, refs, timestamps, or processed-command strings.
    The processed_command_mask is a bounded bitset over the 8 declared
    command slots, giving 2^8 = 256 possible masks.

    submission_time_class and challenge_opened_time_class preserve the
    temporal context needed for time-dependent transition semantics.
    """

    phase: AbstractPhase
    escrow_atoms: int
    submission_status: AbstractSubmissionStatus
    submission_time_class: TimeClassOrNone
    bond_atoms: int
    challenge_status: AbstractChallengeStatus
    challenge_opened_time_class: TimeClassOrNone
    deposit_atoms: int
    payable: bool
    settled: bool
    processed_command_mask: int

    def __post_init__(self) -> None:
        if type(self.phase) is not AbstractPhase:
            raise TypeError("phase must be AbstractPhase")
        if type(self.escrow_atoms) is not int or isinstance(self.escrow_atoms, bool):
            raise TypeError("escrow_atoms must be an integer")
        if self.escrow_atoms < 0:
            raise ValueError("escrow_atoms must be non-negative")
        if type(self.submission_status) is not AbstractSubmissionStatus:
            raise TypeError("submission_status must be AbstractSubmissionStatus")
        if type(self.submission_time_class) is not TimeClassOrNone:
            raise TypeError("submission_time_class must be TimeClassOrNone")
        if type(self.bond_atoms) is not int or isinstance(self.bond_atoms, bool):
            raise TypeError("bond_atoms must be an integer")
        if self.bond_atoms < 0:
            raise ValueError("bond_atoms must be non-negative")
        if type(self.challenge_status) is not AbstractChallengeStatus:
            raise TypeError("challenge_status must be AbstractChallengeStatus")
        if type(self.challenge_opened_time_class) is not TimeClassOrNone:
            raise TypeError("challenge_opened_time_class must be TimeClassOrNone")
        if type(self.deposit_atoms) is not int or isinstance(self.deposit_atoms, bool):
            raise TypeError("deposit_atoms must be an integer")
        if self.deposit_atoms < 0:
            raise ValueError("deposit_atoms must be non-negative")
        if type(self.payable) is not bool:
            raise TypeError("payable must be a bool")
        if type(self.settled) is not bool:
            raise TypeError("settled must be a bool")
        if type(self.processed_command_mask) is not int or isinstance(self.processed_command_mask, bool):
            raise TypeError("processed_command_mask must be an integer")
        if self.processed_command_mask < 0 or self.processed_command_mask >= (1 << len(COMMAND_SLOTS)):
            raise ValueError("processed_command_mask out of range")
        _check_temporal_consistency(self)
        DeeplyImmutable.__post_init__(self)

    def command_processed(self, slot: AbstractCommandKind) -> bool:
        return bool(self.processed_command_mask & (1 << COMMAND_SLOTS.index(slot)))

    def with_command_processed(self, slot: AbstractCommandKind) -> "SingleSlotAbstractState":
        bit = 1 << COMMAND_SLOTS.index(slot)
        return SingleSlotAbstractState(
            phase=self.phase,
            escrow_atoms=self.escrow_atoms,
            submission_status=self.submission_status,
            submission_time_class=self.submission_time_class,
            bond_atoms=self.bond_atoms,
            challenge_status=self.challenge_status,
            challenge_opened_time_class=self.challenge_opened_time_class,
            deposit_atoms=self.deposit_atoms,
            payable=self.payable,
            settled=self.settled,
            processed_command_mask=self.processed_command_mask | bit,
        )

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "phase": self.phase.value,
                "escrow_atoms": self.escrow_atoms,
                "submission_status": self.submission_status.value,
                "submission_time_class": self.submission_time_class.value,
                "bond_atoms": self.bond_atoms,
                "challenge_status": self.challenge_status.value,
                "challenge_opened_time_class": self.challenge_opened_time_class.value,
                "deposit_atoms": self.deposit_atoms,
                "payable": self.payable,
                "settled": self.settled,
                "processed_command_mask": self.processed_command_mask,
            }
        )
        assert isinstance(value, FrozenDict)
        return value

    @classmethod
    def from_json(cls, data: FrozenDict[JsonValue]) -> "SingleSlotAbstractState":
        return cls(
            phase=AbstractPhase(data["phase"]),
            escrow_atoms=data["escrow_atoms"],
            submission_status=AbstractSubmissionStatus(data["submission_status"]),
            submission_time_class=TimeClassOrNone(data["submission_time_class"]),
            bond_atoms=data["bond_atoms"],
            challenge_status=AbstractChallengeStatus(data["challenge_status"]),
            challenge_opened_time_class=TimeClassOrNone(data["challenge_opened_time_class"]),
            deposit_atoms=data["deposit_atoms"],
            payable=data["payable"],
            settled=data["settled"],
            processed_command_mask=data["processed_command_mask"],
        )


def _check_temporal_consistency(state: SingleSlotAbstractState) -> None:
    """Ensure time-class fields are consistent with existence fields."""

    if state.submission_status is AbstractSubmissionStatus.NONE:
        if state.submission_time_class is not TimeClassOrNone.NONE:
            raise ValueError("submission_time_class must be none when submission_status is none")
    else:
        if state.submission_time_class is TimeClassOrNone.NONE:
            raise ValueError("submission_time_class must not be none when submission exists")
    if state.challenge_status is AbstractChallengeStatus.NONE:
        if state.challenge_opened_time_class is not TimeClassOrNone.NONE:
            raise ValueError("challenge_opened_time_class must be none when challenge_status is none")
    else:
        if state.challenge_opened_time_class is TimeClassOrNone.NONE:
            raise ValueError("challenge_opened_time_class must not be none when challenge exists")


def validate_state_bounds(
    state: SingleSlotAbstractState,
    reward_atoms: int,
    bond_atoms: int,
    deposit_atoms: int,
) -> None:
    """Validate that abstract state amounts are within profile-declared bounds."""

    if state.escrow_atoms > reward_atoms:
        raise ValueError(f"escrow_atoms {state.escrow_atoms} exceeds reward_atoms {reward_atoms}")
    if state.bond_atoms > bond_atoms:
        raise ValueError(f"bond_atoms {state.bond_atoms} exceeds profile bond_atoms {bond_atoms}")
    if state.deposit_atoms > deposit_atoms:
        raise ValueError(f"deposit_atoms {state.deposit_atoms} exceeds profile deposit_atoms {deposit_atoms}")


def initial_abstract_state() -> SingleSlotAbstractState:
    """The initial draft state with no activity."""

    return SingleSlotAbstractState(
        phase=AbstractPhase.DRAFT,
        escrow_atoms=0,
        submission_status=AbstractSubmissionStatus.NONE,
        submission_time_class=TimeClassOrNone.NONE,
        bond_atoms=0,
        challenge_status=AbstractChallengeStatus.NONE,
        challenge_opened_time_class=TimeClassOrNone.NONE,
        deposit_atoms=0,
        payable=False,
        settled=False,
        processed_command_mask=0,
    )


@dataclass(frozen=True, slots=True)
class SingleSlotAbstractCommand(DeeplyImmutable):
    """An abstract command for the single-slot profile.

    The command kind selects the transition. For verify_submission, the
    accepted boolean selects the sub-variant. For resolve_challenge, the
    upheld boolean selects the sub-variant. All other kinds must not carry
    accepted or upheld — variant-inapplicable fields are rejected.

    No arbitrary IDs or refs — those come from the profile.
    """

    kind: AbstractCommandKind
    accepted: bool | None = None
    upheld: bool | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not AbstractCommandKind:
            raise TypeError("kind must be AbstractCommandKind")
        if self.accepted is not None and type(self.accepted) is not bool:
            raise TypeError("accepted must be null or bool")
        if self.upheld is not None and type(self.upheld) is not bool:
            raise TypeError("upheld must be null or bool")
        needs_accepted = self.kind is AbstractCommandKind.VERIFY_SUBMISSION
        needs_upheld = self.kind is AbstractCommandKind.RESOLVE_CHALLENGE
        if needs_accepted and self.accepted is None:
            raise ValueError("verify_submission requires accepted")
        if not needs_accepted and self.accepted is not None:
            raise ValueError(f"accepted is not applicable to {self.kind.value}")
        if needs_upheld and self.upheld is None:
            raise ValueError("resolve_challenge requires upheld")
        if not needs_upheld and self.upheld is not None:
            raise ValueError(f"upheld is not applicable to {self.kind.value}")
        DeeplyImmutable.__post_init__(self)

    def as_json(self) -> FrozenDict[JsonValue]:
        fields: dict[str, JsonValue] = {"kind": self.kind.value}
        if self.accepted is not None:
            fields["accepted"] = self.accepted
        if self.upheld is not None:
            fields["upheld"] = self.upheld
        value = freeze_json(fields)
        assert isinstance(value, FrozenDict)
        return value

    @classmethod
    def from_json(cls, data: FrozenDict[JsonValue]) -> "SingleSlotAbstractCommand":
        kind = AbstractCommandKind(data["kind"])
        accepted = data.get("accepted")
        upheld = data.get("upheld")
        return cls(kind=kind, accepted=accepted, upheld=upheld)
