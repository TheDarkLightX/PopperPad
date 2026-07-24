from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .codec import canonical_json_bytes, sha256_bytes
from .result import Reject
from .values import FrozenDict, JsonValue, freeze_json, thaw_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCHEMA = "popperpad/bundle/manifest/v1"


def _reject(code: str, field: str, reason: str) -> Reject:
    details = freeze_json({"field": field, "reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code=code, details=details)


def _owned_mapping(value: Mapping[str, Any] | FrozenDict[JsonValue]) -> FrozenDict[JsonValue]:
    if isinstance(value, FrozenDict):
        return value
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenDict):
        raise TypeError("bundle metadata must be object-shaped JSON")
    return frozen


def _owned_mapping_tuple(values: tuple[Mapping[str, Any] | FrozenDict[JsonValue], ...]) -> tuple[FrozenDict[JsonValue], ...]:
    return tuple(_owned_mapping(value) for value in values)


def _owned_refs(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    owned = tuple(str(value) for value in values)
    if not all(_REF_RE.fullmatch(value) for value in owned):
        raise ValueError(f"{field} must contain only sha256 refs")
    if owned != tuple(sorted(set(owned))):
        raise ValueError(f"{field} must be sorted and unique")
    return owned


@dataclass(frozen=True, slots=True)
class Bundle:
    bundle_id: str
    object_refs: tuple[str, ...]
    blob_refs: tuple[str, ...]
    entry_refs: tuple[str, ...]
    previous_bundle_refs: tuple[str, ...] = ()
    signatures: tuple[FrozenDict[JsonValue], ...] = ()
    storage_hints: tuple[FrozenDict[JsonValue], ...] = ()
    anchor_hints: tuple[FrozenDict[JsonValue], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.bundle_id, str) or not self.bundle_id:
            raise ValueError("bundle_id must be a non-empty string")
        object.__setattr__(self, "object_refs", _owned_refs(tuple(self.object_refs), field="object_refs"))
        object.__setattr__(self, "blob_refs", _owned_refs(tuple(self.blob_refs), field="blob_refs"))
        object.__setattr__(self, "entry_refs", _owned_refs(tuple(self.entry_refs), field="entry_refs"))
        object.__setattr__(
            self,
            "previous_bundle_refs",
            _owned_refs(tuple(self.previous_bundle_refs), field="previous_bundle_refs"),
        )
        object.__setattr__(self, "signatures", _owned_mapping_tuple(tuple(self.signatures)))
        object.__setattr__(self, "storage_hints", _owned_mapping_tuple(tuple(self.storage_hints)))
        object.__setattr__(self, "anchor_hints", _owned_mapping_tuple(tuple(self.anchor_hints)))
        if not set(self.entry_refs).issubset(set(self.object_refs)):
            raise ValueError("entry_refs must be a subset of object_refs")

    def content_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "object_refs": self.object_refs,
                "blob_refs": self.blob_refs,
                "entry_refs": self.entry_refs,
                "previous_bundle_refs": self.previous_bundle_refs,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


@dataclass(frozen=True, slots=True)
class Manifest:
    schema: str
    bundle_id: str
    created_at: str
    producer: FrozenDict[JsonValue]
    root_hash: str
    object_refs: tuple[str, ...]
    blob_refs: tuple[str, ...]
    entry_refs: tuple[str, ...]
    previous_bundle_refs: tuple[str, ...]
    signatures: tuple[FrozenDict[JsonValue], ...] = ()
    storage_hints: tuple[FrozenDict[JsonValue], ...] = ()
    anchor_hints: tuple[FrozenDict[JsonValue], ...] = ()

    def __post_init__(self) -> None:
        if self.schema != _SCHEMA:
            raise ValueError(f"manifest schema must be {_SCHEMA}")
        if not self.bundle_id:
            raise ValueError("manifest bundle_id must be non-empty")
        if not self.created_at:
            raise ValueError("manifest created_at must be non-empty")
        if not _REF_RE.fullmatch(self.root_hash):
            raise ValueError("manifest root_hash must be a sha256 ref")
        object.__setattr__(self, "producer", _owned_mapping(self.producer))
        object.__setattr__(self, "object_refs", _owned_refs(tuple(self.object_refs), field="object_refs"))
        object.__setattr__(self, "blob_refs", _owned_refs(tuple(self.blob_refs), field="blob_refs"))
        object.__setattr__(self, "entry_refs", _owned_refs(tuple(self.entry_refs), field="entry_refs"))
        object.__setattr__(
            self,
            "previous_bundle_refs",
            _owned_refs(tuple(self.previous_bundle_refs), field="previous_bundle_refs"),
        )
        object.__setattr__(self, "signatures", _owned_mapping_tuple(tuple(self.signatures)))
        object.__setattr__(self, "storage_hints", _owned_mapping_tuple(tuple(self.storage_hints)))
        object.__setattr__(self, "anchor_hints", _owned_mapping_tuple(tuple(self.anchor_hints)))
        if not set(self.entry_refs).issubset(set(self.object_refs)):
            raise ValueError("entry_refs must be a subset of object_refs")

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "bundle_id": self.bundle_id,
                "created_at": self.created_at,
                "producer": self.producer,
                "root_hash": self.root_hash,
                "object_refs": self.object_refs,
                "blob_refs": self.blob_refs,
                "entry_refs": self.entry_refs,
                "previous_bundle_refs": self.previous_bundle_refs,
                "signatures": self.signatures,
                "storage_hints": self.storage_hints,
                "anchor_hints": self.anchor_hints,
            }
        )
        assert isinstance(value, FrozenDict)
        return value

    def as_dict(self) -> dict[str, Any]:
        plain = thaw_json(self.as_json())
        assert isinstance(plain, dict)
        return plain


def content_root(bundle: Bundle) -> str:
    """Legacy v1 content root retained byte-for-byte for bundle compatibility."""

    return sha256_bytes(canonical_json_bytes(bundle.content_json()))


def build_manifest(
    bundle: Bundle,
    *,
    created_at: str,
    producer: Mapping[str, Any] | FrozenDict[JsonValue],
) -> Manifest:
    """Purely construct a manifest from complete explicit inputs."""

    if not created_at:
        raise ValueError("created_at must be explicit and non-empty")
    return Manifest(
        schema=_SCHEMA,
        bundle_id=bundle.bundle_id,
        created_at=created_at,
        producer=_owned_mapping(producer),
        root_hash=content_root(bundle),
        object_refs=bundle.object_refs,
        blob_refs=bundle.blob_refs,
        entry_refs=bundle.entry_refs,
        previous_bundle_refs=bundle.previous_bundle_refs,
        signatures=bundle.signatures,
        storage_hints=bundle.storage_hints,
        anchor_hints=bundle.anchor_hints,
    )


def manifest_root(manifest: Manifest) -> str:
    """Legacy v1 full-manifest root retained for existing chain adapters."""

    return sha256_bytes(canonical_json_bytes(manifest.as_json()))


def parse_manifest(raw: Mapping[str, Any]) -> Manifest | Reject:
    """Own and validate hostile manifest data without performing I/O."""

    try:
        producer = raw.get("producer", {})
        if not isinstance(producer, Mapping):
            return _reject("INVALID_MANIFEST", "producer", "must be an object")
        for field in ("object_refs", "blob_refs", "entry_refs", "previous_bundle_refs"):
            value = raw.get(field, ())
            if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
                return _reject("INVALID_MANIFEST", field, "must be an array")
        for field in ("signatures", "storage_hints", "anchor_hints"):
            value = raw.get(field, ())
            if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
                return _reject("INVALID_MANIFEST", field, "must be an array")
            if not all(isinstance(item, Mapping) for item in value):
                return _reject("INVALID_MANIFEST", field, "items must be objects")
        manifest = Manifest(
            schema=str(raw.get("schema", "")),
            bundle_id=str(raw.get("bundle_id", "")),
            created_at=str(raw.get("created_at", "")),
            producer=_owned_mapping(producer),
            root_hash=str(raw.get("root_hash", "")),
            object_refs=tuple(str(value) for value in raw.get("object_refs", ())),
            blob_refs=tuple(str(value) for value in raw.get("blob_refs", ())),
            entry_refs=tuple(str(value) for value in raw.get("entry_refs", ())),
            previous_bundle_refs=tuple(str(value) for value in raw.get("previous_bundle_refs", ())),
            signatures=_owned_mapping_tuple(tuple(raw.get("signatures", ()))),
            storage_hints=_owned_mapping_tuple(tuple(raw.get("storage_hints", ()))),
            anchor_hints=_owned_mapping_tuple(tuple(raw.get("anchor_hints", ()))),
        )
    except (TypeError, ValueError) as exc:
        return _reject("INVALID_MANIFEST", "manifest", str(exc))
    expected = sha256_bytes(
        canonical_json_bytes(
            freeze_json(
                {
                    "object_refs": manifest.object_refs,
                    "blob_refs": manifest.blob_refs,
                    "entry_refs": manifest.entry_refs,
                    "previous_bundle_refs": manifest.previous_bundle_refs,
                }
            )
        )
    )
    if manifest.root_hash != expected:
        return _reject("CONTENT_ROOT_MISMATCH", "root_hash", manifest.root_hash)
    return manifest
