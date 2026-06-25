import Std

namespace PopperPadTauPolicy

/-- Boolean facts fed into the Tau Net policy evaluator. -/
structure PolicyInputs where
  publication_requested : Bool
  contains_private_data : Bool
  bundle_root_matches : Bool
  required_signatures_present : Bool
  has_bounty_ref : Bool
  has_submission_ref : Bool
  has_evidence_ref : Bool
  has_storage_receipt_ref : Bool
  challenge_window_closed : Bool
  has_open_challenge : Bool
  governance_action_mutates_history : Bool
  governance_action_marks_truth : Bool

structure PolicyOutputs where
  allow_publish : Bool
  allow_settle : Bool
  deny_governance : Bool

def allowPublish (i : PolicyInputs) : Bool :=
  i.publication_requested && !i.contains_private_data && i.bundle_root_matches && i.required_signatures_present

def allowSettle (i : PolicyInputs) : Bool :=
  i.has_bounty_ref && i.has_submission_ref && i.has_evidence_ref && i.has_storage_receipt_ref
    && i.challenge_window_closed && !i.has_open_challenge

def denyGovernance (i : PolicyInputs) : Bool :=
  i.governance_action_mutates_history || i.governance_action_marks_truth

def evaluate (i : PolicyInputs) : PolicyOutputs :=
  { allow_publish := allowPublish i, allow_settle := allowSettle i, deny_governance := denyGovernance i }

-- Fail-closed: with all guards off, nothing is allowed.
theorem fail_closed_default
    (i : PolicyInputs)
    (hpub : ¬ i.publication_requested)
    (hpriv : ¬ i.contains_private_data)
    (hroot : ¬ i.bundle_root_matches)
    (hsig : ¬ i.required_signatures_present)
    (hbounty : ¬ i.has_bounty_ref)
    (hsub : ¬ i.has_submission_ref)
    (hev : ¬ i.has_evidence_ref)
    (hstore : ¬ i.has_storage_receipt_ref)
    (hwin : ¬ i.challenge_window_closed)
    (hgov1 : ¬ i.governance_action_mutates_history)
    (hgov2 : ¬ i.governance_action_marks_truth) :
    (evaluate i).allow_publish = false ∧ (evaluate i).allow_settle = false ∧ (evaluate i).deny_governance = false := by
  unfold evaluate allowPublish allowSettle denyGovernance
  simp [hpub, hpriv, hroot, hsig, hbounty, hsub, hev, hstore, hwin, hgov1, hgov2]

-- Private data always blocks publication, regardless of other guards.
theorem private_data_blocks_publish
    (i : PolicyInputs)
    (hpriv : i.contains_private_data = true) :
    (evaluate i).allow_publish = false := by
  unfold evaluate allowPublish
  simp [hpriv]

-- An open challenge always blocks settlement, regardless of other guards.
theorem open_challenge_blocks_settle
    (i : PolicyInputs)
    (hopen : i.has_open_challenge = true) :
    (evaluate i).allow_settle = false := by
  unfold evaluate allowSettle
  simp [hopen]

-- Truth-marking governance is always denied.
theorem truth_vote_denied
    (i : PolicyInputs)
    (htruth : i.governance_action_marks_truth = true) :
    (evaluate i).deny_governance = true := by
  unfold evaluate denyGovernance
  simp [htruth]

-- Settlement requires evidence: no evidence ref => no settlement.
theorem no_evidence_no_settle
    (i : PolicyInputs)
    (hev : i.has_evidence_ref = false) :
    (evaluate i).allow_settle = false := by
  unfold evaluate allowSettle
  simp [hev]

end PopperPadTauPolicy
