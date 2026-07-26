from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .canonical import canonical_json_bytes, stable_sha256
from .core.commit import CommitBundle, validate_commit_bundle, validate_commit_record
from .core.result import Reject
from .core.values import thaw_json
from .refs import REF_RE, ValidationError, require


_LOG_SCHEMA_V1 = "popperpad/log_record/v1"
_LOG_SCHEMA_V2 = "popperpad/log_record/v2"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class AppendResult:
    record_hash: str


def _strip_record_hash(record: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out.pop("record_hash", None)
    return out


def _read_last_nonempty_line(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return ""
    if size == 0:
        return ""

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        buffer = b""
        while position > 0:
            step = min(4096, position)
            position -= step
            handle.seek(position)
            buffer = handle.read(step) + buffer
            if b"\n" not in buffer and position != 0:
                continue
            lines = [line for line in buffer.splitlines() if line.strip()]
            if lines:
                return lines[-1].decode("utf-8")
    return ""


def _logical_commit_records(record: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    created_at = str(record.get("created_at", ""))
    commit_hash = str(record.get("record_hash", ""))
    for item in record.get("objects", ()) or ():
        if not isinstance(item, Mapping):
            continue
        yield {
            "schema": _LOG_SCHEMA_V1,
            "op": "add_object",
            "created_at": created_at,
            "obj_ref": str(item.get("ref", "")),
            "obj_schema": str(item.get("schema", "")),
            "commit_record_hash": commit_hash,
        }
    for item in record.get("blobs", ()) or ():
        if not isinstance(item, Mapping):
            continue
        yield {
            "schema": _LOG_SCHEMA_V1,
            "op": "add_blob",
            "created_at": created_at,
            "blob_ref": str(item.get("ref", "")),
            "media_type": str(item.get("media_type", "application/octet-stream")),
            "commit_record_hash": commit_hash,
        }


class AppendOnlyLog:
    """Hash-chained JSONL authority log with atomic compare-and-swap append.

    Version-1 records remain readable. Version-2 ``commit_bundle`` records are
    physical atomic records and are projected into legacy add-object/add-blob
    records for existing index and doctor consumers.
    """

    def __init__(self, *, path: Path):
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        self.lock_path.touch(mode=0o600, exist_ok=True)

    @contextmanager
    def _lock(self):
        try:
            import fcntl  # linux/mac
        except Exception:
            fcntl = None

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _head_unlocked(self) -> str:
        line = _read_last_nonempty_line(self.path)
        if not line:
            return ""
        record = json.loads(line)
        record_hash = record.get("record_hash", "")
        require(
            isinstance(record_hash, str) and bool(REF_RE.fullmatch(record_hash)),
            "log corruption: invalid record_hash",
        )
        return record_hash

    def head(self) -> str:
        return self._head_unlocked()

    def append(self, record_core: Mapping[str, Any]) -> AppendResult:
        """Append one legacy v1 record using atomic whole-file replacement."""

        record = dict(record_core)
        require(record.get("schema") == _LOG_SCHEMA_V1, f"log record schema must be {_LOG_SCHEMA_V1}")
        require(isinstance(record.get("op"), str) and record.get("op"), "log record op must be set")
        require(
            isinstance(record.get("created_at"), str) and record.get("created_at"),
            "log record created_at must be set",
        )

        with self._lock():
            previous = self._head_unlocked()
            record["prev_record_hash"] = previous
            record_hash = stable_sha256(record)
            full = {**record, "record_hash": record_hash}
            self._append_line_atomically_unlocked(full)
            return AppendResult(record_hash=record_hash)

    def append_prepared(self, planned: CommitBundle, *, expected_head: str) -> AppendResult:
        """Publish one semantically validated receipt-v2 bundle by compare-and-swap."""

        if type(planned) is not CommitBundle:
            raise TypeError("prepared publication requires a CommitBundle")
        validated = validate_commit_bundle(planned)
        if isinstance(validated, Reject):
            raise ValueError(f"{validated.code}: {thaw_json(validated.details)}")
        require(
            validated.expected_head == expected_head,
            "prepared record is bound to another head",
        )
        full = thaw_json(validated.record)
        require(isinstance(full, Mapping), "validated record must be an object")

        with self._lock():
            current_head = self._head_unlocked()
            require(current_head == expected_head, "commit conflict: authoritative log head changed")
            self._append_line_atomically_unlocked(full)
        return AppendResult(record_hash=validated.record_hash)

    def _append_line_atomically_unlocked(self, obj: Mapping[str, Any]) -> None:
        existing = self.path.read_bytes() if self.path.exists() else b""
        require(not existing or existing.endswith(b"\n"), "log corruption: final record is incomplete")
        existing_records = (
            json.loads(line)
            for line in existing.decode("utf-8").splitlines()
            if line.strip()
        )
        self._verify_records(existing_records)
        next_bytes = existing + canonical_json_bytes(obj)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(next_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary_path), str(self.path))
            try:
                directory_descriptor = os.open(str(self.path.parent), os.O_DIRECTORY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            except (AttributeError, OSError):
                pass
        finally:
            try:
                if temporary_path.exists():
                    temporary_path.unlink()
            except OSError:
                pass

    def iter_raw_records(self) -> Iterator[Mapping[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def iter_records(self) -> Iterator[Mapping[str, Any]]:
        """Iterate the legacy logical projection consumed by indexes and doctor."""

        for record in self.iter_raw_records():
            if record.get("schema") == _LOG_SCHEMA_V2 and record.get("op") == "commit_bundle":
                yield from _logical_commit_records(record)
            else:
                yield record

    def verify(self) -> None:
        self._verify_records(self.iter_raw_records())

    @staticmethod
    def _verify_records(records: Iterator[Mapping[str, Any]]) -> None:
        previous = ""
        for index, record in enumerate(records, start=1):
            schema = record.get("schema")
            require(schema in {_LOG_SCHEMA_V1, _LOG_SCHEMA_V2}, f"log corruption: bad schema at line {index}")
            record_hash = record.get("record_hash")
            require(
                isinstance(record_hash, str) and bool(REF_RE.fullmatch(record_hash)),
                f"log corruption: bad record_hash at line {index}",
            )
            require(
                str(record.get("prev_record_hash", "")) == previous,
                f"log corruption: prev_record_hash mismatch at line {index}",
            )
            if schema == _LOG_SCHEMA_V1:
                expected = stable_sha256(_strip_record_hash(record))
                require(
                    expected == record_hash,
                    f"log corruption: record_hash mismatch at line {index}",
                )
            else:
                validated = validate_commit_record(record, allow_legacy_receipt=True)
                if isinstance(validated, Reject):
                    raise ValidationError(
                        f"log corruption: record_hash mismatch ({validated.code}) at line {index}: "
                        f"{thaw_json(validated.details)}"
                    )
                require(
                    validated.record_hash == record_hash,
                    f"log corruption: record_hash mismatch at line {index}",
                )
            previous = record_hash

    def stats(self) -> dict[str, Any]:
        count = 0
        head = ""
        for record in self.iter_raw_records():
            count += 1
            head = str(record.get("record_hash", ""))
        return {"event_count": count, "head": head}
