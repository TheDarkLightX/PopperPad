from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


REF_A = "sha256:" + "a" * 64


def _resource_budget() -> dict[str, object]:
    from popperpad.schemas import SCHEMA_MARKET_RESOURCE_BUDGET_V1

    return {
        "schema": SCHEMA_MARKET_RESOURCE_BUDGET_V1,
        "budget_id": "counterexample-search-budget-001",
        "work_order_ref": REF_A,
        "payer_ref": "did:example:sponsor",
        "settlement_assets": ["AGRS", "USDC", "PPAD_CREDIT"],
        "limits": {
            "compute": "15 AGRS",
            "storage": "2 AGRS",
            "api": "30 USD",
            "verifier": "10 AGRS",
            "retrieval": "3 AGRS",
        },
        "access_paths": ["pay", "earn", "grant", "local"],
        "model_policy": {
            "cheap_model_first": True,
            "max_paid_escalations": 2,
        },
        "truth_boundary": "resource_funding_only",
    }


def test_market_resource_budget_validates_and_can_be_stored() -> None:
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_object(_resource_budget())
        assert rep.obj_ref.startswith("sha256:")
        pad.doctor(strict=True)


def test_market_resource_budget_rejects_truth_buying_boundary() -> None:
    from popperpad.validate import validate_object

    obj = _resource_budget()
    obj["truth_boundary"] = "stake_marks_true"
    with pytest.raises(ValueError, match="truth_boundary"):
        validate_object(obj)


def test_market_resource_budget_rejects_unknown_access_path() -> None:
    from popperpad.validate import validate_object

    obj = _resource_budget()
    obj["access_paths"] = ["pay", "whale_only"]
    with pytest.raises(ValueError, match="access_paths"):
        validate_object(obj)


def test_market_resource_budget_rejects_unknown_limit_key() -> None:
    from popperpad.validate import validate_object

    obj = _resource_budget()
    obj["limits"] = {"truth": "100 AGRS"}
    with pytest.raises(ValueError, match="limits keys"):
        validate_object(obj)
