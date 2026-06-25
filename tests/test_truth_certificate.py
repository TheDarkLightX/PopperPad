from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64
REF_D = "sha256:" + "d" * 64
REF_E = "sha256:" + "e" * 64


def _truth_certificate() -> dict[str, object]:
    from popperpad.schemas import SCHEMA_TRUTH_CERTIFICATE_V1

    return {
        "schema": SCHEMA_TRUTH_CERTIFICATE_V1,
        "certificate_id": "lean-proof-cert-001",
        "certificate_kind": "proof",
        "claim_ref": REF_A,
        "context_ref": REF_B,
        "verifier_ref": REF_C,
        "recipe_ref": REF_D,
        "evidence_refs": [REF_E],
        "artifact_refs": [],
        "verifier_result": {
            "accepted": True,
            "status": "supported",
        },
        "signatures": ["did:example:prover#sig"],
        "truth_boundary": "verifier_checked_certificate",
    }


def test_truth_certificate_validates_and_can_be_stored() -> None:
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_object(_truth_certificate())
        assert rep.obj_ref.startswith("sha256:")
        pad.doctor(strict=True)


def test_truth_certificate_rejects_unaccepted_verifier_result() -> None:
    from popperpad.validate import validate_object

    obj = _truth_certificate()
    obj["verifier_result"] = {"accepted": False, "status": "supported"}
    with pytest.raises(ValueError, match="accepted"):
        validate_object(obj)


def test_truth_certificate_requires_evidence() -> None:
    from popperpad.validate import validate_object

    obj = _truth_certificate()
    obj["evidence_refs"] = []
    with pytest.raises(ValueError, match="evidence_refs"):
        validate_object(obj)


def test_truth_certificate_rejects_truth_boundary_drift() -> None:
    from popperpad.validate import validate_object

    obj = _truth_certificate()
    obj["truth_boundary"] = "paid_truth_by_decree"
    with pytest.raises(ValueError, match="truth_boundary"):
        validate_object(obj)
