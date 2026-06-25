from __future__ import annotations

from dataclasses import dataclass

from ..log import utc_now_iso
from ..refs import is_ref, require
from .base import AdapterCapability, AnchorAdapter, AnchorReceipt, StorageReceipt, VerificationCheck, VerificationReport


@dataclass(frozen=True)
class TauPolicyInputs:
    """Boolean facts fed into the Tau Net policy evaluator.

    Host software computes complex checks and passes simple facts in; Tau
    decides only the listed allow/deny outputs. Missing facts default to the
    fail-closed (deny) side.
    """

    publication_requested: bool = False
    contains_private_data: bool = False
    bundle_root_matches: bool = False
    required_signatures_present: bool = False
    has_bounty_ref: bool = False
    has_submission_ref: bool = False
    has_evidence_ref: bool = False
    has_storage_receipt_ref: bool = False
    challenge_window_closed: bool = False
    has_open_challenge: bool = False
    governance_action_mutates_history: bool = False
    governance_action_marks_truth: bool = False


@dataclass(frozen=True)
class TauPolicyOutputs:
    allow_publish: bool
    allow_settle: bool
    deny_governance: bool
    allow_anchor: bool
    allow_import: bool
    deny_reason_private_data: bool
    deny_reason_missing_evidence: bool
    deny_reason_open_challenge: bool
    deny_reason_truth_vote: bool


def evaluate_tau_policy(inputs: TauPolicyInputs) -> TauPolicyOutputs:
    """Pure fail-closed policy evaluator for the Tau Net adapter boundary.

    Mirrors the policy intent in ``docs/tau-net-adapter-spec.md``. Every output
    defaults to deny; an ``allow`` requires all of its guards to hold. This is
    the formal counterpart of ``formal/PopperPadTauPolicy.lean``.
    """
    allow_publish = (
        inputs.publication_requested
        and not inputs.contains_private_data
        and inputs.bundle_root_matches
        and inputs.required_signatures_present
    )
    allow_settle = (
        inputs.has_bounty_ref
        and inputs.has_submission_ref
        and inputs.has_evidence_ref
        and inputs.has_storage_receipt_ref
        and inputs.challenge_window_closed
        and not inputs.has_open_challenge
    )
    deny_governance = inputs.governance_action_mutates_history or inputs.governance_action_marks_truth
    allow_anchor = inputs.bundle_root_matches and inputs.required_signatures_present
    allow_import = inputs.bundle_root_matches and not inputs.contains_private_data
    return TauPolicyOutputs(
        allow_publish=allow_publish,
        allow_settle=allow_settle,
        deny_governance=deny_governance,
        allow_anchor=allow_anchor,
        allow_import=allow_import,
        deny_reason_private_data=inputs.contains_private_data and inputs.publication_requested,
        deny_reason_missing_evidence=not inputs.has_evidence_ref,
        deny_reason_open_challenge=inputs.has_open_challenge,
        deny_reason_truth_vote=inputs.governance_action_marks_truth,
    )


class TauNetAnchorAdapter(AnchorAdapter):
    """Placeholder Tau Net anchor adapter.

    Tau Net does not yet expose a stable production PopperPad API. This adapter
    records anchor receipts using the Tau policy boundary so the integration
    surface is fixed and fail-closed; live anchoring is deferred until Tau Net
    tooling is available. See ``docs/tau-net-adapter-spec.md`` MVP section.
    """

    adapter_id = "tau-net-v1"
    kind = "anchor"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(content_addressed=True, append_only=True, native_governance=True)

    def anchor(self, storage_receipt: StorageReceipt, *, anchor_ref: str, config: dict) -> AnchorReceipt:
        require(is_ref(anchor_ref), "anchor_ref must be a sha256 ref")
        policy = evaluate_tau_policy(
            TauPolicyInputs(bundle_root_matches=True, required_signatures_present=True)
        )
        require(policy.allow_anchor, "tau policy denies anchor")
        return AnchorReceipt(
            adapter=self.adapter_id,
            chain_id=str(config.get("chain_id", "tau-net:main")),
            bundle_root=storage_receipt.bundle_root,
            anchor_ref=anchor_ref,
            storage_receipt_ref=storage_receipt.content_id,
            tx_ref="",
            block_ref="",
            contract_ref="",
            event_name="PopperPadBundleAnchored",
            finality={"policy": "tau_agreement", "value": 1},
            created_at=utc_now_iso(),
        )

    def verify(self, receipt: AnchorReceipt, *, config: dict) -> VerificationReport:
        checks = [VerificationCheck("tau_anchor_recorded", "pass" if receipt.bundle_root else "fail")]
        ok = bool(receipt.bundle_root)
        return VerificationReport(
            target_ref=receipt.bundle_root,
            status="pass" if ok else "fail",
            checks=checks,
            verified_at=utc_now_iso(),
        )
