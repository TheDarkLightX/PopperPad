"""Strict bytes-boundary JSONL data adapter shell.

Reads one request per line from stdin (bytes), writes one response per line
to stdout (bytes). Uses strict canonical JSON parsing:

- Rejects duplicate object keys (at parse time via object_pairs_hook)
- Rejects trailing content after the JSON value
- Rejects non-UTF-8 input
- Rejects empty input
- Enforces canonical request bytes: received bytes must equal canonical
  JSON encoding of the parsed value (no alternate byte encodings accepted)
- Preserves caller-supplied wire headers (schema, protocol_version, binding_hash)
  — the shell does NOT replace or repair them
- All boundary failures return committed INVALID_INPUT responses

The shell never imports datetime, os, or other effectful modules for
parsing logic. It only uses sys.stdin/stdout for byte transport.
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import BinaryIO

from ..core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    REQUEST_SCHEMA,
    AdapterBinding,
    AdapterOperation,
    AdapterRequest,
    DataAdapterProfile,
    ExecutionContext,
    InvalidInput,
    InvalidInputCode,
    build_boundary_failure_response,
    require_sha256_ref,
)
from ..core.codec import canonical_json_bytes, sha256_bytes
from ..core.values import FrozenDict, JsonValue, freeze_json, thaw_json
from ..refinement.market_adapter import apply_data_adapter
from ..refinement.profiles.market_single_slot_v1 import load_profile, load_binding


MAX_REQUEST_BYTES = 1_048_576
_REQUEST_FIELDS = frozenset(
    {
        "schema",
        "protocol_version",
        "request_id",
        "case_id",
        "binding_hash",
        "operation",
        "state",
        "command",
        "execution_context",
        "expected_pre_state_hash",
    }
)
_EXECUTION_CONTEXT_FIELDS = frozenset({"time_class", "now_epoch_s"})


class StrictJSONParseError(Exception):
    """Raised when input bytes are not strict canonical JSON."""

    def __init__(self, code: InvalidInputCode, detail: str) -> None:
        self.code = code
        super().__init__(detail)


class RequestValidationError(Exception):
    """Typed failure while constructing a request from canonical JSON."""

    def __init__(self, code: InvalidInputCode, field_path: str, detail: str) -> None:
        self.code = code
        self.field_path = field_path
        super().__init__(detail)


def _reject_float(value: str) -> object:
    raise StrictJSONParseError(
        InvalidInputCode.FLOAT_NOT_ALLOWED,
        f"floating-point JSON value is not allowed: {value}",
    )


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """object_pairs_hook that rejects duplicate keys at parse time."""

    seen: set[str] = set()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise StrictJSONParseError(
                InvalidInputCode.DUPLICATE_JSON_KEY,
                f"duplicate key {key!r}",
            )
        seen.add(key)
        result[key] = value
    return result


def parse_canonical_json(data: bytes) -> object:
    """Parse bytes as strict canonical JSON.

    Rejects:
    - Non-UTF-8 bytes
    - Trailing content after the JSON value
    - Duplicate object keys (detected at parse time via object_pairs_hook)
    - Non-canonical byte encodings (received bytes must equal canonical
      JSON encoding of the parsed value)
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StrictJSONParseError(
            InvalidInputCode.INVALID_UTF8,
            f"non-utf-8 input: {exc}",
        ) from exc
    raw = data
    if not raw:
        raise StrictJSONParseError(
            InvalidInputCode.NON_CANONICAL_JSON,
            "empty input",
        )
    decoder = json.JSONDecoder(
        object_pairs_hook=_reject_duplicate_pairs,
        parse_float=_reject_float,
        parse_constant=_reject_float,
    )
    try:
        value, end = decoder.raw_decode(text)
    except StrictJSONParseError:
        raise
    except json.JSONDecodeError as exc:
        raise StrictJSONParseError(
            InvalidInputCode.NON_CANONICAL_JSON,
            f"invalid json: {exc}",
        ) from exc
    if text[end:].strip():
        raise StrictJSONParseError(
            InvalidInputCode.NON_CANONICAL_JSON,
            "trailing content after json value",
        )
    # Enforce canonical bytes: received bytes must equal canonical encoding.
    # The canonical_json_bytes function appends a trailing newline for file
    # storage; in JSONL the newline is the line delimiter, not content, so
    # we compare against the canonical form without the trailing newline.
    try:
        canonical = canonical_json_bytes(value).rstrip(b"\n")
    except (TypeError, ValueError) as exc:
        raise StrictJSONParseError(
            InvalidInputCode.FLOAT_NOT_ALLOWED,
            f"value is outside canonical integer JSON: {exc}",
        ) from exc
    if raw != canonical:
        raise StrictJSONParseError(
            InvalidInputCode.NON_CANONICAL_JSON,
            "input is not canonical JSON (byte encoding differs from canonical form)",
        )
    return value


def serialize_json(value: object) -> bytes:
    """Serialize a value as canonical JSON bytes (without trailing newline)."""

    plain = thaw_json(value) if isinstance(value, (FrozenDict, tuple)) else value
    encoded = json.dumps(plain, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return encoded.encode("utf-8")


def process_line(
    line: bytes,
    profile: DataAdapterProfile,
    binding: AdapterBinding,
) -> bytes:
    """Process one JSONL line and return the response bytes."""

    input_bytes_hash = sha256_bytes(line)
    if len(line) > MAX_REQUEST_BYTES:
        return _invalid_input_bytes(
            binding,
            InvalidInputCode.INPUT_TOO_LARGE,
            "$",
            f"request is {len(line)} bytes; maximum is {MAX_REQUEST_BYTES}",
            input_bytes_hash,
        )

    try:
        raw = parse_canonical_json(line)
    except StrictJSONParseError as exc:
        return _invalid_input_bytes(binding, exc.code, "$", str(exc), input_bytes_hash)

    if not isinstance(raw, dict):
        return _invalid_input_bytes(
            binding,
            InvalidInputCode.NON_CANONICAL_JSON,
            "$",
            "request must be a JSON object",
            input_bytes_hash,
        )

    try:
        frozen = freeze_json(raw)
    except (TypeError, ValueError) as exc:
        return _invalid_input_bytes(
            binding,
            InvalidInputCode.FLOAT_NOT_ALLOWED,
            "$",
            str(exc),
            input_bytes_hash,
        )
    if not isinstance(frozen, FrozenDict):
        return _invalid_input_bytes(
            binding,
            InvalidInputCode.NON_CANONICAL_JSON,
            "$",
            "request must be a JSON object",
            input_bytes_hash,
        )

    try:
        request = _build_request(frozen)
    except RequestValidationError as exc:
        return _invalid_input_bytes(
            binding,
            exc.code,
            exc.field_path,
            str(exc),
            input_bytes_hash,
        )

    response = apply_data_adapter(profile, binding, request)
    return serialize_json(response.as_json())


def _build_request(frozen: FrozenDict[JsonValue]) -> AdapterRequest:
    """Construct a typed AdapterRequest from parsed JSON.

    Preserves caller-supplied wire headers — does NOT replace schema,
    protocol_version, or binding_hash with local values.
    """

    _require_exact_fields(frozen, _REQUEST_FIELDS, "$")

    request_id = frozen.get("request_id")
    case_id = frozen.get("case_id")
    if type(request_id) is not str or not request_id:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.request_id",
            "request_id must be a non-empty string",
        )
    if type(case_id) is not str or not case_id:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.case_id",
            "case_id must be a non-empty string",
        )

    schema = frozen.get("schema")
    if type(schema) is not str:
        raise RequestValidationError(InvalidInputCode.SCHEMA_MISMATCH, "$.schema", "schema must be a string")
    if schema != REQUEST_SCHEMA:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.schema",
            f"schema must be {REQUEST_SCHEMA}, got {schema!r}",
        )

    protocol_version = frozen.get("protocol_version")
    if type(protocol_version) is not str:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.protocol_version",
            "protocol_version must be a string",
        )
    if protocol_version != ADAPTER_PROTOCOL_VERSION:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.protocol_version",
            f"protocol_version must be {ADAPTER_PROTOCOL_VERSION}, got {protocol_version!r}",
        )

    binding_hash = frozen.get("binding_hash")
    try:
        require_sha256_ref(binding_hash, "binding_hash")
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            InvalidInputCode.BINDING_MISMATCH,
            "$.binding_hash",
            str(exc),
        ) from exc

    operation_raw = frozen.get("operation")
    if type(operation_raw) is not str:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.operation",
            "operation must be a string",
        )
    try:
        operation = AdapterOperation(operation_raw)
    except ValueError as exc:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.operation",
            str(exc),
        ) from exc

    state_raw = frozen.get("state")
    if not isinstance(state_raw, FrozenDict):
        raise RequestValidationError(
            InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
            "$.state",
            "state must be a JSON object",
        )

    command_raw = frozen.get("command")
    if command_raw is not None and not isinstance(command_raw, FrozenDict):
        raise RequestValidationError(
            InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
            "$.command",
            "command must be null or a JSON object",
        )
    if operation is AdapterOperation.STEP and command_raw is None:
        raise RequestValidationError(
            InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
            "$.command",
            "step operation requires a command",
        )
    if operation is AdapterOperation.VALIDATE_STATE and command_raw is not None:
        raise RequestValidationError(
            InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
            "$.command",
            "validate_state operation requires a null command",
        )

    ctx_raw = frozen.get("execution_context")
    if not isinstance(ctx_raw, FrozenDict):
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.execution_context",
            "execution_context must be a JSON object",
        )
    _require_exact_fields(ctx_raw, _EXECUTION_CONTEXT_FIELDS, "$.execution_context")
    time_class = ctx_raw.get("time_class")
    now_epoch_s = ctx_raw.get("now_epoch_s")
    if type(time_class) is not str:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.execution_context.time_class",
            "execution_context.time_class must be a string",
        )
    if type(now_epoch_s) is not int or isinstance(now_epoch_s, bool):
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.execution_context.now_epoch_s",
            "execution_context.now_epoch_s must be an integer",
        )
    try:
        ctx = ExecutionContext(time_class=time_class, now_epoch_s=now_epoch_s)
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            "$.execution_context",
            str(exc),
        ) from exc

    expected_hash = frozen.get("expected_pre_state_hash")
    try:
        require_sha256_ref(expected_hash, "expected_pre_state_hash")
    except (TypeError, ValueError) as exc:
        raise RequestValidationError(
            InvalidInputCode.PRE_STATE_HASH_MISMATCH,
            "$.expected_pre_state_hash",
            str(exc),
        ) from exc

    return AdapterRequest(
        schema=schema,
        protocol_version=protocol_version,
        request_id=request_id,
        case_id=case_id,
        binding_hash=binding_hash,
        operation=operation,
        state=state_raw,
        command=command_raw,
        execution_context=ctx,
        expected_pre_state_hash=expected_hash,
    )


def _require_exact_fields(
    value: FrozenDict[JsonValue],
    expected: frozenset[str],
    field_path: str,
) -> None:
    actual = frozenset(value)
    unknown = sorted(actual - expected)
    if unknown:
        raise RequestValidationError(
            InvalidInputCode.UNKNOWN_FIELD,
            field_path,
            f"unknown fields: {unknown}",
        )
    missing = sorted(expected - actual)
    if missing:
        raise RequestValidationError(
            InvalidInputCode.SCHEMA_MISMATCH,
            field_path,
            f"missing required fields: {missing}",
        )


def _invalid_input_bytes(
    binding: AdapterBinding,
    code: InvalidInputCode,
    field_path: str,
    detail: str,
    input_bytes_hash: str,
) -> bytes:
    """Build a committed INVALID_INPUT response without inventing a request."""

    invalid = InvalidInput(code=code, field_path=field_path, detail=detail)
    response = build_boundary_failure_response(
        binding_hash=binding.hash(),
        input_bytes_hash=input_bytes_hash,
        invalid=invalid,
    )
    return serialize_json(response.as_json())


def run_jsonl_shell(stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Run the JSONL shell: read lines from stdin, write responses to stdout."""

    profile = load_profile()
    binding = load_binding(profile)
    while True:
        line = stdin.readline(MAX_REQUEST_BYTES + 2)
        if not line:
            break
        if len(line) > MAX_REQUEST_BYTES and not line.endswith((b"\n", b"\r")):
            digest = hashlib.sha256()
            digest.update(line)
            while line and not line.endswith((b"\n", b"\r")):
                line = stdin.readline(MAX_REQUEST_BYTES + 2)
                digest.update(line)
            response_bytes = _invalid_input_bytes(
                binding,
                InvalidInputCode.INPUT_TOO_LARGE,
                "$",
                f"request exceeds {MAX_REQUEST_BYTES} bytes",
                "sha256:" + digest.hexdigest(),
            )
            stdout.write(response_bytes)
            stdout.write(b"\n")
            stdout.flush()
            continue
        payload = line.rstrip(b"\n\r")
        if not payload:
            continue
        response_bytes = process_line(payload, profile, binding)
        stdout.write(response_bytes)
        stdout.write(b"\n")
        stdout.flush()
