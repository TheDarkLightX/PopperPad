import Std

namespace PopperPadMechanism

structure FraudCase where
  gain : Int
  detectionPenalty : Int
  futureLost : Int

def defectUtility (c : FraudCase) : Int :=
  c.gain - c.detectionPenalty - c.futureLost

theorem defect_nonpositive_of_bound
    (c : FraudCase)
    (h : c.gain <= c.detectionPenalty + c.futureLost) :
    defectUtility c <= 0 := by
  unfold defectUtility
  omega

structure HonestWork where
  reward : Int
  reputationValue : Int
  cost : Int
  expectedSlashCost : Int

def honestUtility (w : HonestWork) : Int :=
  w.reward + w.reputationValue - w.cost - w.expectedSlashCost

theorem honest_participates_of_positive
    (w : HonestWork)
    (h : w.cost + w.expectedSlashCost < w.reward + w.reputationValue) :
    0 < honestUtility w := by
  unfold honestUtility
  omega

/-- Treasury epoch: starting balance + inflows must cover outflows + reserve. -/
structure TreasuryEpoch where
  startingBalance : Int
  inflows : Int
  committedOutflows : Int
  reserveRequirement : Int

def treasurySolvent (e : TreasuryEpoch) : Bool :=
  e.startingBalance + e.inflows >= e.committedOutflows + e.reserveRequirement

theorem treasury_solvent_of_margin_nonneg
    (e : TreasuryEpoch)
    (h : e.startingBalance + e.inflows >= e.committedOutflows + e.reserveRequirement) :
    treasurySolvent e = true := by
  unfold treasurySolvent
  simp [h]

theorem treasury_insolvent_of_margin_neg
    (e : TreasuryEpoch)
    (h : e.startingBalance + e.inflows < e.committedOutflows + e.reserveRequirement) :
    treasurySolvent e = false := by
  unfold treasurySolvent
  simp [h]

/-- Resource budget: funded amount must cover total cost. -/
structure ResourceBudget where
  funded : Int
  compute : Int
  storage : Int
  api : Int
  verifier : Int
  retrieval : Int

def totalCost (b : ResourceBudget) : Int :=
  b.compute + b.storage + b.api + b.verifier + b.retrieval

def resourceBudgetCovered (b : ResourceBudget) : Bool :=
  b.funded >= totalCost b

theorem budget_covered_of_funded_ge_cost
    (b : ResourceBudget)
    (h : b.funded >= totalCost b) :
    resourceBudgetCovered b = true := by
  unfold resourceBudgetCovered
  simp [h]

/-- Certificate payable: all four guards must hold. -/
structure CertificateCase where
  paymentOffered : Int
  verifierAccepted : Bool
  certificateAvailable : Bool
  challengeFailed : Bool

def certificatePayable (c : CertificateCase) : Bool :=
  c.paymentOffered > 0 && c.verifierAccepted && c.certificateAvailable && !c.challengeFailed

theorem certificate_not_payable_without_verifier
    (c : CertificateCase)
    (h : c.verifierAccepted = false) :
    certificatePayable c = false := by
  unfold certificatePayable
  simp [h]

theorem certificate_not_payable_if_challenge_failed
    (c : CertificateCase)
    (h : c.challengeFailed = true) :
    certificatePayable c = false := by
  unfold certificatePayable
  simp [h]

theorem certificate_not_payable_without_payment
    (c : CertificateCase)
    (h : c.paymentOffered <= 0) :
    certificatePayable c = false := by
  unfold certificatePayable
  have : ¬ (c.paymentOffered > 0) := by omega
  simp [this]

/-- Truth boundary: stake alone never changes status. -/
structure TruthBoundaryInputs where
  stakeChanged : Bool
  verifierResultChanged : Bool
  localStatusInputsChanged : Bool
  statusChanged : Bool

def truthBoundaryHolds (i : TruthBoundaryInputs) : Bool :=
  if ¬ i.statusChanged then true
  else if i.verifierResultChanged then true
  else if i.localStatusInputsChanged then true
  else false

theorem stake_alone_never_changes_status
    (i : TruthBoundaryInputs)
    (_hstake : i.stakeChanged = true)
    (hver : i.verifierResultChanged = false)
    (hlocal : i.localStatusInputsChanged = false)
    (hstatus : i.statusChanged = true) :
    truthBoundaryHolds i = false := by
  unfold truthBoundaryHolds
  simp [hstatus, hver, hlocal]

theorem status_change_allowed_with_verifier_change
    (i : TruthBoundaryInputs)
    (hver : i.verifierResultChanged = true)
    (hstatus : i.statusChanged = true) :
    truthBoundaryHolds i = true := by
  unfold truthBoundaryHolds
  simp [hstatus, hver]

end PopperPadMechanism
