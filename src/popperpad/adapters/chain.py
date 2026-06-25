from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..log import utc_now_iso
from ..refs import is_ref, require
from .base import (
    AdapterCapability,
    AnchorAdapter,
    AnchorReceipt,
    StorageReceipt,
    VerificationCheck,
    VerificationReport,
)


@dataclass(frozen=True)
class ChainFamily:
    """A chain family profile (EVM, Cosmos, etc.).

    Captures the finality model and contract surface so the anchor adapter can
    be configured per chain without hard-coding chain specifics.
    """

    family: str  # evm|cosmos|...
    chain_id: str
    contract_address: str
    event_name: str
    finality_policy: str
    finality_value: int
    native_payment: bool = False
    smart_contracts: bool = True


EVM_FAMILIES: dict[str, ChainFamily] = {
    "ethereum-mainnet": ChainFamily("evm", "ethereum-mainnet", "", "PopperPadBundleAnchored", "finalized", 64, native_payment=True),
    "base-mainnet": ChainFamily("evm", "base-mainnet", "", "PopperPadBundleAnchored", "finalized", 64, native_payment=True),
    "arbitrum-one": ChainFamily("evm", "arbitrum-one", "", "PopperPadBundleAnchored", "finality_l2_to_l1", 64, native_payment=True),
    "optimism-mainnet": ChainFamily("evm", "optimism-mainnet", "", "PopperPadBundleAnchored", "finality_l2_to_l1", 64, native_payment=True),
}


class EvmClient(Protocol):
    """Minimal EVM client surface the anchor adapter depends on."""

    def submit_anchor(self, *, contract_address: str, bundle_root: str, storage_receipt_ref: str) -> Mapping[str, str]: ...
    def fetch_event(self, *, contract_address: str, tx_ref: str) -> Mapping[str, Any] | None: ...
    def block_finalized(self, *, block_ref: str, required: int) -> bool: ...


class _NoEvmClient:
    def submit_anchor(self, *, contract_address: str, bundle_root: str, storage_receipt_ref: str) -> Mapping[str, str]:
        raise RuntimeError("no EVM client configured; inject one or install web3")

    def fetch_event(self, *, contract_address: str, tx_ref: str) -> Mapping[str, Any] | None:
        raise RuntimeError("no EVM client configured; inject one or install web3")

    def block_finalized(self, *, block_ref: str, required: int) -> bool:
        raise RuntimeError("no EVM client configured; inject one or install web3")


def _default_evm_client() -> EvmClient:
    try:
        from web3 import Web3  # type: ignore  # noqa: F401
    except ImportError:
        return _NoEvmClient()
    return _Web3Client()


class _Web3Client:
    def __init__(self) -> None:
        from web3 import Web3  # type: ignore
        self._w3 = Web3()

    def submit_anchor(self, *, contract_address: str, bundle_root: str, storage_receipt_ref: str) -> Mapping[str, str]:
        raise NotImplementedError("live EVM submission wiring is adapter-specific; inject a client")

    def fetch_event(self, *, contract_address: str, tx_ref: str) -> Mapping[str, Any] | None:
        raise NotImplementedError("live EVM event fetch wiring is adapter-specific; inject a client")

    def block_finalized(self, *, block_ref: str, required: int) -> bool:
        raise NotImplementedError("live EVM finality wiring is adapter-specific; inject a client")


class EvmAnchorAdapter(AnchorAdapter):
    """EVM chain anchor adapter.

    Submits ``bundle_root`` + ``storage_receipt_ref`` to a PopperPad anchor
    contract and records an on-chain event receipt. The client is injectable so
    tests run hermetically; live wiring is adapter-specific and out of scope for
    the MVP. See ``docs/blockchain-anchor-spec.md`` contract surface section.
    """

    adapter_id = "evm-anchor-v1"
    kind = "anchor"

    def __init__(self, family: ChainFamily, client: EvmClient | None = None) -> None:
        self._family = family
        self._client = client

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            content_addressed=True,
            append_only=True,
            native_timestamp=True,
            native_payment=self._family.native_payment,
            smart_contracts=self._family.smart_contracts,
        )

    def _resolve_client(self, config: Mapping[str, Any]) -> EvmClient:
        if self._client is not None:
            return self._client
        injected = config.get("client")
        if injected is not None:
            return injected  # type: ignore[return-value]
        return _default_evm_client()

    def anchor(self, storage_receipt: StorageReceipt, *, anchor_ref: str, config: Mapping[str, Any]) -> AnchorReceipt:
        require(is_ref(anchor_ref), "anchor_ref must be a sha256 ref")
        client = self._resolve_client(config)
        contract = str(config.get("contract_address", self._family.contract_address))
        result = client.submit_anchor(
            contract_address=contract,
            bundle_root=storage_receipt.bundle_root,
            storage_receipt_ref=storage_receipt.content_id,
        )
        return AnchorReceipt(
            adapter=self.adapter_id,
            chain_id=self._family.chain_id,
            bundle_root=storage_receipt.bundle_root,
            anchor_ref=anchor_ref,
            storage_receipt_ref=storage_receipt.content_id,
            tx_ref=str(result.get("tx_ref", "")),
            block_ref=str(result.get("block_ref", "")),
            contract_ref=contract,
            event_name=self._family.event_name,
            finality={"policy": self._family.finality_policy, "value": self._family.finality_value},
            created_at=utc_now_iso(),
        )

    def verify(self, receipt: AnchorReceipt, *, config: Mapping[str, Any]) -> VerificationReport:
        checks: list[VerificationCheck] = []
        try:
            client = self._resolve_client(config)
            event = client.fetch_event(contract_address=receipt.contract_ref, tx_ref=receipt.tx_ref)
            checks.append(VerificationCheck("event_present", "pass" if event is not None else "fail"))
            event_matches = (
                event is not None
                and str(event.get("bundle_root")) == receipt.bundle_root
                and str(event.get("storage_receipt_ref")) == receipt.storage_receipt_ref
            )
            checks.append(VerificationCheck("event_matches_bundle", "pass" if event_matches else "fail"))
            finalized = client.block_finalized(
                block_ref=receipt.block_ref, required=int(receipt.finality.get("value", 0))
            )
            checks.append(VerificationCheck("finality", "pass" if finalized else "fail"))
            return _report(receipt.bundle_root, checks, fail=not (event_matches and finalized))
        except Exception as e:
            checks.append(VerificationCheck("chain_lookup", "fail", str(e)))
            return _report(receipt.bundle_root, checks, fail=True)


def _report(target_ref: str, checks: list[VerificationCheck], *, fail: bool) -> VerificationReport:
    return VerificationReport(
        target_ref=target_ref,
        status="fail" if fail else "pass",
        checks=checks,
        verified_at=utc_now_iso(),
    )
