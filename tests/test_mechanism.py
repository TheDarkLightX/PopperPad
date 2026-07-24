from __future__ import annotations

from popperpad.mechanism import (
    Amount,
    CertificateCase,
    EarnPath,
    ResourceBudget,
    TreasuryEpoch,
    TruthBoundaryInputs,
    certificate_payable,
    earn_margin,
    resource_budget_covered,
    resource_cost,
    treasury_margin,
    treasury_solvent,
    truth_boundary_holds,
)


def A(atoms: int) -> Amount:
    return Amount(atoms)


def test_treasury_solvent_when_margin_nonnegative() -> None:
    epoch = TreasuryEpoch("e1", starting_balance=A(1_000), inflows=A(380), committed_outflows=A(910), reserve_requirement=A(250))
    assert treasury_margin(epoch) == 220
    assert treasury_solvent(epoch) is True


def test_treasury_insolvent_when_margin_negative() -> None:
    epoch = TreasuryEpoch("e1", starting_balance=A(100), inflows=A(0), committed_outflows=A(400), reserve_requirement=A(50))
    assert treasury_margin(epoch) == -350
    assert treasury_solvent(epoch) is False


def test_legacy_numeric_mechanism_api_remains_evaluable() -> None:
    epoch = TreasuryEpoch(
        "legacy",
        starting_balance=1_000.0,
        inflows=380.0,
        committed_outflows=910.0,
        reserve_requirement=250.0,
    )
    assert treasury_margin(epoch) == 220.0
    assert treasury_solvent(epoch) is True

    budget = ResourceBudget(
        "legacy-budget",
        funded=600.0,
        compute=120.0,
        storage=25.0,
        api=300.0,
        verifier=80.0,
        retrieval=30.0,
    )
    assert resource_cost(budget) == 555.0
    assert resource_budget_covered(budget) is True


def test_resource_budget_covered_with_exact_atoms() -> None:
    budget = ResourceBudget("b1", funded=A(600), compute=A(120), storage=A(25), api=A(300), verifier=A(80), retrieval=A(30))
    assert resource_cost(budget) == A(555)
    assert resource_budget_covered(budget) is True
    under = ResourceBudget("b2", funded=A(100), compute=A(120), storage=A(25), api=A(300), verifier=A(80), retrieval=A(30))
    assert resource_budget_covered(under) is False


def test_earn_margin_allows_access() -> None:
    assert earn_margin(EarnPath("p1", earned_credits=A(12), minimum_agent_run_cost=A(8))) == 4
    assert earn_margin(EarnPath("p2", earned_credits=A(3), minimum_agent_run_cost=A(8))) == -5


def test_certificate_payable_requires_all_four_guards() -> None:
    base = CertificateCase("c", payment_offered=A(100), verifier_accepted=True, certificate_available=True, challenge_failed=False)
    assert certificate_payable(base) is True
    assert certificate_payable(CertificateCase("c", A(0), True, True, False)) is False
    assert certificate_payable(CertificateCase("c", A(100), False, True, False)) is False
    assert certificate_payable(CertificateCase("c", A(100), True, False, False)) is False
    assert certificate_payable(CertificateCase("c", A(100), True, True, True)) is False


def test_amount_rejects_inexact_or_negative_state() -> None:
    import pytest

    with pytest.raises(TypeError):
        Amount(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Amount(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Amount(-1)


def test_truth_boundary_stake_alone_never_changes_status() -> None:
    inputs = TruthBoundaryInputs(stake_changed=True)
    assert truth_boundary_holds(inputs) is True


def test_truth_boundary_violated_when_stake_alone_changes_status() -> None:
    inputs = TruthBoundaryInputs(stake_changed=True, status_changed=True)
    assert truth_boundary_holds(inputs) is False


def test_truth_boundary_allows_status_change_when_verifier_changes() -> None:
    inputs = TruthBoundaryInputs(verifier_result_changed=True, status_changed=True)
    assert truth_boundary_holds(inputs) is True
