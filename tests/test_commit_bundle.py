from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from popperpad.adapters import Bundle, TrustPolicy
from popperpad.adapters.bundle import export_bundle
from popperpad.adapters.flow import import_bundle
from popperpad.canonical import canonical_json_bytes, sha256_bytes
from popperpad.core.codec import canonical_hash
from popperpad.core.commit import BlobWrite, CommitBundle, ObjectWrite, plan_commit
from popperpad.core.result import Reject
from popperpad.core.values import FrozenDict, freeze_json, thaw_json
from popperpad.log import AppendOnlyLog
from popperpad.pad import PopperPad
from popperpad.refs import Ref
from popperpad.schemas import SCHEMA_DOMAIN_V1


def _domain(name: str) -> dict[str, object]:
    return {"schema": SCHEMA_DOMAIN_V1, "domain_id": name, "name": name, "tags": []}


def test_commit_plan_is_deterministic_domain_bound_and_immutable() -> None:
    kwargs = {
        "expected_head": "",
        "created_at": "2026-07-24T00:00:00Z",
        "objects": (_domain("A"),),
        "outbox": (("announce", {"topic": "formal", "attempt": 1}),),
        "policy_version": "policy/v1",
        "core_version": "core/v1",
    }
    first = plan_commit(**kwargs)
    second = plan_commit(**kwargs)
    assert isinstance(first, CommitBundle)
    assert first == second
    assert first.commit_root.startswith("sha256:")
    assert first.receipt.pre_state_root == ""
    assert first.receipt.next_state_root == first.commit_root
    assert first.receipt.effect_plan_hash.startswith("sha256:")
    assert isinstance(first.record, FrozenDict)
    assert isinstance(first.outbox[0].payload, FrozenDict)
    assert first.outbox[0].effect_id != first.commit_root

def test_replay_identity_binds_effects_evidence_and_commit_time() -> None:
    common = {
        "expected_head": "",
        "created_at": "2026-07-24T00:00:00Z",
        "objects": (_domain("A"),),
        "outbox": (("notify", {"value": 1}),),
        "evidence_root": "sha256:" + "a" * 64,
    }
    baseline = plan_commit(**common)
    changed_effect = plan_commit(
        **{**common, "outbox": (("notify", {"value": 2}),)}
    )
    changed_evidence = plan_commit(
        **{**common, "evidence_root": "sha256:" + "b" * 64}
    )
    changed_time = plan_commit(
        **{**common, "created_at": "2026-07-24T00:00:01Z"}
    )
    assert all(
        isinstance(value, CommitBundle)
        for value in (baseline, changed_effect, changed_evidence, changed_time)
    )
    replay_ids = {
        value.receipt.replay_id
        for value in (baseline, changed_effect, changed_evidence, changed_time)
        if isinstance(value, CommitBundle)
    }
    assert len(replay_ids) == 4



def test_commit_plan_rejects_inexact_or_duplicate_authoritative_values() -> None:
    inexact = plan_commit(
        expected_head="",
        created_at="2026-07-24T00:00:00Z",
        objects=({"schema": SCHEMA_DOMAIN_V1, "domain_id": "A", "name": "A", "risk": 0.5},),
    )
    assert isinstance(inexact, Reject)
    assert inexact.code == "INVALID_OBJECT"

    duplicate = plan_commit(
        expected_head="",
        created_at="2026-07-24T00:00:00Z",
        objects=(_domain("A"), _domain("A")),
    )
    assert isinstance(duplicate, Reject)
    assert duplicate.code == "DUPLICATE_WRITE"


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    (
        ({"evidence_root": "not-a-ref"}, "INVALID_EVIDENCE_ROOT"),
        ({"created_at": ""}, "INVALID_CREATED_AT"),
        ({"created_at": "", "evidence_root": "not-a-ref"}, "INVALID_CREATED_AT"),
        ({"objects": (1,)}, "INVALID_OBJECT"),
        ({"objects": ({"schema": "example/v1", "weight": 0.5},)}, "INVALID_OBJECT"),
        ({"blobs": ((b"blob", ""),)}, "INVALID_MEDIA_TYPE"),
        ({"outbox": (("", {}),)}, "INVALID_EFFECT"),
        ({"outbox": (("notify", 1),)}, "INVALID_OBJECT"),
        ({"outbox": (("notify", {"weight": 0.5}),)}, "INVALID_OBJECT"),
    ),
)
def test_python_planner_rejects_rust_parity_boundaries(
    overrides: dict[str, object], expected_code: str
) -> None:
    kwargs: dict[str, object] = {
        "expected_head": "",
        "created_at": "2026-07-24T00:00:00Z",
    }
    kwargs.update(overrides)
    planned = plan_commit(**kwargs)  # type: ignore[arg-type]
    assert isinstance(planned, Reject)
    assert planned.code == expected_code


def test_commit_value_constructors_reject_wrong_immutable_runtime_types() -> None:
    with pytest.raises(TypeError, match="payload"):
        ObjectWrite(
            ref="sha256:" + "a" * 64,
            schema="example/v1",
            payload=bytearray(b"mutable"),  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="media_type"):
        BlobWrite(
            ref="sha256:" + "b" * 64,
            media_type=7,  # type: ignore[arg-type]
            payload=b"owned",
        )


def test_batch_commit_has_one_physical_record_and_legacy_logical_projection(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    committed = pad.commit_values(
        objects=(_domain("A"), _domain("B")),
        blobs=((b"witness", "application/octet-stream"),),
        created_at="2026-07-24T00:00:00Z",
    )

    raw = list(pad.log.iter_raw_records())
    logical = list(pad.log.iter_records())
    assert len(raw) == 1
    assert raw[0]["schema"] == "popperpad/log_record/v2"
    assert raw[0]["op"] == "commit_bundle"
    assert len(logical) == 3
    assert [record["op"] for record in logical] == ["add_object", "add_object", "add_blob"]
    assert pad.log.stats() == {"event_count": 1, "head": committed.record_hash}
    assert {pad.get_object(ref)["domain_id"] for ref in committed.object_refs} == {"A", "B"}
    assert pad.get_blob(committed.blob_refs[0]) == b"witness"
    pad.doctor(strict=True)


def test_stale_commit_plan_is_rejected_without_authoritative_publication(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    expected_head = pad.log.head()
    stale = plan_commit(
        expected_head=expected_head,
        created_at="2026-07-24T00:00:00Z",
        objects=(_domain("stale"),),
    )
    assert isinstance(stale, CommitBundle)
    pad.put_object(_domain("winner"))
    winning_head = pad.log.head()

    pad._stage_commit_payloads(stale)
    with pytest.raises(ValueError, match="commit conflict"):
        pad.log.append_prepared(stale, expected_head=expected_head)

    assert pad.log.head() == winning_head
    authoritative_domains = [
        pad.get_object(record["obj_ref"])["domain_id"]
        for record in pad.log.iter_records()
        if record.get("op") == "add_object"
    ]
    assert authoritative_domains == ["winner"]


def test_log_failure_leaves_only_unreferenced_cas_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()

    def fail_append(_record: object, *, expected_head: str) -> object:
        raise OSError(f"injected append failure at {expected_head!r}")

    monkeypatch.setattr(pad.log, "append_prepared", fail_append)
    with pytest.raises(OSError, match="injected append failure"):
        pad.put_object(_domain("orphan"))

    assert pad.log.stats() == {"event_count": 0, "head": ""}
    assert list(pad.log.iter_records()) == []
    report = pad.doctor(strict=False)
    assert report.ok
    assert report.stats["objects"] == 0


def test_corrupt_predecessor_blocks_later_authoritative_append(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    pad.put_object(_domain("first"))

    records = [json.loads(line) for line in pad.log.path.read_text(encoding="utf-8").splitlines()]
    records[0]["commit_root"] = "sha256:" + "0" * 64
    pad.log.path.write_text(
        "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="INVALID_COMMIT_RECORD"):
        pad.put_object(_domain("second"))
    assert len(list(pad.log.iter_raw_records())) == 1


def test_mixed_legacy_and_v2_records_verify_as_one_hash_chain(tmp_path: Path) -> None:
    log = AppendOnlyLog(path=tmp_path / "log.jsonl")
    log.init()
    legacy = log.append(
        {
            "schema": "popperpad/log_record/v1",
            "op": "note",
            "created_at": "2026-07-23T00:00:00Z",
        }
    )
    planned = plan_commit(
        expected_head=legacy.record_hash,
        created_at="2026-07-24T00:00:00Z",
        blobs=((b"next", "application/octet-stream"),),
    )
    assert isinstance(planned, CommitBundle)
    log.append_prepared(planned, expected_head=legacy.record_hash)
    log.verify()
    assert log.head() == planned.record_hash
    assert [record["op"] for record in log.iter_records()] == ["note", "add_blob"]


def test_prepared_log_rejects_self_hashed_semantic_forgery(tmp_path: Path) -> None:
    log = AppendOnlyLog(path=tmp_path / "log.jsonl")
    log.init()
    planned = plan_commit(
        expected_head="",
        created_at="2026-07-24T00:00:00Z",
        outbox=(("notify", {"value": 1}),),
    )
    assert isinstance(planned, CommitBundle)
    forged = thaw_json(planned.record)
    forged["commit_root"] = "sha256:" + "0" * 64
    record_core = dict(forged)
    record_core.pop("record_hash")
    forged["record_hash"] = canonical_hash("log-record/v2", record_core)

    forged_record = freeze_json(forged)
    assert isinstance(forged_record, FrozenDict)
    forged_bundle = replace(
        planned,
        commit_root=forged["commit_root"],
        record_hash=forged["record_hash"],
        record=forged_record,
    )

    with pytest.raises(ValueError, match="INVALID_COMMIT_RECORD"):
        log.append_prepared(forged_bundle, expected_head="")

    assert log.stats() == {"event_count": 0, "head": ""}


def test_bundle_preflight_failure_commits_nothing(tmp_path: Path) -> None:
    valid_bytes = canonical_json_bytes(_domain("A"))
    invalid_bytes = canonical_json_bytes({"schema": "popperpad/unknown/v1", "value": 1})
    valid_ref = Ref(sha256_bytes(valid_bytes))
    invalid_ref = Ref(sha256_bytes(invalid_bytes))
    object_refs = tuple(sorted((valid_ref, invalid_ref)))
    bundle = Bundle(
        bundle_id="atomic-import",
        object_refs=object_refs,
        blob_refs=(),
        entry_refs=object_refs,
        previous_bundle_refs=(),
    )
    objects = {str(valid_ref): valid_bytes, str(invalid_ref): invalid_bytes}
    bundle_dir = tmp_path / "bundle"
    export_bundle(
        bundle,
        bundle_dir,
        objects=objects,
        blobs={},
        created_at="2026-07-24T00:00:00Z",
    )

    target = PopperPad(root=tmp_path / "target")
    target.init()
    report = import_bundle(bundle_dir, target, TrustPolicy(require_signatures=False))
    assert report.status == "rejected"
    assert report.imported_object_refs == ()
    assert target.log.stats() == {"event_count": 0, "head": ""}
    assert list(target.log.iter_records()) == []
