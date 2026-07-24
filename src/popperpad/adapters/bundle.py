from __future__ import annotations

import json
from collections.abc import Iterator, Mapping as MappingABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..canonical import canonical_json_bytes, sha256_bytes
from ..core.bundle import (
    Bundle,
    Manifest,
    build_manifest as build_manifest_core,
    content_root,
    manifest_root,
    parse_manifest,
)
from ..core.result import Reject
from ..log import utc_now_iso
from ..refs import ValidationError, require


class FrozenBytesMap(MappingABC[str, bytes]):
    """Tuple-backed immutable payload map used across the bundle I/O boundary."""

    __slots__ = ("_items", "_index")

    def __init__(self, values: Mapping[str, bytes] | tuple[tuple[str, bytes], ...] = ()) -> None:
        items = values.items() if isinstance(values, MappingABC) else values
        owned = tuple(sorted((str(key), bytes(value)) for key, value in items))
        if len({key for key, _value in owned}) != len(owned):
            raise ValueError("duplicate payload ref")
        self._items = owned
        self._index = {key: value for key, value in owned}

    def __getitem__(self, key: str) -> bytes:
        return self._index[key]

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def items_tuple(self) -> tuple[tuple[str, bytes], ...]:
        return self._items


def build_manifest(
    bundle: Bundle,
    *,
    created_at: str | None = None,
    producer: Mapping[str, Any] | None = None,
) -> Manifest:
    """Shell convenience wrapper that captures time before calling the pure core."""

    return build_manifest_core(
        bundle,
        created_at=created_at or utc_now_iso(),
        producer=dict(producer) if producer is not None else {"name": "PopperPad", "version": "0.1.0"},
    )


def bundle_root(manifest: Manifest) -> str:
    return manifest_root(manifest)


def _hex_parts(ref: str) -> tuple[str, str]:
    hex_value = ref.split(":", 1)[1]
    return hex_value[:2], hex_value[2:]


def export_bundle(
    bundle: Bundle,
    out_dir: Path,
    *,
    objects: Mapping[str, bytes],
    blobs: Mapping[str, bytes],
    created_at: str | None = None,
    producer: Mapping[str, Any] | None = None,
) -> Manifest:
    """Interpret one immutable bundle value by writing its directory layout."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(bundle, created_at=created_at, producer=producer)
    _write_objects(out, bundle.object_refs, objects)
    _write_blobs(out, bundle.blob_refs, blobs)
    _write_indexes(out, bundle)
    (out / "manifest.json").write_bytes(canonical_json_bytes(manifest.as_json()))
    return manifest


def _write_objects(out: Path, refs: tuple[str, ...], objects: Mapping[str, bytes]) -> None:
    base = out / "objects" / "sha256"
    for ref in refs:
        payload = objects.get(ref)
        require(payload is not None, f"missing object bytes for {ref}")
        payload = bytes(payload)
        require(sha256_bytes(payload) == ref, f"object bytes do not hash to {ref}")
        prefix, rest = _hex_parts(ref)
        target = base / prefix / f"sha256-{prefix}{rest}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _write_blobs(out: Path, refs: tuple[str, ...], blobs: Mapping[str, bytes]) -> None:
    base = out / "blobs" / "sha256"
    for ref in refs:
        payload = blobs.get(ref)
        require(payload is not None, f"missing blob bytes for {ref}")
        payload = bytes(payload)
        require(sha256_bytes(payload) == ref, f"blob bytes do not hash to {ref}")
        prefix, rest = _hex_parts(ref)
        target = base / prefix / f"sha256-{prefix}{rest}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _write_indexes(out: Path, bundle: Bundle) -> None:
    index_dir = out / "indexes"
    index_dir.mkdir(parents=True, exist_ok=True)
    refs_index = {"object_refs": bundle.object_refs, "blob_refs": bundle.blob_refs}
    (index_dir / "refs.json").write_bytes(canonical_json_bytes(refs_index))


@dataclass(frozen=True, slots=True)
class LoadedBundle:
    manifest: Manifest
    objects: FrozenBytesMap
    blobs: FrozenBytesMap


def load_bundle_dir(bundle_dir: Path) -> LoadedBundle:
    """Read bytes in the shell, then parse and verify immutable core values."""

    directory = Path(bundle_dir)
    manifest_path = directory / "manifest.json"
    require(manifest_path.exists(), "manifest.json not found")
    raw = json.loads(manifest_path.read_bytes())
    require(isinstance(raw, Mapping), "manifest must be an object")
    manifest = _parse_manifest(raw)
    objects = _load_payloads(directory / "objects" / "sha256", manifest.object_refs, ".json")
    blobs = _load_payloads(directory / "blobs" / "sha256", manifest.blob_refs, "")
    _verify_content_root(manifest)
    return LoadedBundle(manifest=manifest, objects=objects, blobs=blobs)


def _parse_manifest(data: Mapping[str, Any]) -> Manifest:
    parsed = parse_manifest(data)
    if isinstance(parsed, Reject):
        raise ValidationError(f"{parsed.code}: {dict(parsed.details.items_tuple())}")
    return parsed


def _load_payloads(base: Path, refs: tuple[str, ...], suffix: str) -> FrozenBytesMap:
    payloads: dict[str, bytes] = {}
    for ref in refs:
        prefix, rest = _hex_parts(ref)
        path = base / prefix / f"sha256-{prefix}{rest}{suffix}"
        require(path.exists(), f"missing payload file for {ref}")
        data = path.read_bytes()
        require(sha256_bytes(data) == ref, f"payload hash mismatch for {ref}")
        payloads[ref] = data
    return FrozenBytesMap(payloads)


def _verify_content_root(manifest: Manifest) -> None:
    reconstructed = Bundle(
        bundle_id=manifest.bundle_id,
        object_refs=manifest.object_refs,
        blob_refs=manifest.blob_refs,
        entry_refs=manifest.entry_refs,
        previous_bundle_refs=manifest.previous_bundle_refs,
        signatures=manifest.signatures,
        storage_hints=manifest.storage_hints,
        anchor_hints=manifest.anchor_hints,
    )
    require(content_root(reconstructed) == manifest.root_hash, "manifest root_hash does not match content")


__all__ = [
    "Bundle",
    "FrozenBytesMap",
    "LoadedBundle",
    "Manifest",
    "build_manifest",
    "bundle_root",
    "export_bundle",
    "load_bundle_dir",
]
