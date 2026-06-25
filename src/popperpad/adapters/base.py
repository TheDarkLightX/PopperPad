from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ..refs import Ref, is_ref, require, require_str


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    status: str  # pass|fail|skip
    detail: str = ""


@dataclass(frozen=True)
class VerificationReport:
    target_ref: str
    status: str  # pass|fail
    checks: list[VerificationCheck]
    verified_at: str

    @property
    def ok(self) -> bool:
        return self.status == CheckStatus.PASS.value


@dataclass(frozen=True)
class PreparedBundle:
    manifest_ref: str
    bundle_root: str
    object_count: int
    blob_count: int
    byte_size: int
    canonicalization: str = "popperpad-json-c14n-v1"


@dataclass(frozen=True)
class StorageReceipt:
    adapter: str
    network: str
    bundle_root: str
    content_id: str
    retrieval: Mapping[str, Any]
    created_at: str
    publisher_ref: str = ""
    signature: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "popperpad/adapter/storage-receipt/v1",
            "adapter": self.adapter,
            "network": self.network,
            "bundle_root": self.bundle_root,
            "content_id": self.content_id,
            "retrieval": dict(self.retrieval),
            "created_at": self.created_at,
            "publisher_ref": self.publisher_ref,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class AnchorReceipt:
    adapter: str
    chain_id: str
    bundle_root: str
    storage_receipt_ref: str
    tx_ref: str
    block_ref: str
    contract_ref: str
    event_name: str
    created_at: str
    anchor_ref: str = ""
    finality: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "popperpad/adapter/anchor-receipt/v1",
            "adapter": self.adapter,
            "chain_id": self.chain_id,
            "bundle_root": self.bundle_root,
            "anchor_ref": self.anchor_ref,
            "storage_receipt_ref": self.storage_receipt_ref,
            "tx_ref": self.tx_ref,
            "block_ref": self.block_ref,
            "contract_ref": self.contract_ref,
            "event_name": self.event_name,
            "finality": dict(self.finality),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ImportReport:
    bundle_root: str
    imported_object_refs: list[str]
    imported_blob_refs: list[str]
    skipped_refs: list[str]
    status: str  # imported|partial|rejected
    checks: list[VerificationCheck]


@dataclass(frozen=True)
class TrustPolicy:
    """Local trust policy applied when importing bundles.

    Fail-closed by default: required signatures must be present and bundle roots
    must match. ``require_signatures`` enforces that at least one signature is
    present on the manifest.
    """

    require_signatures: bool = True
    require_bundle_root_match: bool = True
    accept_adapters: tuple[str, ...] = ()
    require_anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterCapability:
    content_addressed: bool = False
    append_only: bool = False
    native_timestamp: bool = False
    native_payment: bool = False
    native_governance: bool = False
    smart_contracts: bool = False


class Adapter(ABC):
    """Common base for storage and anchor adapters."""

    adapter_id: str = ""
    kind: str = ""

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapability: ...


class StorageAdapter(Adapter):
    kind = "storage"

    @abstractmethod
    def publish(self, prepared: PreparedBundle, bundle_dir: Path, *, config: Mapping[str, Any]) -> StorageReceipt: ...

    @abstractmethod
    def retrieve(self, receipt: StorageReceipt, *, config: Mapping[str, Any]) -> Path: ...

    @abstractmethod
    def verify(self, receipt: StorageReceipt, *, config: Mapping[str, Any]) -> VerificationReport: ...


class AnchorAdapter(Adapter):
    kind = "anchor"

    @abstractmethod
    def anchor(self, storage_receipt: StorageReceipt, *, anchor_ref: str, config: Mapping[str, Any]) -> AnchorReceipt: ...

    @abstractmethod
    def verify(self, receipt: AnchorReceipt, *, config: Mapping[str, Any]) -> VerificationReport: ...
