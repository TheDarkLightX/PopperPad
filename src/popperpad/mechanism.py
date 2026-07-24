"""Legacy numeric adapter for the exact functional-core mechanism values.

New authority-bearing code should import :mod:`popperpad.core.mechanism` and
use :class:`popperpad.core.values.Amount`. This module preserves the released
numeric API while also accepting all-``Amount`` inputs during migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .core.mechanism import TruthBoundaryInputs, truth_boundary_holds
from .core.values import Amount


Numeric: TypeAlias = int | float
Quantity: TypeAlias = Numeric | Amount


@dataclass(frozen=True, slots=True)
class TreasuryEpoch:
    name: str
    starting_balance: Quantity
    inflows: Quantity
    committed_outflows: Quantity
    reserve_requirement: Quantity


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    budget_id: str
    funded: Quantity
    compute: Quantity
    storage: Quantity
    api: Quantity
    verifier: Quantity
    retrieval: Quantity


@dataclass(frozen=True, slots=True)
class EarnPath:
    name: str
    earned_credits: Quantity
    minimum_agent_run_cost: Quantity


@dataclass(frozen=True, slots=True)
class CertificateCase:
    name: str
    payment_offered: Quantity
    verifier_accepted: bool
    certificate_available: bool
    challenge_failed: bool


def _quantities(*values: Quantity) -> tuple[tuple[Numeric, ...], bool]:
    amount_mode = tuple(isinstance(value, Amount) for value in values)
    if all(amount_mode):
        return tuple(value.atoms for value in values if isinstance(value, Amount)), True
    if any(amount_mode):
        raise TypeError("cannot mix legacy numeric quantities with Amount values")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise TypeError("mechanism quantities must be numeric or Amount values")
    return tuple(value for value in values if isinstance(value, (int, float))), False


def treasury_margin(epoch: TreasuryEpoch) -> Numeric:
    values, _amount_mode = _quantities(
        epoch.starting_balance,
        epoch.inflows,
        epoch.committed_outflows,
        epoch.reserve_requirement,
    )
    starting_balance, inflows, committed_outflows, reserve_requirement = values
    return starting_balance + inflows - committed_outflows - reserve_requirement


def treasury_solvent(epoch: TreasuryEpoch) -> bool:
    return treasury_margin(epoch) >= 0


def resource_cost(budget: ResourceBudget) -> Numeric | Amount:
    values, amount_mode = _quantities(
        budget.compute,
        budget.storage,
        budget.api,
        budget.verifier,
        budget.retrieval,
    )
    total = sum(values)
    return Amount(total) if amount_mode else total


def resource_budget_covered(budget: ResourceBudget) -> bool:
    values, _amount_mode = _quantities(
        budget.funded,
        budget.compute,
        budget.storage,
        budget.api,
        budget.verifier,
        budget.retrieval,
    )
    funded, *costs = values
    return funded >= sum(costs)


def earn_margin(path: EarnPath) -> Numeric:
    values, _amount_mode = _quantities(path.earned_credits, path.minimum_agent_run_cost)
    earned_credits, minimum_agent_run_cost = values
    return earned_credits - minimum_agent_run_cost


def certificate_payable(case: CertificateCase) -> bool:
    values, _amount_mode = _quantities(case.payment_offered)
    return (
        values[0] > 0
        and case.verifier_accepted
        and case.certificate_available
        and not case.challenge_failed
    )


__all__ = [
    "Amount",
    "CertificateCase",
    "EarnPath",
    "ResourceBudget",
    "TreasuryEpoch",
    "TruthBoundaryInputs",
    "certificate_payable",
    "earn_margin",
    "resource_budget_covered",
    "resource_cost",
    "treasury_margin",
    "treasury_solvent",
    "truth_boundary_holds",
]
