from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .base import Adapter, AdapterCapability
from .chain import EVM_FAMILIES, EvmAnchorAdapter
from .ipfs import IpfsStorageAdapter
from .local import LocalAnchorAdapter, LocalStorageAdapter
from .tau import TauNetAnchorAdapter


@dataclass(frozen=True)
class RegistryEntry:
    adapter_id: str
    kind: str  # storage|anchor
    capabilities: AdapterCapability
    trust_notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "popperpad/adapter/registry-entry/v1",
            "adapter_id": self.adapter_id,
            "kind": self.kind,
            "capabilities": {
                "content_addressed": self.capabilities.content_addressed,
                "append_only": self.capabilities.append_only,
                "native_timestamp": self.capabilities.native_timestamp,
                "native_payment": self.capabilities.native_payment,
                "native_governance": self.capabilities.native_governance,
                "smart_contracts": self.capabilities.smart_contracts,
            },
            "trust_notes": list(self.trust_notes),
        }


class AdapterRegistry:
    """Capability-indexed adapter registry.

    Adapters are registered by capability, not by hype. Lookup is by id; the
    registry refuses to return adapters that are not explicitly registered.
    """

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}
        self._adapters: dict[str, Adapter] = {}

    def register(self, entry: RegistryEntry, adapter: Adapter) -> None:
        if entry.adapter_id in self._entries:
            raise ValueError(f"adapter already registered: {entry.adapter_id}")
        self._entries[entry.adapter_id] = entry
        self._adapters[entry.adapter_id] = adapter

    def entry(self, adapter_id: str) -> RegistryEntry:
        if adapter_id not in self._entries:
            raise KeyError(f"unknown adapter: {adapter_id}")
        return self._entries[adapter_id]

    def adapter(self, adapter_id: str) -> Adapter:
        if adapter_id not in self._adapters:
            raise KeyError(f"unknown adapter: {adapter_id}")
        return self._adapters[adapter_id]

    def by_kind(self, kind: str) -> list[RegistryEntry]:
        return [entry for entry in self._entries.values() if entry.kind == kind]

    def all_entries(self) -> list[RegistryEntry]:
        return list(self._entries.values())


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(
        RegistryEntry(
            "local-fs-v1",
            "storage",
            LocalStorageAdapter().capabilities,
            trust_notes=("Local filesystem only; no replication.", "Hash verification is strong."),
        ),
        LocalStorageAdapter(),
    )
    registry.register(
        RegistryEntry(
            "local-anchor-v1",
            "anchor",
            LocalAnchorAdapter().capabilities,
            trust_notes=("Development stand-in for a chain.", "No real finality or economic security."),
        ),
        LocalAnchorAdapter(),
    )
    registry.register(
        RegistryEntry(
            "ipfs-cid-v1",
            "storage",
            IpfsStorageAdapter().capabilities,
            trust_notes=("Content-addressed by CID.", "Gateway responses are untrusted transport; verify recomputes bundle_root."),
        ),
        IpfsStorageAdapter(),
    )
    for family_id, family in EVM_FAMILIES.items():
        registry.register(
            RegistryEntry(
                f"evm-anchor-{family_id}",
                "anchor",
                EvmAnchorAdapter(family).capabilities,
                trust_notes=(f"EVM family: {family.family}.", "Live submission requires an injected EvmClient."),
            ),
            EvmAnchorAdapter(family),
        )
    registry.register(
        RegistryEntry(
            "tau-net-v1",
            "anchor",
            TauNetAnchorAdapter().capabilities,
            trust_notes=("Tau Net API not yet stable.", "Fail-closed policy boundary; live anchoring deferred."),
        ),
        TauNetAnchorAdapter(),
    )
    return registry
