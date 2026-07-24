from __future__ import annotations

import inspect

import pytest

from popperpad.adapters.bundle import build_manifest as build_manifest_shell
from popperpad.core.bundle import Bundle, Manifest, build_manifest, content_root, manifest_root, parse_manifest
from popperpad.core.result import Reject
from popperpad.core.values import FrozenDict


def R(char: str) -> str:
    return "sha256:" + char * 64


def bundle() -> Bundle:
    return Bundle(
        bundle_id="bundle-1",
        object_refs=(R("a"), R("b")),
        blob_refs=(R("c"),),
        entry_refs=(R("a"),),
        previous_bundle_refs=(),
        signatures=(FrozenDict({"key_id": "did:example:alice", "signature": "sig"}),),
        storage_hints=(FrozenDict({"network": "ipfs"}),),
        anchor_hints=(),
    )


def test_core_manifest_requires_explicit_time_and_is_deterministic() -> None:
    value = bundle()
    first = build_manifest(
        value,
        created_at="2026-07-24T00:00:00Z",
        producer={"name": "PopperPad", "version": "0.1.0"},
    )
    second = build_manifest(
        value,
        created_at="2026-07-24T00:00:00Z",
        producer={"version": "0.1.0", "name": "PopperPad"},
    )
    assert first == second
    assert content_root(value) == first.root_hash
    assert manifest_root(first).startswith("sha256:")
    assert isinstance(first.producer, FrozenDict)
    assert isinstance(first.signatures[0], FrozenDict)
    assert tuple(inspect.signature(build_manifest).parameters) == ("bundle", "created_at", "producer")


def test_shell_captures_time_but_core_does_not() -> None:
    manifest = build_manifest_shell(
        bundle(),
        created_at="2026-07-24T00:00:00Z",
        producer={"name": "test"},
    )
    assert manifest.created_at == "2026-07-24T00:00:00Z"


def test_bundle_owns_nested_metadata_aliases() -> None:
    signature = {"key_id": "alice", "claims": ["bundle"]}
    value = Bundle(
        bundle_id="owned",
        object_refs=(R("a"),),
        blob_refs=(),
        entry_refs=(R("a"),),
        signatures=(signature,),
    )
    signature["claims"].append("mutated")
    assert value.signatures[0]["claims"] == ("bundle",)
    with pytest.raises(TypeError):
        value.signatures[0]["key_id"] = "mallory"  # type: ignore[index]


def test_manifest_parse_fails_closed_on_unsorted_duplicates_and_root_mismatch() -> None:
    valid = build_manifest(
        bundle(),
        created_at="2026-07-24T00:00:00Z",
        producer={"name": "test"},
    ).as_dict()

    duplicate = dict(valid)
    duplicate["object_refs"] = [R("a"), R("a")]
    parsed = parse_manifest(duplicate)
    assert isinstance(parsed, Reject)
    assert parsed.code == "INVALID_MANIFEST"

    wrong_root = dict(valid)
    wrong_root["root_hash"] = R("f")
    parsed = parse_manifest(wrong_root)
    assert isinstance(parsed, Reject)
    assert parsed.code == "CONTENT_ROOT_MISMATCH"


def test_entry_refs_must_be_owned_by_bundle() -> None:
    with pytest.raises(ValueError, match="subset"):
        Bundle(
            bundle_id="bad-entry",
            object_refs=(R("a"),),
            blob_refs=(),
            entry_refs=(R("b"),),
        )
