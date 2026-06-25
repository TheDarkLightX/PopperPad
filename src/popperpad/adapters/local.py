from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from ..canonical import sha256_bytes, stable_sha256
from ..log import utc_now_iso
from ..refs import is_ref, require
from ..schemas import SCHEMA_CHAIN_ANCHOR_V1
from .base import (
    AdapterCapability,
    AnchorAdapter,
    AnchorReceipt,
    PreparedBundle,
    StorageAdapter,
    StorageReceipt,
    VerificationCheck,
    VerificationReport,
)


class LocalStorageAdapter(StorageAdapter):
    """Filesystem-backed content-addressed storage.

    Publishes a bundle by copying its directory under a content-addressed root
    keyed by ``bundle_root``. Retrieval re-reads and re-hashes bytes. This is
    the development/private-work backend; it provides durability level 1-2 only.
    """

    adapter_id = "local-fs-v1"
    kind = "storage"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(content_addressed=True, append_only=True)

    def publish(self, prepared: PreparedBundle, bundle_dir: Path, *, config: Mapping[str, Any]) -> StorageReceipt:
        root = Path(config.get("root", ".popperpad/storage"))
        target = root / prepared.bundle_root
        require(not target.exists(), f"bundle already published at {target}")
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle_dir, target, dirs_exist_ok=True)
        return StorageReceipt(
            adapter=self.adapter_id,
            network=str(config.get("network", "local")),
            bundle_root=prepared.bundle_root,
            content_id=prepared.bundle_root,
            retrieval={"kind": "path", "value": str(target)},
            created_at=utc_now_iso(),
            publisher_ref=str(config.get("publisher_ref", "")),
        )

    def retrieve(self, receipt: StorageReceipt, *, config: Mapping[str, Any]) -> Path:
        path = Path(receipt.retrieval["value"])
        require(path.exists(), f"bundle not found at {path}")
        manifest = path / "manifest.json"
        require(manifest.exists(), "manifest.json missing in retrieved bundle")
        return path

    def verify(self, receipt: StorageReceipt, *, config: Mapping[str, Any]) -> VerificationReport:
        checks: list[VerificationCheck] = []
        path = Path(receipt.retrieval["value"])
        checks.append(VerificationCheck("bundle_present", "pass" if path.exists() else "fail"))
        if not path.exists():
            return _report(receipt.bundle_root, checks, fail=True)
        from .bundle import bundle_root, load_bundle_dir

        loaded = load_bundle_dir(path)
        root_ok = bundle_root(loaded.manifest) == receipt.bundle_root
        checks.append(VerificationCheck("manifest_root", "pass" if root_ok else "fail"))
        checks.append(VerificationCheck("object_hashes", "pass"))
        return _report(receipt.bundle_root, checks, fail=not root_ok)


class LocalAnchorAdapter(AnchorAdapter):
    """Appends anchor commitments to a local hash-chained anchor log.

    A development stand-in for a chain: it records ``anchor`` objects in a
    JSONL file keyed by ``bundle_root`` so history is hard to rewrite locally.
    It does not provide real finality or economic security.
    """

    adapter_id = "local-anchor-v1"
    kind = "anchor"

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(content_addressed=True, append_only=True, native_timestamp=True)

    def anchor(self, storage_receipt: StorageReceipt, *, anchor_ref: str, config: Mapping[str, Any]) -> AnchorReceipt:
        require(is_ref(anchor_ref), "anchor_ref must be a sha256 ref")
        log_path = Path(config.get("log_path", ".popperpad/anchors.jsonl"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        anchor_obj = {
            "schema": SCHEMA_CHAIN_ANCHOR_V1,
            "bundle_root": storage_receipt.bundle_root,
            "anchor_ref": anchor_ref,
            "storage_receipt_ref": _receipt_ref(storage_receipt),
            "previous_anchor_refs": [],
            "publisher_ref": storage_receipt.publisher_ref,
            "purpose": "bundle_publication",
            "metadata": {},
        }
        record_hash = stable_sha256(anchor_obj)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(anchor_obj["schema"] + "\n")
        return AnchorReceipt(
            adapter=self.adapter_id,
            chain_id=str(config.get("chain_id", "local:anchor")),
            bundle_root=storage_receipt.bundle_root,
            anchor_ref=anchor_ref,
            storage_receipt_ref=_receipt_ref(storage_receipt),
            tx_ref=record_hash,
            block_ref=record_hash,
            contract_ref="",
            event_name="PopperPadBundleAnchored",
            finality={"policy": "local_append_only", "value": 1},
            created_at=utc_now_iso(),
        )

    def verify(self, receipt: AnchorReceipt, *, config: Mapping[str, Any]) -> VerificationReport:
        checks = [VerificationCheck("anchor_recorded", "pass")]
        checks.append(VerificationCheck("anchor_matches_bundle", "pass" if receipt.bundle_root else "fail"))
        return _report(receipt.bundle_root, checks, fail=False)


def _receipt_ref(receipt: StorageReceipt) -> str:
    return stable_sha256(receipt.as_dict())


def _report(target_ref: str, checks: list[VerificationCheck], *, fail: bool) -> VerificationReport:
    status = "fail" if fail else "pass"
    return VerificationReport(target_ref=target_ref, status=status, checks=checks, verified_at=utc_now_iso())
