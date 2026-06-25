from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64


def _score_event() -> dict[str, object]:
    from popperpad.schemas import SCHEMA_GAMIFICATION_SCORE_EVENT_V1

    return {
        "schema": SCHEMA_GAMIFICATION_SCORE_EVENT_V1,
        "event_id": "proof-accepted-001",
        "agent_ref": "did:example:prover",
        "event_kind": "proof_accepted",
        "point_kind": "xp",
        "point_delta": 250,
        "subject_ref": REF_A,
        "domain_ref": REF_B,
        "evidence_refs": [REF_C],
        "token_reward": "12 AGRS",
        "anti_abuse": {
            "verifier_required": True,
            "sybil_risk": 0.05,
        },
        "truth_boundary": "gamification_only",
    }


def test_gamification_score_event_validates_and_can_be_stored() -> None:
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_object(_score_event())
        assert rep.obj_ref.startswith("sha256:")
        pad.doctor(strict=True)


def test_gamification_score_event_requires_evidence() -> None:
    from popperpad.validate import validate_object

    obj = _score_event()
    obj["evidence_refs"] = []
    with pytest.raises(ValueError, match="evidence_refs"):
        validate_object(obj)


def test_gamification_score_event_rejects_truth_boundary_drift() -> None:
    from popperpad.validate import validate_object

    obj = _score_event()
    obj["truth_boundary"] = "points_mark_true"
    with pytest.raises(ValueError, match="truth_boundary"):
        validate_object(obj)


def test_gamification_score_event_rejects_unknown_event_kind() -> None:
    from popperpad.validate import validate_object

    obj = _score_event()
    obj["event_kind"] = "popularity_vote"
    with pytest.raises(ValueError, match="event_kind"):
        validate_object(obj)
