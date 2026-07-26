from __future__ import annotations

import hashlib
import json
from typing import Any

from .values import freeze_json, thaw_json


CANONICAL_JSON_VERSION = "popperpad-json-int-v2"
_DOMAIN_PREFIX = b"PopperPad\x00"


def canonical_json_bytes(value: Any) -> bytes:
    """Encode the integer-only PopperPad canonical JSON profile.

    The accepted value domain is deliberately narrower than general JSON:
    object keys are strings, arrays preserve order, maps are key-sorted, and
    binary floating point is rejected. The trailing newline is part of v2.
    """

    owned = freeze_json(value)
    plain = thaw_json(owned)
    encoded = json.dumps(
        plain,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (encoded + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def domain_frame(domain: str, data: bytes) -> bytes:
    """Frame immutable bytes under an explicit PopperPad semantic domain."""

    if not isinstance(domain, str) or not domain or "\x00" in domain:
        raise ValueError("domain must be a non-empty NUL-free string")
    if type(data) is not bytes:
        raise TypeError("domain-framed data must be exact bytes")
    domain_bytes = domain.encode("utf-8")
    if len(domain_bytes) > 65_535:
        raise ValueError("domain must encode to at most 65535 bytes")
    return _DOMAIN_PREFIX + len(domain_bytes).to_bytes(2, "big") + domain_bytes + data


def domain_sha256(domain: str, data: bytes) -> str:
    """Hash immutable bytes under an explicit PopperPad semantic domain."""

    return sha256_bytes(domain_frame(domain, data))


def canonical_hash(domain: str, value: Any) -> str:
    return domain_sha256(domain, canonical_json_bytes(value))
