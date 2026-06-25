from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from ..canonical import canonical_json_bytes, sha256_bytes, stable_sha256
from ..log import utc_now_iso
from ..pad import PopperPad
from ..refs import Ref, ValidationError, is_ref, require
from .base import PreparedBundle, TrustPolicy, VerificationCheck, VerificationReport
from .bundle import Bundle, LoadedBundle, build_manifest, bundle_root, load_bundle_dir


def gather_from_pad(
    pad: PopperPad,
    *,
    object_refs: Iterable[str],
    blob_refs: Iterable[str] = (),
    entry_refs: Iterable[str] | None = None,
    bundle_id: str,
    previous_bundle_refs: Iterable[str] = (),
) -> tuple[Bundle, dict[str, bytes], dict[str, bytes]]:
    """Load object/blob bytes from a pad's CAS into in-memory bundle payloads."""
    obj_refs = [str(r) for r in object_refs]
    bl_refs = [str(r) for r in blob_refs]
    entry = [str(r) for r in (entry_refs or obj_refs)]

    objects: dict[str, bytes] = {}
    for ref in obj_refs:
        objects[ref] = canonical_json_bytes(pad.get_object(ref))
    blobs: dict[str, bytes] = {ref: pad.get_blob(ref) for ref in bl_refs}

    bundle = Bundle(
        bundle_id=bundle_id,
        object_refs=obj_refs,  # type: ignore[arg-type]
        blob_refs=bl_refs,  # type: ignore[arg-type]
        entry_refs=entry,  # type: ignore[arg-type]
        previous_bundle_refs=list(previous_bundle_refs),  # type: ignore[arg-type]
    )
    return bundle, objects, blobs


def prepare(
    bundle: Bundle, manifest: Any, objects: Mapping[str, bytes], blobs: Mapping[str, bytes]
) -> PreparedBundle:
    """Compute the ``PreparedBundle`` summary (manifest ref + bundle root + counts)."""
    require(set(objects) == {str(r) for r in bundle.object_refs}, "objects do not match bundle.object_refs")
    require(set(blobs) == {str(r) for r in bundle.blob_refs}, "blobs do not match bundle.blob_refs")
    manifest_bytes = canonical_json_bytes(manifest.as_dict())
    byte_size = len(manifest_bytes) + sum(len(v) for v in objects.values()) + sum(len(v) for v in blobs.values())
    return PreparedBundle(
        manifest_ref=sha256_bytes(manifest_bytes),
        bundle_root=bundle_root(manifest),
        object_count=len(bundle.object_refs),
        blob_count=len(bundle.blob_refs),
        byte_size=byte_size,
    )


def verify_bundle(bundle_dir: Path) -> VerificationReport:
    """Verify a bundle directory: manifest root, object/blob hashes, content root."""
    checks: list[VerificationCheck] = []
    try:
        loaded = load_bundle_dir(bundle_dir)
    except ValidationError as e:
        checks.append(VerificationCheck("load", "fail", str(e)))
        return _report(loaded_target(bundle_dir), checks, fail=True)

    checks.append(VerificationCheck("object_hashes", "pass"))
    checks.append(VerificationCheck("blob_hashes", "pass"))
    root_ok = bundle_root(loaded.manifest) == stable_sha256(loaded.manifest.as_dict())
    checks.append(VerificationCheck("manifest_root", "pass" if root_ok else "fail"))
    content_ok = _content_root_matches(loaded)
    checks.append(VerificationCheck("content_root", "pass" if content_ok else "fail"))
    fail = not (root_ok and content_ok)
    return _report(loaded.manifest.root_hash, checks, fail=fail)


def _content_root_matches(loaded: LoadedBundle) -> bool:
    content = {
        "object_refs": loaded.manifest.object_refs,
        "blob_refs": loaded.manifest.blob_refs,
        "entry_refs": loaded.manifest.entry_refs,
        "previous_bundle_refs": loaded.manifest.previous_bundle_refs,
    }
    return stable_sha256(content) == loaded.manifest.root_hash


def import_bundle(bundle_dir: Path, target: PopperPad, policy: TrustPolicy) -> Any:
    """Verify a bundle and import its objects/blobs into ``target`` (fail-closed)."""
    from .base import ImportReport

    verification = verify_bundle(bundle_dir)
    if not verification.ok:
        return ImportReport(
            bundle_root=_loaded_root(bundle_dir),
            imported_object_refs=[],
            imported_blob_refs=[],
            skipped_refs=[],
            status="rejected",
            checks=verification.checks,
        )
    loaded = load_bundle_dir(bundle_dir)
    if policy.require_signatures and not loaded.manifest.signatures:
        return ImportReport(
            bundle_root=loaded.manifest.root_hash,
            imported_object_refs=[],
            imported_blob_refs=[],
            skipped_refs=[],
            status="rejected",
            checks=verification.checks + [VerificationCheck("required_signatures", "fail")],
        )

    imported_objects: list[str] = []
    imported_blobs: list[str] = []
    skipped: list[str] = []
    for ref, payload in loaded.objects.items():
        if _import_object(target, ref, payload):
            imported_objects.append(ref)
        else:
            skipped.append(ref)
    for ref, payload in loaded.blobs.items():
        if _import_blob(target, ref, payload):
            imported_blobs.append(ref)
        else:
            skipped.append(ref)

    status = "imported" if not skipped else "partial"
    return ImportReport(
        bundle_root=loaded.manifest.root_hash,
        imported_object_refs=imported_objects,
        imported_blob_refs=imported_blobs,
        skipped_refs=skipped,
        status=status,
        checks=verification.checks,
    )


def _import_object(target: PopperPad, ref: str, payload: bytes) -> bool:
    import json
    obj = json.loads(payload.decode("utf-8"))
    existing = target.put_object(obj)
    return existing.obj_ref == ref


def _import_blob(target: PopperPad, ref: str, payload: bytes) -> bool:
    existing = target.put_blob(payload)
    return existing.obj_ref == ref


def _loaded_root(bundle_dir: Path) -> str:
    try:
        return load_bundle_dir(bundle_dir).manifest.root_hash
    except Exception:
        return ""


def _report(target_ref: str, checks: list[VerificationCheck], *, fail: bool) -> VerificationReport:
    return VerificationReport(
        target_ref=target_ref,
        status="fail" if fail else "pass",
        checks=checks,
        verified_at=utc_now_iso(),
    )


def loaded_target(bundle_dir: Path) -> str:
    return _loaded_root(bundle_dir)
