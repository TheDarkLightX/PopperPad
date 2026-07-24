from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from popperpad.canonical import canonical_hash, canonical_json_bytes, sha256_bytes
from popperpad.core.commit import CommitBundle, plan_commit


VECTOR_PATH = Path(__file__).resolve().parents[1] / "vectors" / "fcis-v1.json"


def _vectors() -> dict[str, Any]:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


def test_python_canonical_codec_matches_shared_vectors() -> None:
    vectors = _vectors()
    assert vectors["schema"] == "popperpad/fcis-vectors/v1"
    for case in vectors["canonical_cases"]:
        encoded = canonical_json_bytes(case["value"])
        assert encoded.decode("utf-8") == case["canonical_utf8"], case["name"]
        assert sha256_bytes(encoded) == case["raw_sha256"], case["name"]


def test_python_domain_hashes_match_shared_vectors() -> None:
    for case in _vectors()["domain_hash_cases"]:
        assert canonical_hash(case["domain"], case["value"]) == case["hash"], case["name"]


def test_python_commit_planner_matches_shared_vectors() -> None:
    for case in _vectors()["commit_cases"]:
        source = case["input"]
        planned = plan_commit(
            expected_head=source["expected_head"],
            created_at=source["created_at"],
            objects=tuple(source["objects"]),
            blobs=tuple(
                (blob["payload_utf8"].encode("utf-8"), blob["media_type"])
                for blob in source["blobs"]
            ),
            outbox=tuple((effect["kind"], effect["payload"]) for effect in source["outbox"]),
            evidence_root=source["evidence_root"],
            policy_version=source["policy_version"],
            core_version=source["core_version"],
        )
        assert isinstance(planned, CommitBundle), case["name"]
        expected = case["expected"]
        assert [item.ref for item in planned.objects] == expected["object_refs"]
        assert [item.ref for item in planned.blobs] == expected["blob_refs"]
        assert [item.effect_id for item in planned.outbox] == expected["effect_ids"]
        assert planned.receipt.command_hash == expected["command_hash"]
        assert planned.receipt.replay_id == expected["replay_id"]
        assert planned.receipt.effect_plan_hash == expected["effect_plan_hash"]
        assert planned.commit_root == expected["commit_root"]
        assert planned.record_hash == expected["record_hash"]
        assert canonical_json_bytes(planned.record).decode("utf-8") == expected["record_canonical_utf8"]
