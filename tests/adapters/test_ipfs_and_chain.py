from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import pytest

from popperpad.adapters.bundle import Bundle, build_manifest, bundle_root, export_bundle
from popperpad.adapters.chain import EVM_FAMILIES, EvmAnchorAdapter, EvmClient
from popperpad.adapters.ipfs import IpfsClient, IpfsStorageAdapter
from popperpad.adapters.base import PreparedBundle, StorageReceipt
from popperpad.canonical import canonical_json_bytes, sha256_bytes
from popperpad.refs import Ref
from popperpad.schemas import SCHEMA_DOMAIN_V1


def _make_bundle(tmp_path: Path) -> tuple[Path, PreparedBundle, str]:
    obj = {"schema": SCHEMA_DOMAIN_V1, "domain_id": "A", "name": "A", "tags": []}
    obj_bytes = canonical_json_bytes(obj)
    obj_ref = Ref(sha256_bytes(obj_bytes))
    bundle = Bundle(
        bundle_id="ipfs-test",
        object_refs=(obj_ref,),
        blob_refs=(),
        entry_refs=(obj_ref,),
        previous_bundle_refs=(),
    )
    manifest = build_manifest(bundle, created_at="2026-01-01T00:00:00Z")
    prepared = PreparedBundle(
        manifest_ref=sha256_bytes(canonical_json_bytes(manifest.as_dict())),
        bundle_root=bundle_root(manifest),
        object_count=1,
        blob_count=0,
        byte_size=len(obj_bytes),
    )
    bundle_dir = tmp_path / "bundle"
    export_bundle(bundle, bundle_dir, objects={str(obj_ref): obj_bytes}, blobs={}, created_at="2026-01-01T00:00:00Z")
    return bundle_dir, prepared, str(obj_ref)


class FakeIpfsClient:
    """Hermetic IPFS stand-in: copies bundle dir to a fake store keyed by CID."""

    def __init__(self, store_root: Path) -> None:
        self._store = store_root
        self._store.mkdir(parents=True, exist_ok=True)
        self._pinned: set[str] = set()
        self._cid_counter = 0

    def add_dir(self, path: str) -> str:
        self._cid_counter += 1
        cid = f"QmFake{self._cid_counter:012d}"
        target = self._store / cid
        shutil.copytree(path, target, dirs_exist_ok=True)
        return cid

    def pin(self, cid: str) -> None:
        self._pinned.add(cid)

    def is_pinned(self, cid: str) -> bool:
        return cid in self._pinned

    def get(self, cid: str, out_dir: str) -> None:
        src = self._store / cid
        shutil.copytree(src, Path(out_dir) / cid, dirs_exist_ok=True)


def test_ipfs_publish_pin_verify_round_trip(tmp_path: Path) -> None:
    bundle_dir, prepared, _ = _make_bundle(tmp_path)
    client = FakeIpfsClient(tmp_path / "ipfs_store")
    adapter = IpfsStorageAdapter(client=client)
    receipt = adapter.publish(prepared, bundle_dir, config={"publisher_ref": "did:example:alice"})
    assert receipt.adapter == "ipfs-cid-v1"
    assert client.is_pinned(receipt.content_id)

    report = adapter.verify(receipt, config={})
    assert report.ok, [c.name for c in report.checks if c.status != "pass"]


def test_ipfs_verify_fails_when_unpinned(tmp_path: Path) -> None:
    bundle_dir, prepared, _ = _make_bundle(tmp_path)
    client = FakeIpfsClient(tmp_path / "ipfs_store")
    adapter = IpfsStorageAdapter(client=client)
    receipt = adapter.publish(prepared, bundle_dir, config={})
    client._pinned.discard(receipt.content_id)  # simulate unpin
    report = adapter.verify(receipt, config={})
    assert not report.ok
    assert any(c.name == "pinned" and c.status == "fail" for c in report.checks)


def test_ipfs_verify_fails_on_bundle_root_tamper(tmp_path: Path) -> None:
    bundle_dir, prepared, _ = _make_bundle(tmp_path)
    client = FakeIpfsClient(tmp_path / "ipfs_store")
    adapter = IpfsStorageAdapter(client=client)
    receipt = adapter.publish(prepared, bundle_dir, config={})
    # Tamper with stored manifest root_hash.
    stored = client._store / receipt.content_id / "manifest.json"
    data = json.loads(stored.read_text())
    data["root_hash"] = "sha256:" + "0" * 64
    stored.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
    report = adapter.verify(receipt, config={})
    assert not report.ok
    assert any(c.name == "bundle_load" and c.status == "fail" for c in report.checks)


class FakeEvmClient:
    """Hermetic EVM stand-in: records anchor submissions and finality state."""

    def __init__(self) -> None:
        self._events: dict[str, Mapping[str, Any]] = {}
        self._finalized: set[str] = set()

    def submit_anchor(self, *, contract_address: str, bundle_root: str, storage_receipt_ref: str) -> Mapping[str, str]:
        tx_ref = "0x" + sha256_bytes(bundle_root.encode())[:32]
        block_ref = "0xblock" + sha256_bytes(storage_receipt_ref.encode())[:24]
        self._events[tx_ref] = {
            "bundle_root": bundle_root,
            "storage_receipt_ref": storage_receipt_ref,
            "block_ref": block_ref,
        }
        self._finalized.add(block_ref)
        return {"tx_ref": tx_ref, "block_ref": block_ref}

    def fetch_event(self, *, contract_address: str, tx_ref: str) -> Mapping[str, Any] | None:
        return self._events.get(tx_ref)

    def block_finalized(self, *, block_ref: str, required: int) -> bool:
        return block_ref in self._finalized


def _storage_receipt(bundle_root: str) -> StorageReceipt:
    return StorageReceipt(
        adapter="ipfs-cid-v1",
        network="ipfs",
        bundle_root=bundle_root,
        content_id="QmFake0000000001",
        retrieval={"kind": "cid", "value": "QmFake0000000001"},
        created_at="2026-01-01T00:00:00Z",
        publisher_ref="did:example:alice",
    )


def test_evm_anchor_submit_and_verify_round_trip(tmp_path: Path) -> None:
    _, prepared, _ = _make_bundle(tmp_path)
    family = EVM_FAMILIES["base-mainnet"]
    client = FakeEvmClient()
    adapter = EvmAnchorAdapter(family=family, client=client)
    anchor_ref = str(Ref(sha256_bytes(b"anchor-1")))
    receipt = adapter.anchor(
        _storage_receipt(prepared.bundle_root),
        anchor_ref=anchor_ref,
        config={"contract_address": "0xPopperPadAnchor"},
    )
    assert receipt.chain_id == "base-mainnet"
    assert receipt.event_name == "PopperPadBundleAnchored"
    assert receipt.finality["policy"] == "finalized"

    report = adapter.verify(receipt, config={})
    assert report.ok, [c.name for c in report.checks if c.status != "pass"]


def test_evm_verify_fails_when_event_missing(tmp_path: Path) -> None:
    _, prepared, _ = _make_bundle(tmp_path)
    family = EVM_FAMILIES["base-mainnet"]
    client = FakeEvmClient()
    adapter = EvmAnchorAdapter(family=family, client=client)
    anchor_ref = str(Ref(sha256_bytes(b"anchor-2")))
    receipt = adapter.anchor(
        _storage_receipt(prepared.bundle_root),
        anchor_ref=anchor_ref,
        config={"contract_address": "0xPopperPadAnchor"},
    )
    # Simulate event pruning.
    client._events.pop(receipt.tx_ref, None)
    report = adapter.verify(receipt, config={})
    assert not report.ok
    assert any(c.name == "event_present" and c.status == "fail" for c in report.checks)


def test_evm_verify_fails_when_event_bundle_root_mismatches(tmp_path: Path) -> None:
    _, prepared, _ = _make_bundle(tmp_path)
    family = EVM_FAMILIES["base-mainnet"]
    client = FakeEvmClient()
    adapter = EvmAnchorAdapter(family=family, client=client)
    anchor_ref = str(Ref(sha256_bytes(b"anchor-3")))
    receipt = adapter.anchor(
        _storage_receipt(prepared.bundle_root),
        anchor_ref=anchor_ref,
        config={"contract_address": "0xPopperPadAnchor"},
    )
    # Tamper: event records a different bundle_root.
    event = dict(client._events[receipt.tx_ref])
    event["bundle_root"] = "sha256:" + "f" * 64
    client._events[receipt.tx_ref] = event
    report = adapter.verify(receipt, config={})
    assert not report.ok
    assert any(c.name == "event_matches_bundle" and c.status == "fail" for c in report.checks)


def test_evm_verify_fails_when_block_not_finalized(tmp_path: Path) -> None:
    _, prepared, _ = _make_bundle(tmp_path)
    family = EVM_FAMILIES["base-mainnet"]
    client = FakeEvmClient()
    adapter = EvmAnchorAdapter(family=family, client=client)
    anchor_ref = str(Ref(sha256_bytes(b"anchor-4")))
    receipt = adapter.anchor(
        _storage_receipt(prepared.bundle_root),
        anchor_ref=anchor_ref,
        config={"contract_address": "0xPopperPadAnchor"},
    )
    # Simulate reorg: block no longer finalized.
    client._finalized.discard(receipt.block_ref)
    report = adapter.verify(receipt, config={})
    assert not report.ok
    assert any(c.name == "finality" and c.status == "fail" for c in report.checks)


def test_evm_anchor_rejects_invalid_anchor_ref(tmp_path: Path) -> None:
    _, prepared, _ = _make_bundle(tmp_path)
    family = EVM_FAMILIES["base-mainnet"]
    adapter = EvmAnchorAdapter(family=family, client=FakeEvmClient())
    with pytest.raises(Exception):
        adapter.anchor(
            _storage_receipt(prepared.bundle_root),
            anchor_ref="not-a-ref",
            config={},
        )
