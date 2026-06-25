from __future__ import annotations

import json
import tempfile
from pathlib import Path


REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64


def _event(agent_ref: str, points: int, *, event_id: str, point_kind: str = "xp") -> dict[str, object]:
    from popperpad.schemas import SCHEMA_GAMIFICATION_SCORE_EVENT_V1

    return {
        "schema": SCHEMA_GAMIFICATION_SCORE_EVENT_V1,
        "event_id": event_id,
        "agent_ref": agent_ref,
        "event_kind": "proof_accepted",
        "point_kind": point_kind,
        "point_delta": points,
        "subject_ref": REF_A,
        "domain_ref": REF_B,
        "evidence_refs": [REF_C],
        "truth_boundary": "gamification_only",
    }


def test_aggregate_score_events_orders_by_points() -> None:
    from popperpad.gamification import aggregate_score_events

    rows = aggregate_score_events(
        [
            _event("did:example:bob", 50, event_id="e1"),
            _event("did:example:alice", 100, event_id="e2"),
            _event("did:example:bob", 75, event_id="e3"),
        ]
    )

    assert rows == [
        {
            "agent_ref": "did:example:bob",
            "point_kind": "xp",
            "domain_ref": REF_B,
            "points": 125,
            "event_count": 2,
        },
        {
            "agent_ref": "did:example:alice",
            "point_kind": "xp",
            "domain_ref": REF_B,
            "points": 100,
            "event_count": 1,
        },
    ]


def test_aggregate_score_events_skips_invalid_events_when_non_strict() -> None:
    from popperpad.gamification import aggregate_score_events

    invalid = _event("did:example:mallory", 10, event_id="bad")
    invalid["evidence_refs"] = []
    rows = aggregate_score_events([invalid, _event("did:example:alice", 5, event_id="ok")], strict=False)
    assert len(rows) == 1
    assert rows[0]["agent_ref"] == "did:example:alice"


def test_gamification_leaderboard_cli(capsys) -> None:
    from popperpad.cli import main
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pad"
        pad = PopperPad(root=root)
        pad.init()
        pad.put_object(_event("did:example:bob", 50, event_id="e1"))
        pad.put_object(_event("did:example:alice", 100, event_id="e2"))

        assert main(["--pad", str(root), "gamification-leaderboard", "--limit", "2"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is True
        assert output["leaderboard"][0]["agent_ref"] == "did:example:alice"
        assert output["leaderboard"][0]["points"] == 100
