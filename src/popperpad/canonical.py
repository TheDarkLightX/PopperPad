"""Compatibility surface for PopperPad's pure canonical codec."""

from .core.codec import (
    CANONICAL_JSON_VERSION,
    canonical_hash,
    canonical_json_bytes,
    domain_sha256,
    sha256_bytes,
)


def stable_sha256(obj: object) -> str:
    """Canonical JSON hash under the versioned generic-object domain."""

    return canonical_hash("canonical-json/v2", obj)


__all__ = [
    "CANONICAL_JSON_VERSION",
    "canonical_hash",
    "canonical_json_bytes",
    "domain_sha256",
    "sha256_bytes",
    "stable_sha256",
]
