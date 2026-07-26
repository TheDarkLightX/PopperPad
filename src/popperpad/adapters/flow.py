from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..canonical import canonical_json_bytes, sha256_bytes
from ..core.imports import VerifiedImportProvenance, admit_bundle_import
from ..core.result import Reject
from ..core.values import thaw_json
from ..log import utc_now_iso
from ..pad import PopperPad
from ..refs import ValidationError, require
from ..validate import validate_object
from .base import ImportReport, PreparedBundle, TrustPolicy, VerificationCheck, VerificationReport
from .bundle import (
    Bundle,
    LoadedBundle,
    bundle_content_root,
    bundle_root,
    bundle_signatures,
    load_bundle_dir,
    unsigned_bundle_root,
)
from .import_auth import authenticate_bundle_signatures
from .import_receipts import admit_trusted_truth


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
    """Verify one bounded canonical snapshot of a hostile bundle directory."""

    try:
        loaded = load_bundle_dir(bundle_dir)
    except Exception as exc:
        checks = [VerificationCheck("load", "fail", f"{type(exc).__name__}: {exc}")]
        return _report("", checks, fail=True)

    checks = list(_verification_checks(loaded))
    fail = any(check.status != "pass" for check in checks)
    return _report(bundle_root(loaded.manifest), checks, fail=fail)


def _verification_checks(loaded: LoadedBundle) -> tuple[VerificationCheck, ...]:
    """Report checks already established by canonical bounded loading."""

    checks: list[VerificationCheck] = []
    checks.append(VerificationCheck("object_hashes", "pass"))
    checks.append(VerificationCheck("blob_hashes", "pass"))
    checks.append(VerificationCheck("manifest_canonical", "pass"))
    content_ok = _content_root_matches(loaded)
    checks.append(VerificationCheck("content_root", "pass" if content_ok else "fail"))
    return tuple(checks)


def _content_root_matches(loaded: LoadedBundle) -> bool:
    return bundle_content_root(loaded.manifest) == loaded.manifest.root_hash


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


def import_bundle(
    bundle_dir: Path,
    target: PopperPad,
    policy: TrustPolicy,
    *,
    provenance: VerifiedImportProvenance = VerifiedImportProvenance(),
) -> ImportReport:
    """Admit one hostile snapshot, then publish its exact bytes atomically."""

    try:
        loaded = load_bundle_dir(bundle_dir)
    except Exception as exc:
        return ImportReport(
            bundle_root="",
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=(VerificationCheck("load", "fail", f"{type(exc).__name__}: {exc}"),),
        )

    verification_checks = _verification_checks(loaded)
    actual_bundle_root = bundle_root(loaded.manifest)
    unsigned_root = unsigned_bundle_root(loaded.manifest)
    authentication = authenticate_bundle_signatures(
        unsigned_bundle_root=unsigned_root,
        signatures=bundle_signatures(loaded.manifest),
        policy=policy,
    )
    if isinstance(authentication, Reject):
        return ImportReport(
            bundle_root=actual_bundle_root,
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification_checks
            + (
                VerificationCheck(
                    "signature_authentication",
                    "fail",
                    f"{authentication.code}: {thaw_json(authentication.details)}",
                ),
            ),
        )

    decision = admit_bundle_import(
        bundle_root=actual_bundle_root,
        unsigned_bundle_root=unsigned_root,
        content_root=loaded.manifest.root_hash,
        authenticated_signatures=authentication,
        previous_bundle_refs=loaded.manifest.previous_bundle_refs,
        policy=policy,
        provenance=provenance,
    )
    if isinstance(decision, Reject):
        return ImportReport(
            bundle_root=actual_bundle_root,
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification_checks
            + (
                VerificationCheck(
                    "import_admission",
                    "fail",
                    f"{decision.code}: {thaw_json(decision.details)}",
                ),
            ),
        )

    admission_checks = (
        VerificationCheck("independent_bundle_root", "pass"),
        VerificationCheck(
            "signature_authentication",
            "pass",
            f"{len(decision.receipt.signer_key_ids)} admitted signer(s)",
        ),
        VerificationCheck("adapter_policy", "pass"),
        VerificationCheck("anchor_policy", "pass"),
        VerificationCheck("truth_activation", "pass", decision.receipt.truth_mode.value),
    )
    try:
        objects, blobs = _preflight_import(loaded)
    except Exception as exc:
        return ImportReport(
            bundle_root=actual_bundle_root,
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification_checks
            + admission_checks
            + (VerificationCheck("preflight", "fail", f"{type(exc).__name__}: {exc}"),),
        )

    truth_admission = admit_trusted_truth(loaded, policy)
    if isinstance(truth_admission, Reject):
        return ImportReport(
            bundle_root=actual_bundle_root,
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification_checks
            + admission_checks
            + (
                VerificationCheck(
                    "verifier_receipts",
                    "fail",
                    f"{truth_admission.code}: {thaw_json(truth_admission.details)}",
                ),
            ),
        )

    receipt_check = VerificationCheck(
        "verifier_receipts",
        "pass",
        f"{len(truth_admission)} admitted receipt(s)",
    )

    try:
        committed = target.commit_prevalidated_values(
            objects=objects,
            blobs=blobs,
            evidence_root=decision.next_state.evidence_root,
            created_at=utc_now_iso(),
            policy_version=decision.next_state.policy_version,
            core_version="popperpad-core/v1",
        )
        expected_object_refs = tuple(loaded.manifest.object_refs)
        expected_blob_refs = tuple(loaded.manifest.blob_refs)
        require(committed.object_refs == expected_object_refs, "atomic import object refs differ from manifest")
        require(committed.blob_refs == expected_blob_refs, "atomic import blob refs differ from manifest")
    except Exception as exc:
        return ImportReport(
            bundle_root=actual_bundle_root,
            imported_object_refs=(),
            imported_blob_refs=(),
            skipped_refs=(),
            status="rejected",
            checks=verification_checks
            + admission_checks
            + (receipt_check,)
            + (VerificationCheck("atomic_commit", "fail", f"{type(exc).__name__}: {exc}"),),
        )

    return ImportReport(
        bundle_root=actual_bundle_root,
        imported_object_refs=committed.object_refs,
        imported_blob_refs=committed.blob_refs,
        skipped_refs=(),
        status="imported",
        checks=verification_checks
        + admission_checks
        + (receipt_check, VerificationCheck("atomic_commit", "pass")),
    )


def _loaded_root(bundle_dir: Path) -> str:
    try:
        return bundle_root(load_bundle_dir(bundle_dir).manifest)
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
