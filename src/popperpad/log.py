from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .canonical import canonical_json_bytes, stable_sha256


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOG_SCHEMA_V1 = "popperpad/log_record/v1"


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    raise ValueError(msg)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AppendResult:
    record_hash: str


def _strip_record_hash(rec: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(rec)
    out.pop("record_hash", None)
    return out


def _read_last_nonempty_line(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        st = path.stat()
    except FileNotFoundError:
        return ""
    if st.st_size == 0:
        return ""

    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buf = b""
        while pos > 0:
            step = min(4096, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step)
            buf = chunk + buf
            if b"\n" not in chunk and pos != 0:
                continue
            lines = [ln for ln in buf.splitlines() if ln.strip()]
            if not lines:
                continue
            return lines[-1].decode("utf-8")
    return ""


class AppendOnlyLog:
    """
    Append-only JSONL log with a hash chain (prev_record_hash).
    """

    def __init__(self, *, path: Path):
        self.path = Path(path).resolve()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    @contextmanager
    def _lock(self):
        try:
            import fcntl  # linux/mac
        except Exception:
            fcntl = None

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(fd)

    def head(self) -> str:
        ln = _read_last_nonempty_line(self.path)
        if not ln:
            return ""
        rec = json.loads(ln)
        rh = rec.get("record_hash", "")
        _require(isinstance(rh, str) and bool(_REF_RE.match(rh)), "log corruption: invalid record_hash")
        return rh

    def append(self, record_core: Mapping[str, Any]) -> AppendResult:
        rec = dict(record_core)
        _require(rec.get("schema") == _LOG_SCHEMA_V1, f"log record schema must be {_LOG_SCHEMA_V1}")
        _require(isinstance(rec.get("op"), str) and rec.get("op"), "log record op must be set")
        _require(isinstance(rec.get("created_at"), str) and rec.get("created_at"), "log record created_at must be set")

        with self._lock():
            prev = self.head()
            rec["prev_record_hash"] = prev
            rh = stable_sha256(rec)
            full = dict(rec)
            full["record_hash"] = rh
            self._append_line(full)
            return AppendResult(record_hash=rh)

    def _append_line(self, obj: Mapping[str, Any]) -> None:
        data = canonical_json_bytes(obj)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(str(self.path), flags, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    def iter_records(self) -> Iterator[Mapping[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                yield json.loads(ln)

    def verify(self) -> None:
        prev = ""
        for i, rec in enumerate(self.iter_records()):
            _require(rec.get("schema") == _LOG_SCHEMA_V1, f"log corruption: bad schema at line {i+1}")
            rh = rec.get("record_hash")
            _require(isinstance(rh, str) and bool(_REF_RE.match(rh)), f"log corruption: bad record_hash at line {i+1}")
            _require(str(rec.get("prev_record_hash", "")) == prev, f"log corruption: prev_record_hash mismatch at line {i+1}")
            core = _strip_record_hash(rec)
            _require(stable_sha256(core) == rh, f"log corruption: record_hash mismatch at line {i+1}")
            prev = rh

    def stats(self) -> dict[str, Any]:
        n = 0
        last = ""
        for rec in self.iter_records():
            n += 1
            last = str(rec.get("record_hash", ""))
        return {"event_count": n, "head": last}

