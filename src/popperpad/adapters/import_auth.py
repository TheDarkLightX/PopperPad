from __future__ import annotations

from ..core.imports import (
    AuthenticatedBundleSignatures,
    BundleSignature,
    SignatureAlgorithm,
    TrustPolicy,
    bundle_signature_message,
)
from ..core.result import Reject
from ..core.values import FrozenDict, JsonValue, freeze_json
from ..core.verifier import verify_ed25519_signature


def _reject(code: str, **details: JsonValue) -> Reject:
    frozen = freeze_json(details)
    assert isinstance(frozen, FrozenDict)
    return Reject(code, frozen)


def authenticate_bundle_signatures(
    *,
    unsigned_bundle_root: str,
    signatures: tuple[BundleSignature, ...],
    policy: TrustPolicy,
) -> AuthenticatedBundleSignatures | Reject:
    """Imperative-shell authentication for canonical bundle signatures."""

    if type(signatures) is not tuple or not all(
        type(value) is BundleSignature for value in signatures
    ):
        return _reject("INVALID_SIGNATURE_SET", reason="wrong value type")
    trusted_by_id = {signer.key_id: signer for signer in policy.trusted_signers}
    message = bundle_signature_message(unsigned_bundle_root)
    admitted: list[str] = []
    seen: set[str] = set()
    for signature in signatures:
        if signature.key_id in seen:
            return _reject("DUPLICATE_SIGNATURE", key_id=signature.key_id)
        seen.add(signature.key_id)
        trusted = trusted_by_id.get(signature.key_id)
        if trusted is None:
            return _reject("UNKNOWN_SIGNER", key_id=signature.key_id)
        if signature.algorithm is not trusted.algorithm:
            return _reject(
                "SIGNATURE_ALGORITHM_MISMATCH",
                key_id=signature.key_id,
            )
        if (
            signature.algorithm is not SignatureAlgorithm.ED25519
            or not verify_ed25519_signature(
                public_key=trusted.public_key,
                signature=signature.signature,
                message=message,
            )
        ):
            return _reject("INVALID_SIGNATURE", key_id=signature.key_id)
        admitted.append(signature.key_id)
    if policy.require_signatures and len(admitted) < policy.minimum_signatures:
        return _reject(
            "SIGNATURE_THRESHOLD_NOT_MET",
            required=policy.minimum_signatures,
            admitted=len(admitted),
        )
    return AuthenticatedBundleSignatures(
        unsigned_bundle_root=unsigned_bundle_root,
        signer_key_ids=tuple(sorted(admitted)),
    )
