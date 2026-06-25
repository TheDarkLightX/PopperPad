from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, sha256_bytes
from .refs import REF_RE, require


@dataclass(frozen=True)
class CasPutResult:
    ref: str
    path: str
    bytes_written: int


def _atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> int:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp)
    try:
        os.fchmod(fd, int(mode))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
        try:
            dfd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except Exception:
            pass
        return len(data)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


class ContentAddressedStore:
    """
    Content-addressed store for PopperPad objects and blobs.

    Layout:
      root/
        objects/
          sha256/
            ab/
              <rest_of_hex>
    """

    def __init__(self, *, root: Path):
        self.root = Path(root).resolve()
        self.obj_dir = self.root / "objects" / "sha256"

    def _path_for_ref(self, ref: str) -> Path:
        require(isinstance(ref, str) and bool(REF_RE.match(ref)), "invalid ref (expected sha256:<64hex>)")
        hex_ = ref.split(":", 1)[1]
        return self.obj_dir / hex_[:2] / hex_[2:]

    def put_bytes(self, data: bytes) -> CasPutResult:
        ref = sha256_bytes(data)
        p = self._path_for_ref(ref)
        if p.exists():
            cur = p.read_bytes()
            require(sha256_bytes(cur) == ref, "CAS corruption: existing object hash mismatch")
            return CasPutResult(ref=ref, path=str(p), bytes_written=0)
        p.parent.mkdir(parents=True, exist_ok=True)
        n = _atomic_write_bytes(p, data, mode=0o600)
        chk = p.read_bytes()
        require(sha256_bytes(chk) == ref, "CAS corruption: written object hash mismatch")
        return CasPutResult(ref=ref, path=str(p), bytes_written=int(n))

    def get_bytes(self, ref: str) -> bytes:
        p = self._path_for_ref(ref)
        data = p.read_bytes()
        require(sha256_bytes(data) == ref, "CAS corruption: object hash mismatch on read")
        return data

    def put_json(self, obj: Any) -> CasPutResult:
        return self.put_bytes(canonical_json_bytes(obj))

    def get_json(self, ref: str) -> Any:
        b = self.get_bytes(ref)
        obj = json.loads(b.decode("utf-8"))
        require(canonical_json_bytes(obj) == b, "CAS JSON is not canonical (integrity check failed)")
        return obj

