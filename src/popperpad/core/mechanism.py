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


@dataclass(frozen=True, slots=True)
class ResourceBudget(DeeplyImmutable):
    budget_id: str
    funded: Amount
    compute: Amount
    storage: Amount
    api: Amount
    verifier: Amount
    retrieval: Amount


@dataclass(frozen=True, slots=True)
class EarnPath(DeeplyImmutable):
    name: str
    earned_credits: Amount
    minimum_agent_run_cost: Amount


@dataclass(frozen=True, slots=True)
class CertificateCase(DeeplyImmutable):
    name: str
    payment_offered: Amount
    verifier_accepted: bool
    certificate_available: bool
    challenge_failed: bool


@dataclass(frozen=True, slots=True)
class TruthBoundaryInputs(DeeplyImmutable):
    stake_changed: bool = False
    verifier_result_changed: bool = False
    local_status_inputs_changed: bool = False
    status_changed: bool = False


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
