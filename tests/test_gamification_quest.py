from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64


def _quest() -> dict[str, object]:
    from popperpad.schemas import SCHEMA_GAMIFICATION_QUEST_V1

    return {
        "schema": SCHEMA_GAMIFICATION_QUEST_V1,
        "quest_id": "lean-proof-week-001",
        "title": "Prove or refute a queued Lean theorem",
        "quest_type": "proof",
        "domain_ref": REF_A,
        "objective": {
            "summary": "Submit a verifier-accepted proof or counterexample.",
            "target_ref": REF_B,
        },
        "accepted_event_kinds": ["proof_accepted", "counterexample_verified"],
        "rewards": {
            "points": {
                "xp": 500,
                "reputation": 25,
                "season_score": 100,
            },
            "token_budget_ref": REF_C,
        },
        "completion": {
            "required_evidence_count": 1,
            "deadline": "2026-12-31T23:59:59Z",
        },
        "anti_abuse": {
            "max_rewards_per_agent": 3,
            "requires_independent_reproduction": True,
        },
        "truth_boundary": "gamification_only",
    }


def test_gamification_quest_validates_and_can_be_stored() -> None:
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_object(_quest())
        assert rep.obj_ref.startswith("sha256:")
        pad.doctor(strict=True)


def test_gamification_quest_requires_accepted_event_kinds() -> None:
    from popperpad.validate import validate_object

    obj = _quest()
    obj["accepted_event_kinds"] = []
    with pytest.raises(ValueError, match="accepted_event_kinds"):
        validate_object(obj)


def test_gamification_quest_rejects_unknown_event_kind() -> None:
    from popperpad.validate import validate_object

    obj = _quest()
    obj["accepted_event_kinds"] = ["upvote_received"]
    with pytest.raises(ValueError, match="accepted_event_kinds"):
        validate_object(obj)


def test_gamification_quest_rejects_truth_boundary_drift() -> None:
    from popperpad.validate import validate_object

    obj = _quest()
    obj["truth_boundary"] = "quest_marks_true"
    with pytest.raises(ValueError, match="truth_boundary"):
        validate_object(obj)
