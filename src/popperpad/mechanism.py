"""Compatibility exports for the pure mechanism core.

New code should import from :mod:`popperpad.core.mechanism` directly. This
module remains so existing callers do not need to move in the same release.
"""

from .core.mechanism import (
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
from .core.values import Amount

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
