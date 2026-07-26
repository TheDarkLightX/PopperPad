from __future__ import annotations

import json
from pathlib import Path

import pytest

from popperpad.adapters import (
    AnchorReceipt,
    Bundle,
    LocalAnchorAdapter,
    LocalStorageAdapter,
    PreparedBundle,
    TrustPolicy,
    build_manifest,
    bundle_root,
)
from popperpad.adapters.flow import gather_from_pad, import_bundle, prepare, verify_bundle
from popperpad.adapters.bundle import Manifest, export_bundle
from popperpad.canonical import canonical_json_bytes, sha256_bytes
from popperpad.pad import PopperPad
from popperpad.refs import Ref
from popperpad.schemas import SCHEMA_DOMAIN_V1, SCHEMA_MARKET_WORK_ORDER_V1


def _pad_with_domain(tmp_path: Path) -> tuple[PopperPad, str]:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    obj = {"schema": SCHEMA_DOMAIN_V1, "domain_id": "A", "name": "A", "tags": []}
    obj_ref = pad.put_object(obj).obj_ref
    return pad, obj_ref


def _unsigned_policy(manifest: Manifest) -> TrustPolicy:
    return TrustPolicy(
        require_signatures=False,
        expected_bundle_root=bundle_root(manifest),
    )


def test_gather_prepare_export_publish_anchor_round_trip(tmp_path: Path) -> None:
    pad, obj_ref = _pad_with_domain(tmp_path)
    bundle, objects, blobs = gather_from_pad(pad, object_refs=[obj_ref], entry_refs=[obj_ref], bundle_id="b1")
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    prepared = prepare(bundle, manifest, objects, blobs)
    assert prepared.canonicalization == "popperpad-json-c14n-v1"
    assert prepared.object_count == 1
    assert prepared.bundle_root == bundle_root(manifest)

    bundle_dir = tmp_path / "bundle"
    export_bundle(bundle, bundle_dir, objects=objects, blobs=blobs, created_at="2026-01-01T00:00:00Z")

    storage = LocalStorageAdapter()
    receipt = storage.publish(prepared, bundle_dir, config={"root": tmp_path / "store", "publisher_ref": "did:example:alice"})
    assert receipt.bundle_root == prepared.bundle_root

    sv = storage.verify(receipt, config={})
    assert sv.ok

    anchor = LocalAnchorAdapter()
    anchor_ref = Ref(sha256_bytes(canonical_json_bytes({"anchor": 1})))
    areceipt = anchor.anchor(receipt, anchor_ref=str(anchor_ref), config={"log_path": tmp_path / "anchors.jsonl"})
    assert areceipt.bundle_root == prepared.bundle_root
    av = anchor.verify(areceipt, config={})
    assert av.ok


def test_import_rejects_bundle_with_wrong_root(tmp_path: Path) -> None:
    pad, obj_ref = _pad_with_domain(tmp_path)
    bundle, objects, blobs = gather_from_pad(pad, object_refs=[obj_ref], entry_refs=[obj_ref], bundle_id="b1")
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    bundle_dir = tmp_path / "bundle"
    export_bundle(bundle, bundle_dir, objects=objects, blobs=blobs, created_at="2026-01-01T00:00:00Z")

    # Tamper: rewrite manifest with a wrong root_hash.
    mp = bundle_dir / "manifest.json"
    data = json.loads(mp.read_text())
    data["root_hash"] = "sha256:" + "0" * 64
    mp.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")

    target = PopperPad(root=tmp_path / "imported")
    target.init()
    report = import_bundle(bundle_dir, target, _unsigned_policy(manifest))
    assert report.status == "rejected"


def test_import_round_trip_into_new_pad(tmp_path: Path) -> None:
    pad, obj_ref = _pad_with_domain(tmp_path)
    bundle, objects, blobs = gather_from_pad(pad, object_refs=[obj_ref], entry_refs=[obj_ref], bundle_id="b1")
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    bundle_dir = tmp_path / "bundle"
    export_bundle(bundle, bundle_dir, objects=objects, blobs=blobs, created_at="2026-01-01T00:00:00Z")

    target = PopperPad(root=tmp_path / "imported")
    target.init()
    report = import_bundle(bundle_dir, target, _unsigned_policy(manifest))
    assert report.status == "imported"
    assert obj_ref in report.imported_object_refs
    assert target.get_object(obj_ref)["domain_id"] == "A"
    target.doctor(strict=True)


def test_import_preserves_legacy_float_object_in_one_atomic_record(tmp_path: Path) -> None:
    legacy = {
        "schema": SCHEMA_MARKET_WORK_ORDER_V1,
        "task_type": "counterexample",
        "claim_ref": "sha256:" + "a" * 64,
        "context_ref": "sha256:" + "b" * 64,
        "accepted_recipe_refs": ["sha256:" + "c" * 64],
        "accepted_verifier_refs": ["sha256:" + "d" * 64],
        "max_payout": "1000 PPAD",
        "min_bond": "25 PPAD",
        "deadline": "2026-12-31T23:59:59Z",
        "payout_condition": "valid_counterexample",
        "challenge_window_seconds": 604800,
        "scoring": {"novelty_weight": 0.30},
    }
    payload = canonical_json_bytes(legacy)
    obj_ref = sha256_bytes(payload)
    bundle = Bundle(
        bundle_id="legacy-float",
        object_refs=(Ref(obj_ref),),
        blob_refs=(),
        entry_refs=(Ref(obj_ref),),
        previous_bundle_refs=(),
    )
    bundle_dir = tmp_path / "legacy-bundle"
    manifest = export_bundle(
        bundle,
        bundle_dir,
        objects={obj_ref: payload},
        blobs={},
        created_at="2026-07-24T00:00:00Z",
    )

    target = PopperPad(root=tmp_path / "legacy-target")
    target.init()
    report = import_bundle(bundle_dir, target, _unsigned_policy(manifest))
    assert report.status == "imported"
    assert report.imported_object_refs == (obj_ref,)
    assert target.get_object(obj_ref) == legacy
    assert len(list(target.log.iter_raw_records())) == 1
    target.doctor(strict=True)


def test_verify_bundle_passes_for_clean_export(tmp_path: Path) -> None:
    pad, obj_ref = _pad_with_domain(tmp_path)
    bundle, objects, blobs = gather_from_pad(pad, object_refs=[obj_ref], entry_refs=[obj_ref], bundle_id="b1")
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    bundle_dir = tmp_path / "bundle"
    export_bundle(bundle, bundle_dir, objects=objects, blobs=blobs, created_at="2026-01-01T00:00:00Z")
    report = verify_bundle(bundle_dir)
    assert report.ok
