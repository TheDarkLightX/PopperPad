from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TreasuryEpoch:
    name: str
    starting_balance: float
    inflows: float
    committed_outflows: float
    reserve_requirement: float


@dataclass(frozen=True)
class ResourceBudget:
    budget_id: str
    funded: float
    compute: float
    storage: float
    api: float
    verifier: float
    retrieval: float


@dataclass(frozen=True)
class EarnPath:
    name: str
    earned_credits: float
    minimum_agent_run_cost: float


@dataclass(frozen=True)
class CertificateCase:
    name: str
    payment_offered: float
    verifier_accepted: bool
    certificate_available: bool
    challenge_failed: bool


@dataclass(frozen=True)
class TruthBoundaryInputs:
    stake_changed: bool = False
    verifier_result_changed: bool = False
    local_status_inputs_changed: bool = False
    status_changed: bool = False


def treasury_solvent(epoch: TreasuryEpoch) -> bool:
    return epoch.starting_balance + epoch.inflows >= epoch.committed_outflows + epoch.reserve_requirement


def resource_budget_covered(budget: ResourceBudget) -> bool:
    total_cost = budget.compute + budget.storage + budget.api + budget.verifier + budget.retrieval
    return budget.funded >= total_cost


def earn_margin(path: EarnPath) -> float:
    return path.earned_credits - path.minimum_agent_run_cost


def certificate_payable(case: CertificateCase) -> bool:
    if case.payment_offered <= 0:
        return False
    if not case.verifier_accepted:
        return False
    if not case.certificate_available:
        return False
    if case.challenge_failed:
        return False
    return True


def truth_boundary_holds(inputs: TruthBoundaryInputs) -> bool:
    if not inputs.status_changed:
        return True
    if inputs.verifier_result_changed:
        return True
    if inputs.local_status_inputs_changed:
        return True
    return False
