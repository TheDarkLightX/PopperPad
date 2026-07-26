from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path

import pytest

from popperpad.adapters.bundle import Bundle, Manifest, build_manifest, bundle_root, export_bundle, load_bundle_dir
from popperpad.canonical import canonical_hash, canonical_json_bytes
from popperpad.refs import Ref
from popperpad.core.values import is_deeply_immutable


def _ref(seed: str) -> Ref:
    return Ref("sha256:" + seed * 64)


def test_bundle_rejects_unsorted_and_invalid_refs() -> None:
    a, b = _ref("a"), _ref("b")
    with pytest.raises(ValueError):
        Bundle(bundle_id="x", object_refs=(b, a), blob_refs=(), entry_refs=(), previous_bundle_refs=())
    with pytest.raises(ValueError):
        Bundle(bundle_id="x", object_refs=(a,), blob_refs=(), entry_refs=(), previous_bundle_refs=(Ref("sha256:" + "0" * 63),))


def test_manifest_root_hash_is_deterministic_and_content_bound() -> None:
    a, b = _ref("a"), _ref("b")
    bundle = Bundle(
        bundle_id="ex",
        object_refs=(a, b),
        blob_refs=(),
        entry_refs=(a,),
        previous_bundle_refs=(),
    )
    manifest = build_manifest(bundle)
    assert manifest.root_hash == canonical_hash("bundle-content/v1", {
        "object_refs": [str(a), str(b)],
        "blob_refs": [],
        "entry_refs": [str(a)],
        "previous_bundle_refs": [],
    })
    # Same content -> same root_hash and bundle_root regardless of bundle_id/producer.
    bundle2 = Bundle(
        bundle_id="different",
        object_refs=(a, b),
        blob_refs=(),
        entry_refs=(a,),
        previous_bundle_refs=(),
    )
    assert build_manifest(bundle2).root_hash == manifest.root_hash


def test_bundle_root_is_canonical_hash_of_manifest() -> None:
    bundle = Bundle(bundle_id="ex", object_refs=(_ref("a"),), blob_refs=(), entry_refs=(), previous_bundle_refs=())
    manifest = build_manifest(bundle)
    assert bundle_root(manifest) == canonical_hash(
        "bundle-manifest/v1",
        manifest.as_dict(),
    )


def test_bundle_and_manifest_own_nested_metadata() -> None:
    signature = {
        "algorithm": "ed25519",
        "key_id": "sha256:" + "c" * 64,
        "signature_hex": "ab" * 64,
    }
    storage_hint = {"adapter": "local", "proof": {"path": ["root", "leaf"]}}
    producer = {"name": "builder", "versions": [1, 2]}
    bundle = Bundle(
        bundle_id="owned",
        object_refs=(_ref("a"),),
        blob_refs=(),
        entry_refs=(),
        signatures=(signature,),
        storage_hints=(storage_hint,),
    )
    manifest = build_manifest(bundle, producer=producer)
    expected = deepcopy(manifest.as_dict())
    expected_root = bundle_root(manifest)

    signature["signature_hex"] = "00" * 64
    storage_hint["proof"]["path"].append("mutated")
    producer["versions"].append(3)

    assert manifest.as_dict() == expected
    assert bundle_root(manifest) == expected_root
    assert is_deeply_immutable(bundle)
    assert is_deeply_immutable(manifest)
    assert not hasattr(bundle, "__dict__")
    assert not hasattr(manifest, "__dict__")
    with pytest.raises(TypeError):
        manifest.producer["name"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        manifest.storage_hints[0]["adapter"] = "mutated"  # type: ignore[index]


def test_export_and_load_round_trip(tmp_path: Path) -> None:
    obj = {"schema": "popperpad/domain/v1", "domain_id": "A", "name": "A", "tags": []}
    obj_bytes = canonical_json_bytes(obj)
    from popperpad.canonical import sha256_bytes
    obj_ref = Ref(sha256_bytes(obj_bytes))
    blob = b"hello-blob"
    blob_ref = Ref(sha256_bytes(blob))

    bundle = Bundle(
        bundle_id="round-trip",
        object_refs=(obj_ref,),
        blob_refs=(blob_ref,),
        entry_refs=(obj_ref,),
        previous_bundle_refs=(),
    )
    objects = {str(obj_ref): obj_bytes}
    blobs = {str(blob_ref): blob}
    out = tmp_path / "bundle"
    manifest = export_bundle(bundle, out, objects=objects, blobs=blobs)

    # Manifest written and root matches.
    written_manifest = json.loads((out / "manifest.json").read_text())
    assert written_manifest["root_hash"] == manifest.root_hash
    op, orr = obj_ref.hex_pair
    bp, brr = blob_ref.hex_pair
    assert (out / "objects" / "sha256" / op / f"sha256-{op}{orr}.json").exists()
    assert (out / "blobs" / "sha256" / bp / f"sha256-{bp}{brr}").read_bytes() == blob

    loaded = load_bundle_dir(out)
    assert loaded.manifest.root_hash == manifest.root_hash
    assert loaded.objects[str(obj_ref)] == obj_bytes
    assert loaded.blobs[str(blob_ref)] == blob
    assert is_deeply_immutable(loaded)
    assert not hasattr(loaded, "__dict__")
    with pytest.raises(TypeError):
        loaded.objects[str(obj_ref)] = b"mutated"  # type: ignore[index]
