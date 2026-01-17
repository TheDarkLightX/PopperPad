from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(obj: Any) -> bytes:
    """
    Canonical JSON bytes used by PopperPad hashing.

    Notes:
    - This is a deterministic, language-agnostic *spec* only if other implementations
      follow the same serialization rules. We intentionally disallow NaN/Inf.
    - If you need RFC8785 (JCS) compatibility across non-Python implementations,
      treat this function as the norm and reimplement it byte-for-byte elsewhere.
    """
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def stable_sha256(obj: Any) -> str:
    return sha256_bytes(canonical_json_bytes(obj))

