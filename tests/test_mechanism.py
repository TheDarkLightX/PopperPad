from __future__ import annotations

import pytest

from popperpad.mechanism import (
    CertificateCase,
    EarnPath,
    ResourceBudget,
    TreasuryEpoch,
    TruthBoundaryInputs,
    certificate_payable,
    earn_margin,
    resource_budget_covered,
    treasury_solvent,
    truth_boundary_holds,
)


def test_treasury_solvent_when_margin_nonnegative() -> None:
    ep = TreasuryEpoch("e1", starting_balance=1000.0, inflows=380.0, committed_outflows=910.0, reserve_requirement=250.0)
    assert treasury_solvent(ep) is True


def test_treasury_insolvent_when_margin_negative() -> None:
    ep = TreasuryEpoch("e1", starting_balance=100.0, inflows=0.0, committed_outflows=400.0, reserve_requirement=50.0)
    assert treasury_solvent(ep) is False


def test_resource_budget_covered() -> None:
    b = ResourceBudget("b1", funded=60.0, compute=12.0, storage=2.5, api=30.0, verifier=8.0, retrieval=3.0)
    assert resource_budget_covered(b) is True
    under = ResourceBudget("b2", funded=10.0, compute=12.0, storage=2.5, api=30.0, verifier=8.0, retrieval=3.0)
    assert resource_budget_covered(under) is False


def test_earn_margin_allows_access() -> None:
    p = EarnPath("p1", earned_credits=12.0, minimum_agent_run_cost=8.0)
    assert earn_margin(p) >= 0
    blocked = EarnPath("p2", earned_credits=3.0, minimum_agent_run_cost=8.0)
    assert earn_margin(blocked) < 0


def test_certificate_payable_requires_all_four_guards() -> None:
    base = CertificateCase("c", payment_offered=100.0, verifier_accepted=True, certificate_available=True, challenge_failed=False)
    assert certificate_payable(base) is True
    assert certificate_payable(CertificateCase("c", payment_offered=0.0, verifier_accepted=True, certificate_available=True, challenge_failed=False)) is False
    assert certificate_payable(CertificateCase("c", payment_offered=100.0, verifier_accepted=False, certificate_available=True, challenge_failed=False)) is False
    assert certificate_payable(CertificateCase("c", payment_offered=100.0, verifier_accepted=True, certificate_available=False, challenge_failed=False)) is False
    assert certificate_payable(CertificateCase("c", payment_offered=100.0, verifier_accepted=True, certificate_available=True, challenge_failed=True)) is False


def test_truth_boundary_stake_alone_never_changes_status() -> None:
    inputs = TruthBoundaryInputs(
        stake_changed=True,
        verifier_result_changed=False,
        local_status_inputs_changed=False,
    )
    assert truth_boundary_holds(inputs) is True  # boundary holds: status unchanged


def test_truth_boundary_violated_when_stake_alone_changes_status() -> None:
    inputs = TruthBoundaryInputs(
        stake_changed=True,
        verifier_result_changed=False,
        local_status_inputs_changed=False,
        status_changed=True,  # this would be a violation
    )
    assert truth_boundary_holds(inputs) is False


def test_truth_boundary_allows_status_change_when_verifier_changes() -> None:
    inputs = TruthBoundaryInputs(
        stake_changed=False,
        verifier_result_changed=True,
        local_status_inputs_changed=False,
        status_changed=True,
    )
    assert truth_boundary_holds(inputs) is True
