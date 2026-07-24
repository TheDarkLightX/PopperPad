"""Compatibility surface for PopperPad's pure canonical codec."""

from .core.codec import (
    CANONICAL_JSON_VERSION,
    canonical_hash,
    canonical_json_bytes,
    domain_sha256,
    sha256_bytes,
)


def stable_sha256(obj: object) -> str:
    """Legacy canonical JSON hash retained for v1 object/log compatibility.

    New authority-bearing commitments must call ``canonical_hash`` with an
    explicit semantic domain. Keeping this function byte-compatible avoids
    invalidating existing v1 pads during the FCIS migration.
    """

    return sha256_bytes(canonical_json_bytes(obj))


__all__ = [
    "CANONICAL_JSON_VERSION",
    "canonical_hash",
    "canonical_json_bytes",
    "domain_sha256",
    "sha256_bytes",
    "stable_sha256",
]
