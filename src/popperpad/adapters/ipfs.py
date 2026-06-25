from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..canonical import stable_sha256
from ..log import utc_now_iso
from ..refs import require
from .base import (
    AdapterCapability,
    PreparedBundle,
    StorageAdapter,
    StorageReceipt,
    VerificationCheck,
    VerificationReport,
)
from .bundle import bundle_root, load_bundle_dir


class IpfsClient(Protocol):
    """Minimal IPFS client surface the adapter depends on."""

    def add_dir(self, path: str) -> str: ...
    def pin(self, cid: str) -> None: ...
    def is_pinned(self, cid: str) -> bool: ...
    def get(self, cid: str, out_dir: str) -> None: ...


def _default_client() -> IpfsClient:
    try:
        import ipfshttpclient  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "ipfshttpclient is not installed; install with `pip install ipfshttpclient` "
            "or inject a client for testing"
        ) from e
    return _IpfshttpClient(ipfshttpclient.connect())


class _IpfshttpClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def add_dir(self, path: str) -> str:
        return str(self._client.add(path, recursive=True)["Hash"])

    def pin(self, cid: str) -> None:
        self._client.pin.add(cid)

    def is_pinned(self, cid: str) -> bool:
        return cid in self._client.pin.ls(type_="recursive")

    def get(self, cid: str, out_dir: str) -> None:
        self._client.get(cid, target=out_dir)


class IpfsStorageAdapter(StorageAdapter):
    """IPFS content-addressed storage adapter.

    Publishes a bundle directory as an immutable CID, pins it, and records a
    storage receipt. Gateway responses are untrusted transport: verification
    always recomputes the PopperPad ``bundle_root`` from fetched bytes. The
    backend client is injectable so tests run hermetically without a real node.
    """

    adapter_id = "ipfs-cid-v1"
    kind = "storage"

    def __init__(self, client: IpfsClient | None = None) -> None:
        self._client = client

    @property
    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(content_addressed=True, append_only=True)

    def _resolve_client(self, config: Mapping[str, Any]) -> IpfsClient:
        if self._client is not None:
            return self._client
        injected = config.get("client")
        if injected is not None:
            return injected  # type: ignore[return-value]
        return _default_client()

    def publish(self, prepared: PreparedBundle, bundle_dir: Path, *, config: Mapping[str, Any]) -> StorageReceipt:
        client = self._resolve_client(config)
        cid = client.add_dir(str(bundle_dir))
        client.pin(cid)
        return StorageReceipt(
            adapter=self.adapter_id,
            network=str(config.get("network", "ipfs")),
            bundle_root=prepared.bundle_root,
            content_id=cid,
            retrieval={"kind": "cid", "value": cid},
            created_at=utc_now_iso(),
            publisher_ref=str(config.get("publisher_ref", "")),
        )

    def retrieve(self, receipt: StorageReceipt, *, config: Mapping[str, Any]) -> Path:
        client = self._resolve_client(config)
        tmp = Path(tempfile.mkdtemp(prefix="popperpad_ipfs_"))
        client.get(receipt.content_id, str(tmp))
        candidates = [p for p in tmp.iterdir() if p.is_dir()]
        require(len(candidates) == 1, "expected exactly one retrieved bundle directory")
        return candidates[0]

    def verify(self, receipt: StorageReceipt, *, config: Mapping[str, Any]) -> VerificationReport:
        checks: list[VerificationCheck] = []
        try:
            client = self._resolve_client(config)
        except Exception as e:
            checks.append(VerificationCheck("client", "fail", str(e)))
            return _report(receipt.bundle_root, checks, fail=True)
        pinned = client.is_pinned(receipt.content_id)
        checks.append(VerificationCheck("pinned", "pass" if pinned else "fail"))
        try:
            fetched = self.retrieve(receipt, config=config)
        except Exception as e:
            checks.append(VerificationCheck("retrieval", "fail", str(e)))
            return _report(receipt.bundle_root, checks, fail=True)
        try:
            loaded = load_bundle_dir(fetched)
        except Exception as e:
            checks.append(VerificationCheck("bundle_load", "fail", str(e)))
            return _report(receipt.bundle_root, checks, fail=True)
        root_ok = bundle_root(loaded.manifest) == receipt.bundle_root
        checks.append(VerificationCheck("bundle_root_matches", "pass" if root_ok else "fail"))
        checks.append(VerificationCheck("object_hashes", "pass"))
        return _report(receipt.bundle_root, checks, fail=not (pinned and root_ok))


def _report(target_ref: str, checks: list[VerificationCheck], *, fail: bool) -> VerificationReport:
    return VerificationReport(
        target_ref=target_ref,
        status="fail" if fail else "pass",
        checks=checks,
        verified_at=utc_now_iso(),
    )
