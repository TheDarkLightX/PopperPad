from __future__ import annotations

import pytest

from popperpad.adapters.tau import TauPolicyInputs, TauPolicyOutputs, evaluate_tau_policy


def test_allow_publish_requires_all_guards() -> None:
    base = dict(
        publication_requested=True,
        contains_private_data=False,
        bundle_root_matches=True,
        required_signatures_present=True,
    )
    assert evaluate_tau_policy(TauPolicyInputs(**base)).allow_publish is True
    # Each guard flipping to the unsafe side must deny.
    for key, bad in [
        ("publication_requested", False),
        ("contains_private_data", True),
        ("bundle_root_matches", False),
        ("required_signatures_present", False),
    ]:
        inputs = TauPolicyInputs(**{**base, key: bad})
        assert evaluate_tau_policy(inputs).allow_publish is False, key


def test_allow_settle_requires_evidence_and_closed_challenge_window() -> None:
    base = dict(
        has_bounty_ref=True,
        has_submission_ref=True,
        has_evidence_ref=True,
        has_storage_receipt_ref=True,
        challenge_window_closed=True,
        has_open_challenge=False,
    )
    assert evaluate_tau_policy(TauPolicyInputs(**base)).allow_settle is True
    assert evaluate_tau_policy(TauPolicyInputs(**{**base, "has_evidence_ref": False})).allow_settle is False
    assert evaluate_tau_policy(TauPolicyInputs(**{**base, "has_open_challenge": True})).allow_settle is False
    assert evaluate_tau_policy(TauPolicyInputs(**{**base, "challenge_window_closed": False})).allow_settle is False


def test_governance_denies_history_mutation_and_truth_marking() -> None:
    assert evaluate_tau_policy(TauPolicyInputs(governance_action_mutates_history=True)).deny_governance is True
    assert evaluate_tau_policy(TauPolicyInputs(governance_action_marks_truth=True)).deny_governance is True
    assert evaluate_tau_policy(TauPolicyInputs()).deny_governance is False


def test_default_is_fail_closed_deny_everything() -> None:
    out = evaluate_tau_policy(TauPolicyInputs())
    assert out.allow_publish is False
    assert out.allow_settle is False
    assert out.deny_governance is False
    assert out.deny_reason_private_data is False  # no private data referenced
    assert out.deny_reason_missing_evidence is True  # no evidence referenced
    assert out.deny_reason_open_challenge is False  # no challenge referenced


def test_deny_reasons_are_mutually_explanatory() -> None:
    out = evaluate_tau_policy(TauPolicyInputs(publication_requested=True, contains_private_data=True))
    assert out.deny_reason_private_data is True
    assert out.allow_publish is False
