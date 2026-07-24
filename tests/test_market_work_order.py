from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64


def _work_order() -> dict[str, object]:
    from popperpad.schemas import SCHEMA_MARKET_WORK_ORDER_V1

    return {
        "schema": SCHEMA_MARKET_WORK_ORDER_V1,
        "task_type": "counterexample",
        "claim_ref": REF_A,
        "context_ref": REF_B,
        "accepted_recipe_refs": [REF_C],
        "accepted_verifier_refs": [REF_B],
        "max_payout": "1000 PPAD",
        "min_bond": "25 PPAD",
        "deadline": "2026-12-31T23:59:59Z",
        "payout_condition": "valid_counterexample",
        "challenge_window_seconds": 604800,
        "scoring": {
            "novelty_weight_bps": 3000,
            "minimality_weight_bps": 2000,
            "severity_weight_bps": 3000,
            "reproducibility_weight_bps": 2000,
        },
    }


def test_market_work_order_validates_and_can_be_stored() -> None:
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_object(_work_order())
        assert rep.obj_ref.startswith("sha256:")
        pad.doctor(strict=True)


def test_legacy_float_scoring_value_remains_storable() -> None:
    from popperpad.pad import PopperPad

    obj = _work_order()
    obj["scoring"] = {"novelty_weight": 0.30}
    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_object(obj)
        assert pad.get_object(rep.obj_ref) == obj
        pad.doctor(strict=True)


def test_market_work_order_rejects_unknown_task_type() -> None:
    from popperpad.validate import validate_object

    obj = _work_order()
    obj["task_type"] = "truth_vote"
    with pytest.raises(ValueError, match="task_type"):
        validate_object(obj)


def test_market_work_order_rejects_negative_scoring_weight() -> None:
    from popperpad.validate import validate_object

    obj = _work_order()
    obj["scoring"] = {"novelty_weight_bps": -1}
    with pytest.raises(ValueError, match="scoring values"):
        validate_object(obj)


def test_market_work_order_accepts_proof_bounty_shape() -> None:
    from popperpad.validate import validate_object

    obj = _work_order()
    obj["task_type"] = "proof"
    obj["payout_condition"] = "verifier_passes"
    validate_object(obj)
