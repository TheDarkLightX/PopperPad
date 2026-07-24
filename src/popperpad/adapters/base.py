from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ..core.values import FrozenDict, JsonValue, freeze_json, thaw_json


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


def _freeze_mapping(value: Mapping[str, Any] | FrozenDict[JsonValue]) -> FrozenDict[JsonValue]:
    if isinstance(value, FrozenDict):
        return value
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenDict):
        raise TypeError("expected object-shaped immutable value")
    return frozen


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    name: str
    status: str  # pass|fail|skip
    detail: str = ""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    target_ref: str
    status: str  # pass|fail
    checks: tuple[VerificationCheck, ...]
    verified_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))

    @property
    def ok(self) -> bool:
        return self.status == CheckStatus.PASS.value


@dataclass(frozen=True, slots=True)
class PreparedBundle:
    manifest_ref: str
    bundle_root: str
    object_count: int
    blob_count: int
    byte_size: int
    canonicalization: str = "popperpad-json-int-v2"


@dataclass(frozen=True, slots=True)
class StorageReceipt:
    adapter: str
    network: str
    bundle_root: str
    content_id: str
    retrieval: FrozenDict[JsonValue]
    created_at: str
    publisher_ref: str = ""
    signature: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieval", _freeze_mapping(self.retrieval))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "popperpad/adapter/storage-receipt/v1",
            "adapter": self.adapter,
            "network": self.network,
            "bundle_root": self.bundle_root,
            "content_id": self.content_id,
            "retrieval": thaw_json(self.retrieval),
            "created_at": self.created_at,
            "publisher_ref": self.publisher_ref,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
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
    finality: FrozenDict[JsonValue] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "finality", _freeze_mapping(self.finality))

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
            "finality": thaw_json(self.finality),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ImportReport:
    bundle_root: str
    imported_object_refs: tuple[str, ...]
    imported_blob_refs: tuple[str, ...]
    skipped_refs: tuple[str, ...]
    status: str  # imported|partial|rejected
    checks: tuple[VerificationCheck, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "imported_object_refs", tuple(self.imported_object_refs))
        object.__setattr__(self, "imported_blob_refs", tuple(self.imported_blob_refs))
        object.__setattr__(self, "skipped_refs", tuple(self.skipped_refs))
        object.__setattr__(self, "checks", tuple(self.checks))


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Immutable local trust policy applied when importing bundles."""

    require_signatures: bool = True
    require_bundle_root_match: bool = True
    accept_adapters: tuple[str, ...] = ()
    require_anchors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "accept_adapters", tuple(self.accept_adapters))
        object.__setattr__(self, "require_anchors", tuple(self.require_anchors))


@dataclass(frozen=True, slots=True)
class AdapterCapability:
    content_addressed: bool = False
    append_only: bool = False
    native_timestamp: bool = False
    native_payment: bool = False
    native_governance: bool = False
    smart_contracts: bool = False


class Adapter(ABC):
    """Common base for storage and anchor shell adapters."""

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
