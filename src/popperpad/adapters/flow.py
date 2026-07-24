from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..canonical import canonical_json_bytes, sha256_bytes, stable_sha256
from ..log import utc_now_iso
from ..pad import PopperPad
from ..refs import ValidationError, require
from ..validate import validate_object
from .base import ImportReport, PreparedBundle, TrustPolicy, VerificationCheck, VerificationReport
from .bundle import Bundle, LoadedBundle, bundle_root, load_bundle_dir


def gather_from_pad(
    pad: PopperPad,
    *,
    object_refs: Iterable[str],
    blob_refs: Iterable[str] = (),
    entry_refs: Iterable[str] | None = None,
    bundle_id: str,
    previous_bundle_refs: Iterable[str] = (),
) -> tuple[Bundle, dict[str, bytes], dict[str, bytes]]:
    """Load object/blob bytes from a pad's CAS into an immutable bundle input set."""

    object_ref_values = sorted({str(ref) for ref in object_refs})
    blob_ref_values = sorted({str(ref) for ref in blob_refs})
    entry_values = sorted({str(ref) for ref in (entry_refs or object_ref_values)})
    previous_values = sorted({str(ref) for ref in previous_bundle_refs})

    objects = {ref: canonical_json_bytes(pad.get_object(ref)) for ref in object_ref_values}
    blobs = {ref: pad.get_blob(ref) for ref in blob_ref_values}
    bundle = Bundle(
        bundle_id=bundle_id,
        object_refs=object_ref_values,  # type: ignore[arg-type]
        blob_refs=blob_ref_values,  # type: ignore[arg-type]
        entry_refs=entry_values,  # type: ignore[arg-type]
        previous_bundle_refs=previous_values,  # type: ignore[arg-type]
    )
    return bundle, objects, blobs


def prepare(
    bundle: Bundle, manifest: Any, objects: Mapping[str, bytes], blobs: Mapping[str, bytes]
) -> PreparedBundle:
    """Compute the immutable prepared-bundle summary consumed by storage shells."""

    require(set(objects) == {str(ref) for ref in bundle.object_refs}, "objects do not match bundle.object_refs")
    require(set(blobs) == {str(ref) for ref in bundle.blob_refs}, "blobs do not match bundle.blob_refs")
    manifest_bytes = canonical_json_bytes(manifest.as_dict())
    byte_size = len(manifest_bytes) + sum(len(value) for value in objects.values()) + sum(
        len(value) for value in blobs.values()
    )
    return PreparedBundle(
        manifest_ref=sha256_bytes(manifest_bytes),
        bundle_root=bundle_root(manifest),
        object_count=len(bundle.object_refs),
        blob_count=len(bundle.blob_refs),
        byte_size=byte_size,
    )


def verify_bundle(bundle_dir: Path) -> VerificationReport:
    """Verify manifest content, object/blob hashes, and the declared content root."""

    checks: list[VerificationCheck] = []
    try:
        loaded = load_bundle_dir(bundle_dir)
    except Exception as exc:
        checks.append(VerificationCheck("load", "fail", f"{type(exc).__name__}: {exc}"))
        return _report(loaded_target(bundle_dir), checks, fail=True)

    checks.append(VerificationCheck("object_hashes", "pass"))
    checks.append(VerificationCheck("blob_hashes", "pass"))
    manifest_hash_ok = bundle_root(loaded.manifest) == stable_sha256(loaded.manifest.as_dict())
    checks.append(VerificationCheck("manifest_hash", "pass" if manifest_hash_ok else "fail"))
    content_ok = _content_root_matches(loaded)
    checks.append(VerificationCheck("content_root", "pass" if content_ok else "fail"))
    return _report(loaded.manifest.root_hash, checks, fail=not (manifest_hash_ok and content_ok))


def _content_root_matches(loaded: LoadedBundle) -> bool:
    content = {
        "object_refs": loaded.manifest.object_refs,
        "blob_refs": loaded.manifest.blob_refs,
        "entry_refs": loaded.manifest.entry_refs,
        "previous_bundle_refs": loaded.manifest.previous_bundle_refs,
    }
    return stable_sha256(content) == loaded.manifest.root_hash


def _preflight_import(loaded: LoadedBundle) -> tuple[tuple[tuple[bytes, str], ...], tuple[tuple[bytes, str], ...]]:
    """Fully validate hostile bundle bytes before any authoritative pad mutation."""

    objects: list[tuple[bytes, str]] = []
    for ref in loaded.manifest.object_refs:
        payload = loaded.objects.get(ref)
        require(payload is not None, f"missing object payload for {ref}")
        require(sha256_bytes(payload) == ref, f"object payload hash mismatch for {ref}")
        parsed = json.loads(payload.decode("utf-8"))
        require(isinstance(parsed, Mapping), f"object payload is not a mapping: {ref}")
        validate_object(parsed)
        require(canonical_json_bytes(parsed) == payload, f"object payload is not canonical: {ref}")
        schema = parsed.get("schema")
        require(isinstance(schema, str) and schema, f"object schema is invalid: {ref}")
        objects.append((bytes(payload), schema))

    blobs: list[tuple[bytes, str]] = []
    for ref in loaded.manifest.blob_refs:
        payload = loaded.blobs.get(ref)
        require(payload is not None, f"missing blob payload for {ref}")
        require(sha256_bytes(payload) == ref, f"blob payload hash mismatch for {ref}")
        blobs.append((bytes(payload), "application/octet-stream"))
    return tuple(objects), tuple(blobs)


def import_bundle(bundle_dir: Path, target: PopperPad, policy: TrustPolicy) -> ImportReport:
    """Preflight a complete bundle, then publish it through one atomic commit."""

    verification = verify_bundle(bundle_dir)
    if not verification.ok:
        return ImportReport(
            bundle_root=_loaded_root(bundle_dir),
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification.checks,
        )

    try:
        loaded = load_bundle_dir(bundle_dir)
        if policy.require_signatures and not loaded.manifest.signatures:
            return ImportReport(
                bundle_root=loaded.manifest.root_hash,
                imported_object_refs=(),
                imported_blob_refs=(),
                skipped_refs=(),
                status="rejected",
                checks=verification.checks + (VerificationCheck("required_signatures", "fail"),),
            )

        objects, blobs = _preflight_import(loaded)
        committed = target.commit_prevalidated_values(
            objects=objects,
            blobs=blobs,
            evidence_root=loaded.manifest.root_hash,
            created_at=utc_now_iso(),
            policy_version="popperpad-import-policy/v1",
            core_version="popperpad-core/v1",
        )
        expected_object_refs = tuple(loaded.manifest.object_refs)
        expected_blob_refs = tuple(loaded.manifest.blob_refs)
        require(committed.object_refs == expected_object_refs, "atomic import object refs differ from manifest")
        require(committed.blob_refs == expected_blob_refs, "atomic import blob refs differ from manifest")
        return ImportReport(
            bundle_root=loaded.manifest.root_hash,
            imported_object_refs=committed.object_refs,
            imported_blob_refs=committed.blob_refs,
            skipped_refs=(),
            status="imported",
            checks=verification.checks + (VerificationCheck("atomic_commit", "pass"),),
        )
    except Exception as exc:
        return ImportReport(
            bundle_root=_loaded_root(bundle_dir),
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification.checks
            + (VerificationCheck("atomic_commit", "fail", f"{type(exc).__name__}: {exc}"),),
        )


def _loaded_root(bundle_dir: Path) -> str:
    try:
        return load_bundle_dir(bundle_dir).manifest.root_hash
    except Exception:
        return ""


def _report(target_ref: str, checks: list[VerificationCheck], *, fail: bool) -> VerificationReport:
    return VerificationReport(
        target_ref=target_ref,
        status="fail" if fail else "pass",
        checks=tuple(checks),
        verified_at=utc_now_iso(),
    )


def loaded_target(bundle_dir: Path) -> str:
    return _loaded_root(bundle_dir)
