from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .codec import canonical_hash


def ed25519_verifier_ref(public_key: bytes) -> str:
    """Return the domain-separated identity of one exact Ed25519 public key."""

    if type(public_key) is not bytes or len(public_key) != 32:
        raise ValueError("Ed25519 public key must be exactly 32 bytes")
    return canonical_hash(
        "market-verifier-key/v1",
        {"algorithm": "ed25519", "public_key_hex": public_key.hex()},
    )


def verify_ed25519_signature(
    *,
    public_key: bytes,
    signature: bytes,
    message: bytes,
) -> bool:
    """Purely verify one exact Ed25519 signature without key discovery or I/O."""

    if (
        type(public_key) is not bytes
        or len(public_key) != 32
        or type(signature) is not bytes
        or len(signature) != 64
        or type(message) is not bytes
    ):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, TypeError, ValueError):
        return False
    return True
