from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..canonical import canonical_json_bytes, sha256_bytes, stable_sha256
from ..log import utc_now_iso
from ..refs import Ref, ValidationError, is_ref, require
from ..schemas import SCHEMA_BUNDLE_MANIFEST_V1


def _freeze_metadata(value: Any, *, path: str = "$") -> Any:
    """Own legacy JSON metadata without narrowing its finite-float domain."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        require(isfinite(value), f"non-finite metadata number at {path}")
        return value
    if isinstance(value, Mapping):
        owned: dict[str, Any] = {}
        for key, child in value.items():
            require(isinstance(key, str), f"metadata key at {path} must be a string")
            owned[key] = _freeze_metadata(child, path=f"{path}.{key}")
        return MappingProxyType(owned)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata(child, path=f"{path}[{index}]") for index, child in enumerate(value))
    raise TypeError(f"unsupported metadata value at {path}: {type(value).__name__}")


def _freeze_metadata_mapping(value: Mapping[str, Any], *, path: str) -> Mapping[str, Any]:
    frozen = _freeze_metadata(value, path=path)
    require(isinstance(frozen, Mapping), f"metadata at {path} must be an object")
    return frozen


def _thaw_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_metadata(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_metadata(child) for child in value]
    return value


def _sorted_refs(refs: Any) -> tuple[Ref, ...]:
    require(isinstance(refs, (list, tuple)), "refs must be a list or tuple")
    parsed = tuple(Ref(str(r)) for r in refs)
    require(parsed == tuple(sorted(parsed)), "refs must be sorted and unique")
    return parsed


@dataclass(frozen=True)
class Bundle:
    """A canonical PopperPad publication bundle.

    Invalid states are unrepresentable: refs are validated and must be sorted
    and unique at construction time. The content root (``root_hash``) is a pure
    function of ``object_refs``, ``blob_refs``, ``entry_refs`` and
    ``previous_bundle_refs``; the ``bundle_root`` is the canonical hash of the
    full manifest.
    """

    bundle_id: str
    object_refs: tuple[Ref, ...]
    blob_refs: tuple[Ref, ...]
    entry_refs: tuple[Ref, ...]
    previous_bundle_refs: tuple[Ref, ...] = ()
    signatures: tuple[Mapping[str, Any], ...] = ()
    storage_hints: tuple[Mapping[str, Any], ...] = ()
    anchor_hints: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        require(isinstance(self.bundle_id, str) and self.bundle_id, "bundle_id must be a non-empty string")
        object.__setattr__(self, "object_refs", _sorted_refs(self.object_refs))
        object.__setattr__(self, "blob_refs", _sorted_refs(self.blob_refs))
        object.__setattr__(self, "entry_refs", _sorted_refs(self.entry_refs))
        object.__setattr__(self, "previous_bundle_refs", _sorted_refs(self.previous_bundle_refs))
        object.__setattr__(
            self,
            "signatures",
            tuple(
                _freeze_metadata_mapping(value, path=f"$.signatures[{index}]")
                for index, value in enumerate(self.signatures)
            ),
        )
        object.__setattr__(
            self,
            "storage_hints",
            tuple(
                _freeze_metadata_mapping(value, path=f"$.storage_hints[{index}]")
                for index, value in enumerate(self.storage_hints)
            ),
        )
        object.__setattr__(
            self,
            "anchor_hints",
            tuple(
                _freeze_metadata_mapping(value, path=f"$.anchor_hints[{index}]")
                for index, value in enumerate(self.anchor_hints)
            ),
        )

    def content(self) -> dict[str, Any]:
        return {
            "object_refs": [str(r) for r in self.object_refs],
            "blob_refs": [str(r) for r in self.blob_refs],
            "entry_refs": [str(r) for r in self.entry_refs],
            "previous_bundle_refs": [str(r) for r in self.previous_bundle_refs],
        }


@dataclass(frozen=True)
class Manifest:
    schema: str
    bundle_id: str
    created_at: str
    producer: Mapping[str, Any]
    root_hash: str
    object_refs: tuple[str, ...]
    blob_refs: tuple[str, ...]
    entry_refs: tuple[str, ...]
    previous_bundle_refs: tuple[str, ...]
    signatures: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    storage_hints: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    anchor_hints: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "producer", _freeze_metadata_mapping(self.producer, path="$.producer"))
        for field_name in ("object_refs", "blob_refs", "entry_refs", "previous_bundle_refs"):
            values = getattr(self, field_name)
            require(
                isinstance(values, (list, tuple)) and all(isinstance(value, str) for value in values),
                f"manifest {field_name} must contain strings",
            )
            object.__setattr__(self, field_name, tuple(values))
        for field_name in ("signatures", "storage_hints", "anchor_hints"):
            values = getattr(self, field_name)
            require(isinstance(values, (list, tuple)), f"manifest {field_name} must be an array")
            object.__setattr__(
                self,
                field_name,
                tuple(
                    _freeze_metadata_mapping(value, path=f"$.{field_name}[{index}]")
                    for index, value in enumerate(values)
                ),
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "bundle_id": self.bundle_id,
            "created_at": self.created_at,
            "producer": _thaw_metadata(self.producer),
            "root_hash": self.root_hash,
            "object_refs": list(self.object_refs),
            "blob_refs": list(self.blob_refs),
            "entry_refs": list(self.entry_refs),
            "previous_bundle_refs": list(self.previous_bundle_refs),
            "signatures": [_thaw_metadata(value) for value in self.signatures],
            "storage_hints": [_thaw_metadata(value) for value in self.storage_hints],
            "anchor_hints": [_thaw_metadata(value) for value in self.anchor_hints],
        }


def build_manifest(
    bundle: Bundle,
    *,
    created_at: str | None = None,
    producer: Mapping[str, Any] | None = None,
) -> Manifest:
    """Build the canonical manifest for a bundle, computing its content root."""
    content = bundle.content()
    return Manifest(
        schema=SCHEMA_BUNDLE_MANIFEST_V1,
        bundle_id=bundle.bundle_id,
        created_at=created_at or utc_now_iso(),
        producer=producer if producer else {"name": "PopperPad", "version": "0.1.0"},
        root_hash=stable_sha256(content),
        object_refs=content["object_refs"],
        blob_refs=content["blob_refs"],
        entry_refs=content["entry_refs"],
        previous_bundle_refs=content["previous_bundle_refs"],
        signatures=bundle.signatures,
        storage_hints=bundle.storage_hints,
        anchor_hints=bundle.anchor_hints,
    )


def bundle_root(manifest: Manifest) -> str:
    """The canonical hash of the manifest (what gets anchored on chains)."""
    return stable_sha256(manifest.as_dict())


def _hex_parts(ref: str) -> tuple[str, str]:
    hex_ = ref.split(":", 1)[1]
    return hex_[:2], hex_[2:]


def export_bundle(
    bundle: Bundle,
    out_dir: Path,
    *,
    objects: Mapping[str, bytes],
    blobs: Mapping[str, bytes],
    created_at: str | None = None,
    producer: Mapping[str, Any] | None = None,
) -> Manifest:
    """Write a canonical bundle directory layout and return its manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(bundle, created_at=created_at, producer=producer)
    _write_objects(out, bundle.object_refs, objects)
    _write_blobs(out, bundle.blob_refs, blobs)
    _write_indexes(out, bundle)
    (out / "manifest.json").write_bytes(canonical_json_bytes(manifest.as_dict()))
    return manifest


def _write_objects(out: Path, refs: tuple[Ref, ...], objects: Mapping[str, bytes]) -> None:
    base = out / "objects" / "sha256"
    for ref in refs:
        payload = objects.get(str(ref))
        require(payload is not None, f"missing object bytes for {ref}")
        require(sha256_bytes(payload) == str(ref), f"object bytes do not hash to {ref}")
        prefix, rest = _hex_parts(str(ref))
        target = base / prefix / f"sha256-{prefix}{rest}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _write_blobs(out: Path, refs: tuple[Ref, ...], blobs: Mapping[str, bytes]) -> None:
    base = out / "blobs" / "sha256"
    for ref in refs:
        payload = blobs.get(str(ref))
        require(payload is not None, f"missing blob bytes for {ref}")
        require(sha256_bytes(payload) == str(ref), f"blob bytes do not hash to {ref}")
        prefix, rest = _hex_parts(str(ref))
        target = base / prefix / f"sha256-{prefix}{rest}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _write_indexes(out: Path, bundle: Bundle) -> None:
    index_dir = out / "indexes"
    index_dir.mkdir(parents=True, exist_ok=True)
    refs_index = {"object_refs": [str(r) for r in bundle.object_refs], "blob_refs": [str(r) for r in bundle.blob_refs]}
    (index_dir / "refs.json").write_bytes(canonical_json_bytes(refs_index))


@dataclass(frozen=True)
class LoadedBundle:
    manifest: Manifest
    objects: dict[str, bytes]
    blobs: dict[str, bytes]


def load_bundle_dir(bundle_dir: Path) -> LoadedBundle:
    """Load a bundle directory, verifying every object/blob hash against its ref."""
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "manifest.json"
    require(manifest_path.exists(), "manifest.json not found")
    manifest = _parse_manifest(json.loads(manifest_path.read_bytes()))
    objects = _load_payloads(bundle_dir / "objects" / "sha256", manifest.object_refs, ".json")
    blobs = _load_payloads(bundle_dir / "blobs" / "sha256", manifest.blob_refs, "")
    _verify_content_root(manifest)
    return LoadedBundle(manifest=manifest, objects=objects, blobs=blobs)


def _parse_manifest(data: Mapping[str, Any]) -> Manifest:
    require(str(data.get("schema")) == SCHEMA_BUNDLE_MANIFEST_V1, f"manifest schema must be {SCHEMA_BUNDLE_MANIFEST_V1}")
    return Manifest(
        schema=str(data["schema"]),
        bundle_id=str(data["bundle_id"]),
        created_at=str(data["created_at"]),
        producer=dict(data.get("producer", {})),
        root_hash=str(data["root_hash"]),
        object_refs=list(data["object_refs"]),
        blob_refs=list(data["blob_refs"]),
        entry_refs=list(data["entry_refs"]),
        previous_bundle_refs=list(data.get("previous_bundle_refs", [])),
        signatures=list(data.get("signatures", [])),
        storage_hints=list(data.get("storage_hints", [])),
        anchor_hints=list(data.get("anchor_hints", [])),
    )


def _load_payloads(base: Path, refs: list[str], suffix: str) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for ref in refs:
        prefix, rest = _hex_parts(ref)
        path = base / prefix / f"sha256-{prefix}{rest}{suffix}"
        require(path.exists(), f"missing payload file for {ref}")
        data = path.read_bytes()
        require(sha256_bytes(data) == ref, f"payload hash mismatch for {ref}")
        payloads[ref] = data
    return payloads


def _verify_content_root(manifest: Manifest) -> None:
    content = {
        "object_refs": manifest.object_refs,
        "blob_refs": manifest.blob_refs,
        "entry_refs": manifest.entry_refs,
        "previous_bundle_refs": manifest.previous_bundle_refs,
    }
    require(stable_sha256(content) == manifest.root_hash, "manifest root_hash does not match content")
