import Std

namespace PopperPadTruthBoundary

inductive LocalStatus where
  | unsupported
  | supported
  | falsified
  | disputed
  deriving DecidableEq, Repr

structure LocalInputs where
  verifierAccepted : Bool
  evidenceDigest : Nat
  contextDigest : Nat
  recipeDigest : Nat
  trustPolicyDigest : Nat

structure FundedView where
  localInputs : LocalInputs
  tokenStake : Nat
  gamePoints : Nat

def localStatusFromInputs (i : LocalInputs) : LocalStatus :=
  if !i.verifierAccepted then
    LocalStatus.unsupported
  else if i.evidenceDigest = 0 then
    LocalStatus.unsupported
  else if i.recipeDigest = 0 then
    LocalStatus.disputed
  else if i.contextDigest = 0 then
    LocalStatus.falsified
  else
    LocalStatus.supported

def localStatus (v : FundedView) : LocalStatus :=
  localStatusFromInputs v.localInputs

theorem token_stake_does_not_change_local_status
    (inputs : LocalInputs)
    (stakeA stakeB : Nat) :
    localStatus { localInputs := inputs, tokenStake := stakeA, gamePoints := 0 }
      = localStatus { localInputs := inputs, tokenStake := stakeB, gamePoints := 0 } := by
  rfl

theorem game_points_do_not_change_local_status
    (inputs : LocalInputs)
    (pointsA pointsB : Nat) :
    localStatus { localInputs := inputs, tokenStake := 0, gamePoints := pointsA }
      = localStatus { localInputs := inputs, tokenStake := 0, gamePoints := pointsB } := by
  rfl

theorem same_evidence_context_recipe_trust_same_status
    (a b : FundedView)
    (h : a.localInputs = b.localInputs) :
    localStatus a = localStatus b := by
  unfold localStatus
  rw [h]

structure VerifierCertificate where
  verifierAccepted : Bool
  certificateDigest : Nat

structure FundedCertificate where
  certificate : VerifierCertificate
  tokenStake : Nat

def payoutEligibleForTruthWork (v : FundedCertificate) : Bool :=
  let c := v.certificate
  c.verifierAccepted && c.certificateDigest != 0

theorem token_stake_does_not_create_truth_payout
    (cert : VerifierCertificate)
    (stakeA stakeB : Nat) :
    payoutEligibleForTruthWork { certificate := cert, tokenStake := stakeA }
      = payoutEligibleForTruthWork { certificate := cert, tokenStake := stakeB } := by
  rfl

theorem unchecked_certificate_not_payable
    (digest stake : Nat) :
    payoutEligibleForTruthWork
      { certificate := { verifierAccepted := false, certificateDigest := digest }, tokenStake := stake } = false := by
  simp [payoutEligibleForTruthWork]

theorem accepted_nonzero_certificate_payable
    (digest stake : Nat)
    (h : digest != 0) :
    payoutEligibleForTruthWork
      { certificate := { verifierAccepted := true, certificateDigest := digest }, tokenStake := stake } = true := by
  simp [payoutEligibleForTruthWork, h]

end PopperPadTruthBoundary
