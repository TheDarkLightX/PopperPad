"""Versioned commitments plus the byte-compatible v1 JSON surface."""

import json
from collections.abc import Mapping
from typing import Any

from .core.codec import (
    CANONICAL_JSON_VERSION,
    canonical_hash,
    domain_sha256,
    sha256_bytes,
)


def _legacy_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _legacy_plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_legacy_plain(child) for child in value]
    return value


def canonical_json_bytes(obj: Any) -> bytes:
    """Encode the original v1 PopperPad JSON format byte-for-byte.

    Existing schemas and pads may contain finite JSON floats. New FCIS core
    commitments use ``popperpad.core.codec.canonical_json_bytes`` and reject
    binary floating point before encoding.
    """

    encoded = json.dumps(
        _legacy_plain(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (encoded + "\n").encode("utf-8")


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
