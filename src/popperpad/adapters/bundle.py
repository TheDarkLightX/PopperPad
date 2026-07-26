from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..canonical import canonical_hash, canonical_json_bytes, sha256_bytes
from ..core.imports import BundleSignature, SignatureAlgorithm
from ..core.values import DeeplyImmutable, FrozenDict, JsonValue, freeze_json, thaw_json
from ..log import utc_now_iso
from ..refs import Ref, ValidationError, is_ref, require
from ..schemas import SCHEMA_BUNDLE_MANIFEST_V1


MAX_MANIFEST_BYTES = 1_048_576
MAX_PAYLOAD_BYTES = 67_108_864
MAX_TOTAL_PAYLOAD_BYTES = 268_435_456
MAX_BUNDLE_REFS = 100_000
_BUNDLE_CONTENT_DOMAIN = "bundle-content/v1"
_BUNDLE_MANIFEST_DOMAIN = "bundle-manifest/v1"
_BUNDLE_UNSIGNED_MANIFEST_DOMAIN = "bundle-manifest-unsigned/v1"
_MANIFEST_FIELDS = frozenset(
    {
        "schema", "bundle_id", "created_at", "producer", "root_hash",
        "object_refs", "blob_refs", "entry_refs", "previous_bundle_refs",
        "signatures", "storage_hints", "anchor_hints",
    }
)
_SIGNATURE_FIELDS = frozenset({"algorithm", "key_id", "signature_hex"})


def _freeze_metadata_mapping(value: Mapping[str, Any], *, path: str) -> FrozenDict[JsonValue]:
    frozen = freeze_json(value, path=path)
    require(type(frozen) is FrozenDict, f"metadata at {path} must be an object")
    return frozen


def _thaw_metadata(value: Any) -> Any:
    return thaw_json(value)


def _sorted_refs(refs: Any) -> tuple[str, ...]:
    require(isinstance(refs, (list, tuple)), "refs must be a list or tuple")
    require(all(isinstance(value, str) for value in refs), "refs must contain strings")
    parsed = tuple(str(Ref(value)) for value in refs)
    require(parsed == tuple(sorted(parsed)), "refs must be sorted and unique")
    return parsed


def _validated_ref_strings(field_name: str, refs: object) -> tuple[str, ...]:
    require(type(refs) in (list, tuple), f"manifest {field_name} must be an array")
    require(len(refs) <= MAX_BUNDLE_REFS, f"manifest {field_name} exceeds the ref limit")
    require(
        all(type(value) is str and is_ref(value) for value in refs),
        f"manifest {field_name} contains an invalid ref",
    )
    values = tuple(refs)
    require(
        values == tuple(sorted(set(values))),
        f"manifest {field_name} must be sorted and unique",
    )
    return values


def _validated_signature(value: Mapping[str, Any], *, path: str) -> FrozenDict[JsonValue]:
    require(
        type(value) in (dict, FrozenDict),
        f"signature at {path} must be an owned object",
    )
    require(set(value) == _SIGNATURE_FIELDS, f"signature at {path} has unknown or missing fields")
    algorithm = value["algorithm"]
    key_id = value["key_id"]
    signature_hex = value["signature_hex"]
    require(
        type(algorithm) is str and algorithm == SignatureAlgorithm.ED25519.value,
        f"unsupported signature algorithm at {path}",
    )
    require(type(key_id) is str and is_ref(key_id), f"signature key_id at {path} is invalid")
    require(
        type(signature_hex) is str and len(signature_hex) == 128,
        f"signature_hex at {path} must encode 64 bytes",
    )
    require(signature_hex == signature_hex.lower(), f"signature_hex at {path} must be lowercase")
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise ValidationError(f"signature_hex at {path} is invalid") from exc
    require(len(signature) == 64, f"signature_hex at {path} must encode 64 bytes")
    frozen = freeze_json(
        {
            "algorithm": algorithm,
            "key_id": key_id,
            "signature_hex": signature_hex,
        }
    )
    assert isinstance(frozen, FrozenDict)
    return frozen


@dataclass(frozen=True, slots=True)
class Bundle(DeeplyImmutable):
    """A canonical PopperPad publication bundle.

    Invalid states are unrepresentable: refs are validated and must be sorted
    and unique at construction time. The content root (``root_hash``) is a pure
    function of ``object_refs``, ``blob_refs``, ``entry_refs`` and
    ``previous_bundle_refs``; the ``bundle_root`` is the canonical hash of the
    full manifest.
    """

    bundle_id: str
    object_refs: tuple[str, ...]
    blob_refs: tuple[str, ...]
    entry_refs: tuple[str, ...]
    previous_bundle_refs: tuple[str, ...] = ()
    signatures: tuple[FrozenDict[JsonValue], ...] = ()
    storage_hints: tuple[FrozenDict[JsonValue], ...] = ()
    anchor_hints: tuple[FrozenDict[JsonValue], ...] = ()

    def __post_init__(self) -> None:
        require(type(self.bundle_id) is str and self.bundle_id, "bundle_id must be a non-empty string")
        object.__setattr__(self, "object_refs", _sorted_refs(self.object_refs))
        object.__setattr__(self, "blob_refs", _sorted_refs(self.blob_refs))
        object.__setattr__(self, "entry_refs", _sorted_refs(self.entry_refs))
        object.__setattr__(self, "previous_bundle_refs", _sorted_refs(self.previous_bundle_refs))
        require(
            set(self.entry_refs).issubset(self.object_refs),
            "entry_refs must be a subset of object_refs",
        )
        require(
            set(self.object_refs).isdisjoint(self.blob_refs),
            "object_refs and blob_refs must be disjoint",
        )
        require(type(self.signatures) is tuple, "signatures must be a tuple")
        object.__setattr__(
            self,
            "signatures",
            tuple(
                _validated_signature(value, path=f"$.signatures[{index}]")
                for index, value in enumerate(self.signatures)
            ),
        )
        require(type(self.storage_hints) is tuple, "storage_hints must be a tuple")
        object.__setattr__(
            self,
            "storage_hints",
            tuple(
                _freeze_metadata_mapping(value, path=f"$.storage_hints[{index}]")
                for index, value in enumerate(self.storage_hints)
            ),
        )
        require(type(self.anchor_hints) is tuple, "anchor_hints must be a tuple")
        object.__setattr__(
            self,
            "anchor_hints",
            tuple(
                _freeze_metadata_mapping(value, path=f"$.anchor_hints[{index}]")
                for index, value in enumerate(self.anchor_hints)
            ),
        )
        DeeplyImmutable.__post_init__(self)

    def content(self) -> dict[str, Any]:
        return {
            "object_refs": [str(r) for r in self.object_refs],
            "blob_refs": [str(r) for r in self.blob_refs],
            "entry_refs": [str(r) for r in self.entry_refs],
            "previous_bundle_refs": [str(r) for r in self.previous_bundle_refs],
        }


@dataclass(frozen=True, slots=True)
class Manifest(DeeplyImmutable):
    schema: str
    bundle_id: str
    created_at: str
    producer: FrozenDict[JsonValue]
    root_hash: str
    object_refs: tuple[str, ...]
    blob_refs: tuple[str, ...]
    entry_refs: tuple[str, ...]
    previous_bundle_refs: tuple[str, ...]
    signatures: tuple[FrozenDict[JsonValue], ...] = field(default_factory=tuple)
    storage_hints: tuple[FrozenDict[JsonValue], ...] = field(default_factory=tuple)
    anchor_hints: tuple[FrozenDict[JsonValue], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require(type(self.schema) is str and self.schema == SCHEMA_BUNDLE_MANIFEST_V1, "manifest schema is invalid")
        require(type(self.bundle_id) is str and bool(self.bundle_id), "manifest bundle_id must be non-empty")
        require(type(self.created_at) is str and bool(self.created_at), "manifest created_at must be non-empty")
        require(type(self.root_hash) is str and is_ref(self.root_hash), "manifest root_hash is invalid")
        object.__setattr__(self, "producer", _freeze_metadata_mapping(self.producer, path="$.producer"))
        for field_name in ("object_refs", "blob_refs", "entry_refs", "previous_bundle_refs"):
            object.__setattr__(
                self,
                field_name,
                _validated_ref_strings(field_name, getattr(self, field_name)),
            )
        require(
            set(self.entry_refs).issubset(self.object_refs),
            "manifest entry_refs must be a subset of object_refs",
        )
        require(
            set(self.object_refs).isdisjoint(self.blob_refs),
            "manifest object_refs and blob_refs must be disjoint",
        )
        require(type(self.signatures) in (list, tuple), "manifest signatures must be an array")
        object.__setattr__(
            self,
            "signatures",
            tuple(
                _validated_signature(value, path=f"$.signatures[{index}]")
                for index, value in enumerate(self.signatures)
            ),
        )
        signer_ids = tuple(value["key_id"] for value in self.signatures)
        require(
            signer_ids == tuple(sorted(set(signer_ids))),
            "manifest signatures must use sorted and unique key_ids",
        )
        for field_name in ("storage_hints", "anchor_hints"):
            values = getattr(self, field_name)
            require(type(values) in (list, tuple), f"manifest {field_name} must be an array")
            object.__setattr__(
                self,
                field_name,
                tuple(
                    _freeze_metadata_mapping(value, path=f"$.{field_name}[{index}]")
                    for index, value in enumerate(values)
                ),
            )
        DeeplyImmutable.__post_init__(self)

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
        root_hash=canonical_hash(_BUNDLE_CONTENT_DOMAIN, content),
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
    return canonical_hash(_BUNDLE_MANIFEST_DOMAIN, manifest.as_dict())


def unsigned_bundle_root(manifest: Manifest) -> str:
    """Hash the full manifest with an empty signature set.

    Signatures authenticate this acyclic commitment. The final ``bundle_root``
    additionally commits to the admitted signature metadata.
    """

    require(type(manifest) is Manifest, "manifest must be an exact Manifest")
    unsigned = manifest.as_dict()
    unsigned["signatures"] = []
    return canonical_hash(_BUNDLE_UNSIGNED_MANIFEST_DOMAIN, unsigned)


def bundle_content_root(manifest: Manifest) -> str:
    """Recompute the content-only root in its dedicated semantic domain."""

    require(type(manifest) is Manifest, "manifest must be an exact Manifest")
    return canonical_hash(
        _BUNDLE_CONTENT_DOMAIN,
        {
            "object_refs": manifest.object_refs,
            "blob_refs": manifest.blob_refs,
            "entry_refs": manifest.entry_refs,
            "previous_bundle_refs": manifest.previous_bundle_refs,
        },
    )


def bundle_signatures(manifest: Manifest) -> tuple[BundleSignature, ...]:
    require(type(manifest) is Manifest, "manifest must be an exact Manifest")
    return tuple(
        BundleSignature(
            key_id=value["key_id"],
            algorithm=SignatureAlgorithm(value["algorithm"]),
            signature=bytes.fromhex(value["signature_hex"]),
        )
        for value in manifest.signatures
    )


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


def _write_objects(out: Path, refs: tuple[str, ...], objects: Mapping[str, bytes]) -> None:
    base = out / "objects" / "sha256"
    for ref in refs:
        payload = objects.get(str(ref))
        require(payload is not None, f"missing object bytes for {ref}")
        require(sha256_bytes(payload) == str(ref), f"object bytes do not hash to {ref}")
        prefix, rest = _hex_parts(str(ref))
        target = base / prefix / f"sha256-{prefix}{rest}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _write_blobs(out: Path, refs: tuple[str, ...], blobs: Mapping[str, bytes]) -> None:
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


@dataclass(frozen=True, slots=True)
class LoadedBundle(DeeplyImmutable):
    manifest: Manifest
    objects: FrozenDict[bytes]
    blobs: FrozenDict[bytes]

    def __post_init__(self) -> None:
        if type(self.manifest) is not Manifest:
            raise TypeError("manifest must be an exact Manifest")
        object.__setattr__(self, "objects", FrozenDict(self.objects))
        object.__setattr__(self, "blobs", FrozenDict(self.blobs))
        DeeplyImmutable.__post_init__(self)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    owned: dict[str, Any] = {}
    for key, value in pairs:
        require(type(key) is str, "manifest keys must be strings")
        require(key not in owned, f"duplicate manifest key: {key}")
        owned[key] = value
    return owned


def _read_regular_bundle_file(root: Path, path: Path, *, max_bytes: int) -> bytes:
    relative = path.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        require(not cursor.is_symlink(), f"bundle path must not contain symlinks: {relative}")
    require(path.is_file(), f"bundle file is missing or not regular: {relative}")
    stat = path.stat()
    require(stat.st_size <= max_bytes, f"bundle file exceeds byte limit: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(root), f"bundle path escapes root: {relative}")
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    require(len(data) <= max_bytes, f"bundle file exceeds byte limit: {relative}")
    return data


def _decode_manifest(raw: bytes) -> dict[str, Any]:
    require(bool(raw), "manifest.json is empty")
    try:
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"manifest.json is not valid JSON: {exc}") from exc
    require(type(parsed) is dict, "manifest.json must contain an object")
    require(canonical_json_bytes(parsed) == raw, "manifest.json must use canonical bytes")
    return parsed


def load_bundle_dir(bundle_dir: Path) -> LoadedBundle:
    """Bound and canonically admit all hostile bundle bytes before returning."""

    root = Path(bundle_dir).resolve(strict=True)
    require(root.is_dir(), "bundle path must be a directory")
    manifest_bytes = _read_regular_bundle_file(
        root,
        root / "manifest.json",
        max_bytes=MAX_MANIFEST_BYTES,
    )
    manifest = _parse_manifest(_decode_manifest(manifest_bytes))
    objects = _load_payloads(
        root,
        root / "objects" / "sha256",
        manifest.object_refs,
        ".json",
        max_total_bytes=MAX_TOTAL_PAYLOAD_BYTES,
    )
    remaining_bytes = MAX_TOTAL_PAYLOAD_BYTES - sum(map(len, objects.values()))
    blobs = _load_payloads(
        root,
        root / "blobs" / "sha256",
        manifest.blob_refs,
        "",
        max_total_bytes=remaining_bytes,
    )
    _verify_content_root(manifest)
    return LoadedBundle(
        manifest=manifest,
        objects=FrozenDict(objects),
        blobs=FrozenDict(blobs),
    )


def _parse_manifest(data: dict[str, Any]) -> Manifest:
    require(set(data) == _MANIFEST_FIELDS, "manifest has unknown or missing fields")
    require(
        type(data["schema"]) is str and data["schema"] == SCHEMA_BUNDLE_MANIFEST_V1,
        f"manifest schema must be {SCHEMA_BUNDLE_MANIFEST_V1}",
    )
    require(type(data["producer"]) is dict, "manifest producer must be an object")
    return Manifest(
        schema=data["schema"],
        bundle_id=data["bundle_id"],
        created_at=data["created_at"],
        producer=data["producer"],
        root_hash=data["root_hash"],
        object_refs=data["object_refs"],
        blob_refs=data["blob_refs"],
        entry_refs=data["entry_refs"],
        previous_bundle_refs=data["previous_bundle_refs"],
        signatures=data["signatures"],
        storage_hints=data["storage_hints"],
        anchor_hints=data["anchor_hints"],
    )


def _load_payloads(
    root: Path,
    base: Path,
    refs: tuple[str, ...],
    suffix: str,
    *,
    max_total_bytes: int,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    total_bytes = 0
    for ref in refs:
        prefix, rest = _hex_parts(ref)
        path = base / prefix / f"sha256-{prefix}{rest}{suffix}"
        remaining_bytes = max_total_bytes - total_bytes
        require(remaining_bytes >= 0, "bundle payloads exceed total byte limit")
        data = _read_regular_bundle_file(
            root,
            path,
            max_bytes=min(MAX_PAYLOAD_BYTES, remaining_bytes),
        )
        require(sha256_bytes(data) == ref, f"payload hash mismatch for {ref}")
        payloads[ref] = data
        total_bytes += len(data)
    return payloads


def _verify_content_root(manifest: Manifest) -> None:
    require(
        bundle_content_root(manifest) == manifest.root_hash,
        "manifest root_hash does not match content",
    )
