from __future__ import annotations

from dataclasses import dataclass

from .values import Amount, DeeplyImmutable


@dataclass(frozen=True, slots=True)
class TreasuryEpoch(DeeplyImmutable):
    name: str
    starting_balance: Amount
    inflows: Amount
    committed_outflows: Amount
    reserve_requirement: Amount

    def __post_init__(self) -> None:
        _require_name("name", self.name)
        _require_amounts(
            starting_balance=self.starting_balance,
            inflows=self.inflows,
            committed_outflows=self.committed_outflows,
            reserve_requirement=self.reserve_requirement,
        )
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class ResourceBudget(DeeplyImmutable):
    budget_id: str
    funded: Amount
    compute: Amount
    storage: Amount
    api: Amount
    verifier: Amount
    retrieval: Amount

    def __post_init__(self) -> None:
        _require_name("budget_id", self.budget_id)
        _require_amounts(
            funded=self.funded,
            compute=self.compute,
            storage=self.storage,
            api=self.api,
            verifier=self.verifier,
            retrieval=self.retrieval,
        )
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class EarnPath(DeeplyImmutable):
    name: str
    earned_credits: Amount
    minimum_agent_run_cost: Amount

    def __post_init__(self) -> None:
        _require_name("name", self.name)
        _require_amounts(
            earned_credits=self.earned_credits,
            minimum_agent_run_cost=self.minimum_agent_run_cost,
        )
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class CertificateCase(DeeplyImmutable):
    name: str
    payment_offered: Amount
    verifier_accepted: bool
    certificate_available: bool
    challenge_failed: bool

    def __post_init__(self) -> None:
        _require_name("name", self.name)
        _require_amounts(payment_offered=self.payment_offered)
        _require_bools(
            verifier_accepted=self.verifier_accepted,
            certificate_available=self.certificate_available,
            challenge_failed=self.challenge_failed,
        )
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class TruthBoundaryInputs(DeeplyImmutable):
    stake_changed: bool = False
    verifier_result_changed: bool = False
    local_status_inputs_changed: bool = False
    status_changed: bool = False

    def __post_init__(self) -> None:
        _require_bools(
            stake_changed=self.stake_changed,
            verifier_result_changed=self.verifier_result_changed,
            local_status_inputs_changed=self.local_status_inputs_changed,
            status_changed=self.status_changed,
        )
        DeeplyImmutable.__post_init__(self)


def _require_name(field_name: str, value: object) -> None:
    if type(value) is not str or not value:
        raise TypeError(f"{field_name} must be a non-empty string")


def _require_amounts(**values: object) -> None:
    for field_name, value in values.items():
        if type(value) is not Amount:
            raise TypeError(f"{field_name} must be an Amount")


def _require_bools(**values: object) -> None:
    for field_name, value in values.items():
        if type(value) is not bool:
            raise TypeError(f"{field_name} must be a bool")


def treasury_margin(epoch: TreasuryEpoch) -> int:
    return (
        epoch.starting_balance.atoms
        + epoch.inflows.atoms
        - epoch.committed_outflows.atoms
        - epoch.reserve_requirement.atoms
    )


def treasury_solvent(epoch: TreasuryEpoch) -> bool:
    return treasury_margin(epoch) >= 0


def resource_cost(budget: ResourceBudget) -> Amount:
    return Amount(
        budget.compute.atoms
        + budget.storage.atoms
        + budget.api.atoms
        + budget.verifier.atoms
        + budget.retrieval.atoms
    )


def resource_budget_covered(budget: ResourceBudget) -> bool:
    return budget.funded.atoms >= resource_cost(budget).atoms


def earn_margin(path: EarnPath) -> int:
    return path.earned_credits.atoms - path.minimum_agent_run_cost.atoms


def certificate_payable(case: CertificateCase) -> bool:
    return (
        case.payment_offered.atoms > 0
        and case.verifier_accepted
        and case.certificate_available
        and not case.challenge_failed
    )


def truth_boundary_holds(inputs: TruthBoundaryInputs) -> bool:
    return (
        not inputs.status_changed
        or inputs.verifier_result_changed
        or inputs.local_status_inputs_changed
    )
