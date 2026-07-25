"""Generic data-only transition adapter protocol values.

This module defines the immutable, domain-separated value algebra that bridges
external finite-state models (ESSO, spreadsheets, test harnesses, model
checkers, future WASM validators, replay corpora) to an authoritative
PopperPad functional core.

The adapter is a *deterministic semantic bridge*: it receives canonical
profile data, immutable abstract state data, immutable command data, and
immutable execution-context data; it projects them into core values, applies
the core transition, and projects the decision back into canonical data.

It must NOT read files, access databases, read clocks, access environment
variables, call networks, invoke verifiers, publish objects, deliver payments,
resolve content-addressed references, dynamically import code, accept
caller-supplied functions or class names, mutate the source tree, or choose
or alter market semantics.

Binding graph (acyclic)::

    DataAdapterProfile
        ↓ hash
    profile_hash

    SourceManifest(profile_hash, sorted source bindings)
        ↓ hash
    source_manifest_hash

    AdapterBinding(profile_hash, source_manifest_hash, model_ir_hash, ...)
        ↓ hash
    binding_hash

    AdapterRequest(binding_hash, ...)
    AdapterResponse(binding_hash, ...)

No cycle exists: the profile hash depends only on semantic content,
the manifest hash depends on the profile hash, and the binding hash
depends on both. Requests and responses carry the final binding_hash.

Dependency direction::

    market.py
        ↑
    adapter_protocol.py
        ↑
    refinement/market_adapter.py
        ↑
    shells/data_adapter_jsonl.py

``market.py`` must never import this module or the adapter/shell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import ClassVar, TypeAlias

from .codec import CANONICAL_JSON_VERSION, canonical_hash
from .values import (
    Amount,
    ClosedStrEnum,
    DeeplyImmutable,
    FrozenDict,
    JsonValue,
    freeze_json,
)


# ---------------------------------------------------------------------------
# Schema tags — distinct per wire type to prevent cross-type decoding.
# ---------------------------------------------------------------------------

PROFILE_SCHEMA = "popperpad/data-adapter-profile/v1"
BINDING_SCHEMA = "popperpad/data-adapter-binding/v1"
REQUEST_SCHEMA = "popperpad/data-adapter-request/v1"
RESPONSE_SCHEMA = "popperpad/data-adapter-response/v1"
BOUNDARY_RESPONSE_SCHEMA = "popperpad/data-adapter-boundary-response/v1"
SOURCE_MANIFEST_SCHEMA = "popperpad/data-adapter-source-manifest/v1"
ADAPTER_PROTOCOL_VERSION = "v1"


# ---------------------------------------------------------------------------
# Hash domains — distinct, domain-separated, never reused across value kinds.
# ---------------------------------------------------------------------------

PROFILE_HASH_DOMAIN = "popperpad-data-adapter-profile/v1"
BINDING_HASH_DOMAIN = "popperpad-data-adapter-binding/v1"
REQUEST_HASH_DOMAIN = "popperpad-data-adapter-request/v1"
RESPONSE_HASH_DOMAIN = "popperpad-data-adapter-response/v1"
BOUNDARY_RESPONSE_HASH_DOMAIN = "popperpad-data-adapter-boundary-response/v1"
SOURCE_MANIFEST_HASH_DOMAIN = "popperpad-data-adapter-source-manifest/v1"


# ---------------------------------------------------------------------------
# Strict digest validation — exact sha256:<64 lowercase hex>, nowhere weaker.
# ---------------------------------------------------------------------------

_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def require_sha256_ref(value: object, field_path: str) -> str:
    """Validate that *value* is exactly ``sha256:<64 lowercase hex>``."""
    if type(value) is not str or _SHA256_REF_RE.fullmatch(value) is None:
        raise ValueError(f"{field_path} must be sha256:<64 lowercase hex>")
    return value


def _require_nonempty_str(value: object, field_path: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field_path} must be a non-empty string")
    return value


def _require_exact_int(value: object, field_path: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError(f"{field_path} must be an exact integer")
    return value


# ---------------------------------------------------------------------------
# Closed operations — no dynamic method names or module paths.
# ---------------------------------------------------------------------------


class AdapterOperation(ClosedStrEnum):
    __slots__ = ()

    VALIDATE_STATE: ClassVar[AdapterOperation]
    STEP: ClassVar[AdapterOperation]
    _symbols = (
        ("VALIDATE_STATE", "validate_state"),
        ("STEP", "step"),
    )


# ---------------------------------------------------------------------------
# Closed decision kinds — INVALID_INPUT is a boundary failure, not a market Reject.
# ---------------------------------------------------------------------------


class AdapterDecisionKind(ClosedStrEnum):
    __slots__ = ()

    INVALID_INPUT: ClassVar[AdapterDecisionKind]
    REJECT: ClassVar[AdapterDecisionKind]
    ACCEPT: ClassVar[AdapterDecisionKind]
    COMMITTED_FAILURE: ClassVar[AdapterDecisionKind]
    _symbols = (
        ("INVALID_INPUT", "invalid_input"),
        ("REJECT", "reject"),
        ("ACCEPT", "accept"),
        ("COMMITTED_FAILURE", "committed_failure"),
    )


# ---------------------------------------------------------------------------
# Closed invalid-input reason codes — boundary failures, not semantic rejections.
# ---------------------------------------------------------------------------


class InvalidInputCode(ClosedStrEnum):
    __slots__ = ()

    NON_CANONICAL_JSON: ClassVar[InvalidInputCode]
    INVALID_UTF8: ClassVar[InvalidInputCode]
    DUPLICATE_JSON_KEY: ClassVar[InvalidInputCode]
    FLOAT_NOT_ALLOWED: ClassVar[InvalidInputCode]
    UNKNOWN_FIELD: ClassVar[InvalidInputCode]
    SCHEMA_MISMATCH: ClassVar[InvalidInputCode]
    PROFILE_MISMATCH: ClassVar[InvalidInputCode]
    BINDING_MISMATCH: ClassVar[InvalidInputCode]
    SOURCE_MANIFEST_MISMATCH: ClassVar[InvalidInputCode]
    MODEL_HASH_MISMATCH: ClassVar[InvalidInputCode]
    PRE_STATE_HASH_MISMATCH: ClassVar[InvalidInputCode]
    INPUT_TOO_LARGE: ClassVar[InvalidInputCode]
    ABSTRACT_STATE_OUT_OF_DOMAIN: ClassVar[InvalidInputCode]
    ABSTRACT_COMMAND_OUT_OF_DOMAIN: ClassVar[InvalidInputCode]
    _symbols = (
        ("NON_CANONICAL_JSON", "non_canonical_json"),
        ("INVALID_UTF8", "invalid_utf8"),
        ("DUPLICATE_JSON_KEY", "duplicate_json_key"),
        ("FLOAT_NOT_ALLOWED", "float_not_allowed"),
        ("UNKNOWN_FIELD", "unknown_field"),
        ("SCHEMA_MISMATCH", "schema_mismatch"),
        ("PROFILE_MISMATCH", "profile_mismatch"),
        ("BINDING_MISMATCH", "binding_mismatch"),
        ("SOURCE_MANIFEST_MISMATCH", "source_manifest_mismatch"),
        ("MODEL_HASH_MISMATCH", "model_hash_mismatch"),
        ("PRE_STATE_HASH_MISMATCH", "pre_state_hash_mismatch"),
        ("INPUT_TOO_LARGE", "input_too_large"),
        ("ABSTRACT_STATE_OUT_OF_DOMAIN", "abstract_state_out_of_domain"),
        ("ABSTRACT_COMMAND_OUT_OF_DOMAIN", "abstract_command_out_of_domain"),
    )


# ---------------------------------------------------------------------------
# Typed invalid-input value — closed code + structured detail, never a bare string.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InvalidInput(DeeplyImmutable):
    code: InvalidInputCode
    field_path: str
    detail: str

    def __post_init__(self) -> None:
        if type(self.code) is not InvalidInputCode:
            raise TypeError("InvalidInput.code must be an InvalidInputCode")
        _require_nonempty_str(self.field_path, "InvalidInput.field_path")
        if type(self.detail) is not str:
            raise TypeError("InvalidInput.detail must be a string")
        DeeplyImmutable.__post_init__(self)

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "code": self.code.value,
                "field_path": self.field_path,
                "detail": self.detail,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Source manifest — checked-in, read-only binding of semantic source files.
#
# The manifest references the profile_hash (acyclic: manifest → profile, never
# profile → manifest). Source file paths are normalized, relative, traversal-
# free, sorted, and unique. Digests are exact sha256:<64hex>.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFileBinding(DeeplyImmutable):
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _validate_source_path(self.path, "SourceFileBinding.path")
        require_sha256_ref(self.sha256, "SourceFileBinding.sha256")
        DeeplyImmutable.__post_init__(self)


def _validate_source_path(path: object, field_path: str) -> str:
    if type(path) is not str or not path:
        raise ValueError(f"{field_path} must be a non-empty string")
    if path.startswith("/"):
        raise ValueError(f"{field_path} must be relative, not absolute: {path}")
    if ".." in path.split("/"):
        raise ValueError(f"{field_path} must not contain traversal: {path}")
    if "." in path.split("/"):
        raise ValueError(f"{field_path} must not contain a dot segment: {path}")
    if "\\" in path:
        raise ValueError(f"{field_path} must not contain backslashes: {path}")
    if "//" in path:
        raise ValueError(f"{field_path} must not contain double slashes: {path}")
    return path


@dataclass(frozen=True, slots=True)
class SourceManifest(DeeplyImmutable):
    schema: str
    repository: str
    commit: str
    files: tuple[SourceFileBinding, ...]
    profile_hash: str
    codec_version: str

    def __post_init__(self) -> None:
        if self.schema != SOURCE_MANIFEST_SCHEMA:
            raise ValueError("SourceManifest.schema mismatch")
        _require_nonempty_str(self.repository, "SourceManifest.repository")
        if type(self.commit) is not str or not _GIT_COMMIT_RE.fullmatch(self.commit):
            raise ValueError("SourceManifest.commit must be a 40-char lowercase hex git commit")
        if not isinstance(self.files, tuple) or not self.files:
            raise ValueError("SourceManifest.files must be a non-empty tuple")
        if any(type(value) is not SourceFileBinding for value in self.files):
            raise TypeError("SourceManifest.files must contain SourceFileBinding values")
        paths = [binding.path for binding in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("SourceManifest.files must have unique paths")
        if paths != sorted(paths):
            raise ValueError("SourceManifest.files must be sorted by path")
        require_sha256_ref(self.profile_hash, "SourceManifest.profile_hash")
        if self.codec_version != CANONICAL_JSON_VERSION:
            raise ValueError("SourceManifest.codec_version mismatch")
        DeeplyImmutable.__post_init__(self)

    def hash(self) -> str:
        return canonical_hash(SOURCE_MANIFEST_HASH_DOMAIN, self.as_json())

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "repository": self.repository,
                "commit": self.commit,
                "files": tuple(
                    {"path": binding.path, "sha256": binding.sha256}
                    for binding in self.files
                ),
                "profile_hash": self.profile_hash,
                "codec_version": self.codec_version,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Generic data-adapter profile — immutable, data-only, no market-specific fields.
#
# The semantic_profile payload is an opaque FrozenDict. Domain-specific typed
# profiles (e.g. SingleSlotMarketProfile in A2) parse it. The generic protocol
# only requires it to be a FrozenDict and deeply immutable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DataAdapterProfile(DeeplyImmutable):
    """Immutable, data-only adapter profile.

    No field may contain a callable, module, class, file path selected by the
    request, URL, executable source, dynamic resolver, database handle, or
    shell client. All semantics are data.

    The profile does NOT contain source_manifest_hash — that would create a
    hash cycle. The binding is established by AdapterBinding.
    """

    schema: str
    profile_id: str
    profile_version: str
    protocol_version: str
    abstraction_id: str
    codec_version: str
    semantic_profile: FrozenDict[JsonValue]
    explicit_nonclaims: tuple[str, ...]

    def __post_init__(self) -> None:
        self._validate_header()
        self._validate_payload()
        DeeplyImmutable.__post_init__(self)

    def _validate_header(self) -> None:
        if self.schema != PROFILE_SCHEMA:
            raise ValueError("DataAdapterProfile.schema mismatch")
        for name, value in (
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("protocol_version", self.protocol_version),
            ("abstraction_id", self.abstraction_id),
        ):
            _require_nonempty_str(value, f"DataAdapterProfile.{name}")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("DataAdapterProfile.protocol_version mismatch")
        if self.codec_version != CANONICAL_JSON_VERSION:
            raise ValueError("DataAdapterProfile.codec_version mismatch")

    def _validate_payload(self) -> None:
        if type(self.semantic_profile) is not FrozenDict:
            raise TypeError("DataAdapterProfile.semantic_profile must be a FrozenDict")
        if type(self.explicit_nonclaims) is not tuple:
            raise TypeError("DataAdapterProfile.explicit_nonclaims must be a tuple")
        if not all(type(value) is str and value for value in self.explicit_nonclaims):
            raise TypeError("DataAdapterProfile.explicit_nonclaims must contain non-empty strings")
        if list(self.explicit_nonclaims) != sorted(self.explicit_nonclaims):
            raise ValueError("DataAdapterProfile.explicit_nonclaims must be sorted")
        if len(set(self.explicit_nonclaims)) != len(self.explicit_nonclaims):
            raise ValueError("DataAdapterProfile.explicit_nonclaims must have no duplicates")

    def hash(self) -> str:
        return canonical_hash(PROFILE_HASH_DOMAIN, self.as_json())

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "protocol_version": self.protocol_version,
                "abstraction_id": self.abstraction_id,
                "codec_version": self.codec_version,
                "semantic_profile": self.semantic_profile,
                "explicit_nonclaims": self.explicit_nonclaims,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Adapter binding — acyclic binding of profile, source manifest, model IR, and
# implementation identity. Requests and responses carry binding_hash.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterBinding(DeeplyImmutable):
    """Acyclic binding of a semantic profile to its source manifest and implementation.

    The binding hash is the final commitment used by requests and responses.
    It depends on profile_hash, source_manifest_hash, model_ir_hash, protocol
    version, and adapter implementation ID. None of these depend on the
    binding hash, so the graph is acyclic.
    """

    schema: str
    profile_hash: str
    source_manifest_hash: str
    model_ir_hash: str | None
    protocol_version: str
    adapter_implementation_id: str

    def __post_init__(self) -> None:
        if self.schema != BINDING_SCHEMA:
            raise ValueError("AdapterBinding.schema mismatch")
        require_sha256_ref(self.profile_hash, "AdapterBinding.profile_hash")
        require_sha256_ref(self.source_manifest_hash, "AdapterBinding.source_manifest_hash")
        if self.model_ir_hash is not None:
            require_sha256_ref(self.model_ir_hash, "AdapterBinding.model_ir_hash")
        _require_nonempty_str(self.protocol_version, "AdapterBinding.protocol_version")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("AdapterBinding.protocol_version mismatch")
        _require_nonempty_str(self.adapter_implementation_id, "AdapterBinding.adapter_implementation_id")
        DeeplyImmutable.__post_init__(self)

    def hash(self) -> str:
        return canonical_hash(BINDING_HASH_DOMAIN, self.as_json())

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "profile_hash": self.profile_hash,
                "source_manifest_hash": self.source_manifest_hash,
                "model_ir_hash": self.model_ir_hash,
                "protocol_version": self.protocol_version,
                "adapter_implementation_id": self.adapter_implementation_id,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Execution context — explicit time data, never read from the machine clock.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionContext(DeeplyImmutable):
    time_class: str
    now_epoch_s: int

    def __post_init__(self) -> None:
        _require_nonempty_str(self.time_class, "ExecutionContext.time_class")
        if type(self.now_epoch_s) is not int or isinstance(self.now_epoch_s, bool):
            raise TypeError("ExecutionContext.now_epoch_s must be an integer")
        if self.now_epoch_s < 0:
            raise ValueError("ExecutionContext.now_epoch_s must be non-negative")
        DeeplyImmutable.__post_init__(self)

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "time_class": self.time_class,
                "now_epoch_s": self.now_epoch_s,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Adapter request — immutable, carries binding_hash and abstract state/command.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterRequest(DeeplyImmutable):
    schema: str
    protocol_version: str
    request_id: str
    case_id: str
    binding_hash: str
    operation: AdapterOperation
    state: FrozenDict[JsonValue]
    command: FrozenDict[JsonValue] | None
    execution_context: ExecutionContext
    expected_pre_state_hash: str

    def __post_init__(self) -> None:
        self._validate_header()
        self._validate_binding()
        self._validate_operation_and_payload()
        require_sha256_ref(self.expected_pre_state_hash, "AdapterRequest.expected_pre_state_hash")
        DeeplyImmutable.__post_init__(self)

    def _validate_header(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise ValueError("AdapterRequest.schema mismatch")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("AdapterRequest.protocol_version mismatch")
        for name, value in (
            ("request_id", self.request_id),
            ("case_id", self.case_id),
        ):
            _require_nonempty_str(value, f"AdapterRequest.{name}")

    def _validate_binding(self) -> None:
        require_sha256_ref(self.binding_hash, "AdapterRequest.binding_hash")

    def _validate_operation_and_payload(self) -> None:
        if type(self.operation) is not AdapterOperation:
            raise TypeError("AdapterRequest.operation must be an AdapterOperation")
        if type(self.state) is not FrozenDict:
            raise TypeError("AdapterRequest.state must be a FrozenDict")
        if self.command is not None and type(self.command) is not FrozenDict:
            raise TypeError("AdapterRequest.command must be null or FrozenDict")
        if type(self.execution_context) is not ExecutionContext:
            raise TypeError("AdapterRequest.execution_context must be an ExecutionContext")
        if self.operation is AdapterOperation.STEP and self.command is None:
            raise ValueError("STEP operation requires a non-null command")
        if self.operation is AdapterOperation.VALIDATE_STATE and self.command is not None:
            raise ValueError("VALIDATE_STATE operation requires a null command")

    def hash(self) -> str:
        return canonical_hash(REQUEST_HASH_DOMAIN, self.as_json())

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "protocol_version": self.protocol_version,
                "request_id": self.request_id,
                "case_id": self.case_id,
                "binding_hash": self.binding_hash,
                "operation": self.operation.value,
                "state": self.state,
                "command": self.command,
                "execution_context": self.execution_context.as_json(),
                "expected_pre_state_hash": self.expected_pre_state_hash,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Adapter response — immutable, carries the full decision as canonical data.
#
# The response_commitment is verified during __post_init__: it recomputes the
# hash of the response body (everything except response_commitment) and
# requires it to match. This means dataclasses.replace with a stale commitment
# will fail, because changing any field invalidates the commitment.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterResponse(DeeplyImmutable):
    schema: str
    protocol_version: str
    request_id: str
    case_id: str
    binding_hash: str
    request_hash: str
    decision_kind: AdapterDecisionKind
    reason_code: str | None
    reason_details: FrozenDict[JsonValue]
    pre_state: FrozenDict[JsonValue]
    pre_state_hash: str
    post_state: FrozenDict[JsonValue] | None
    post_state_hash: str | None
    effects: tuple[FrozenDict[JsonValue], ...]
    effect_plan_hash: str | None
    receipt: FrozenDict[JsonValue] | None
    state_violations: tuple[FrozenDict[JsonValue], ...]
    projection_warnings: tuple[str, ...]
    response_commitment: str

    def __post_init__(self) -> None:
        self._validate_header()
        self._validate_decision_invariants()
        self._validate_hashes()
        self._verify_response_commitment()
        DeeplyImmutable.__post_init__(self)

    def _validate_header(self) -> None:
        if self.schema != RESPONSE_SCHEMA:
            raise ValueError("AdapterResponse.schema mismatch")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("AdapterResponse.protocol_version mismatch")
        for name, value in (
            ("request_id", self.request_id),
            ("case_id", self.case_id),
        ):
            _require_nonempty_str(value, f"AdapterResponse.{name}")
        if type(self.reason_details) is not FrozenDict:
            raise TypeError("reason_details must be a FrozenDict")
        if type(self.pre_state) is not FrozenDict:
            raise TypeError("pre_state must be a FrozenDict")
        if self.post_state is not None and type(self.post_state) is not FrozenDict:
            raise TypeError("post_state must be a FrozenDict when present")
        if type(self.effects) is not tuple:
            raise TypeError("effects must be a tuple")
        if any(type(value) is not FrozenDict for value in self.effects):
            raise TypeError("effects must contain FrozenDict values")
        if self.receipt is not None and type(self.receipt) is not FrozenDict:
            raise TypeError("receipt must be a FrozenDict when present")
        if type(self.state_violations) is not tuple:
            raise TypeError("state_violations must be a tuple")
        if any(type(value) is not FrozenDict for value in self.state_violations):
            raise TypeError("state_violations must contain FrozenDict values")
        if type(self.projection_warnings) is not tuple:
            raise TypeError("projection_warnings must be a tuple")
        if not all(type(value) is str for value in self.projection_warnings):
            raise TypeError("projection_warnings must contain strings")

    def _validate_decision_invariants(self) -> None:
        kind = self.decision_kind
        if type(kind) is not AdapterDecisionKind:
            raise TypeError("decision_kind must be an AdapterDecisionKind")
        if kind is AdapterDecisionKind.INVALID_INPUT:
            self._assert_invalid_input_shape()
        elif kind is AdapterDecisionKind.REJECT:
            self._assert_reject_shape()
        elif kind is AdapterDecisionKind.ACCEPT:
            self._assert_accept_shape()
        elif kind is AdapterDecisionKind.COMMITTED_FAILURE:
            self._assert_committed_failure_shape()

    def _assert_invalid_input_shape(self) -> None:
        if self.post_state is not None:
            raise ValueError("INVALID_INPUT must have null post_state")
        if self.post_state_hash is not None:
            raise ValueError("INVALID_INPUT must have null post_state_hash")
        if self.effects:
            raise ValueError("INVALID_INPUT must have empty effects")
        if self.effect_plan_hash is not None:
            raise ValueError("INVALID_INPUT must have null effect_plan_hash")
        if self.receipt is not None:
            raise ValueError("INVALID_INPUT must have null receipt")
        if type(self.reason_code) is not str or not self.reason_code:
            raise ValueError("INVALID_INPUT requires a non-empty reason_code")
        try:
            code = InvalidInputCode(self.reason_code)
        except ValueError as exc:
            raise ValueError(
                "INVALID_INPUT reason_code must be a closed InvalidInputCode"
            ) from exc
        if self.reason_details.get("code") != code.value:
            raise ValueError("INVALID_INPUT reason_details.code must match reason_code")
        _require_nonempty_str(
            self.reason_details.get("field_path"),
            "AdapterResponse.reason_details.field_path",
        )
        if type(self.reason_details.get("detail")) is not str:
            raise TypeError("AdapterResponse.reason_details.detail must be a string")

    def _assert_reject_shape(self) -> None:
        if type(self.reason_code) is not str or not self.reason_code:
            raise ValueError("REJECT requires a non-empty reason_code")
        if self.post_state is None:
            raise ValueError("REJECT requires non-null post_state equal to pre_state")
        if self.post_state != self.pre_state:
            raise ValueError("REJECT post_state must equal pre_state")
        if self.post_state_hash is None:
            raise ValueError("REJECT requires non-null post_state_hash equal to pre_state_hash")
        if self.post_state_hash != self.pre_state_hash:
            raise ValueError("REJECT post_state_hash must equal pre_state_hash")
        if self.effects:
            raise ValueError("REJECT must have empty effects")
        if self.effect_plan_hash is not None:
            raise ValueError("REJECT must have null effect_plan_hash")
        if self.receipt is not None:
            raise ValueError("REJECT must have null receipt")

    def _assert_accept_shape(self) -> None:
        if self.reason_code is not None:
            raise ValueError("ACCEPT must have null reason_code")
        if self.post_state is None:
            raise ValueError("ACCEPT requires non-null post_state")
        if self.post_state_hash is None:
            raise ValueError("ACCEPT requires non-null post_state_hash")
        if self.effect_plan_hash is None:
            raise ValueError("ACCEPT requires non-null effect_plan_hash")
        if self.receipt is None:
            raise ValueError("ACCEPT requires non-null receipt")

    def _assert_committed_failure_shape(self) -> None:
        if type(self.reason_code) is not str or not self.reason_code:
            raise ValueError("COMMITTED_FAILURE requires a non-empty reason_code")
        if self.post_state is None:
            raise ValueError("COMMITTED_FAILURE requires non-null post_state")
        if self.post_state_hash is None:
            raise ValueError("COMMITTED_FAILURE requires non-null post_state_hash")
        if self.effect_plan_hash is None:
            raise ValueError("COMMITTED_FAILURE requires non-null effect_plan_hash")
        if self.receipt is None:
            raise ValueError("COMMITTED_FAILURE requires non-null receipt")

    def _validate_hashes(self) -> None:
        require_sha256_ref(self.binding_hash, "AdapterResponse.binding_hash")
        require_sha256_ref(self.request_hash, "AdapterResponse.request_hash")
        require_sha256_ref(self.pre_state_hash, "AdapterResponse.pre_state_hash")
        require_sha256_ref(self.response_commitment, "AdapterResponse.response_commitment")
        if self.post_state_hash is not None:
            require_sha256_ref(self.post_state_hash, "AdapterResponse.post_state_hash")
        if self.effect_plan_hash is not None:
            require_sha256_ref(self.effect_plan_hash, "AdapterResponse.effect_plan_hash")

    def _verify_response_commitment(self) -> None:
        expected = canonical_hash(RESPONSE_HASH_DOMAIN, self._body_json())
        if self.response_commitment != expected:
            raise ValueError(
                "response_commitment does not match recomputed hash; "
                "use build_response to construct AdapterResponse"
            )

    def _body_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "protocol_version": self.protocol_version,
                "request_id": self.request_id,
                "case_id": self.case_id,
                "binding_hash": self.binding_hash,
                "request_hash": self.request_hash,
                "decision_kind": self.decision_kind.value,
                "reason_code": self.reason_code,
                "reason_details": self.reason_details,
                "pre_state": self.pre_state,
                "pre_state_hash": self.pre_state_hash,
                "post_state": self.post_state,
                "post_state_hash": self.post_state_hash,
                "effects": self.effects,
                "effect_plan_hash": self.effect_plan_hash,
                "receipt": self.receipt,
                "state_violations": self.state_violations,
                "projection_warnings": self.projection_warnings,
            }
        )
        assert isinstance(value, FrozenDict)
        return value

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "protocol_version": self.protocol_version,
                "request_id": self.request_id,
                "case_id": self.case_id,
                "binding_hash": self.binding_hash,
                "request_hash": self.request_hash,
                "decision_kind": self.decision_kind.value,
                "reason_code": self.reason_code,
                "reason_details": self.reason_details,
                "pre_state": self.pre_state,
                "pre_state_hash": self.pre_state_hash,
                "post_state": self.post_state,
                "post_state_hash": self.post_state_hash,
                "effects": self.effects,
                "effect_plan_hash": self.effect_plan_hash,
                "receipt": self.receipt,
                "state_violations": self.state_violations,
                "projection_warnings": self.projection_warnings,
                "response_commitment": self.response_commitment,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Boundary response — committed failure data for bytes that cannot produce a
# valid AdapterRequest. It deliberately has no request identity or request
# hash: fabricating either would claim a request existed when decoding failed.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundaryFailureResponse(DeeplyImmutable):
    schema: str
    protocol_version: str
    binding_hash: str
    input_bytes_hash: str
    decision_kind: AdapterDecisionKind
    reason_code: str
    reason_details: FrozenDict[JsonValue]
    response_commitment: str

    def __post_init__(self) -> None:
        if self.schema != BOUNDARY_RESPONSE_SCHEMA:
            raise ValueError("BoundaryFailureResponse.schema mismatch")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("BoundaryFailureResponse.protocol_version mismatch")
        require_sha256_ref(self.binding_hash, "BoundaryFailureResponse.binding_hash")
        require_sha256_ref(self.input_bytes_hash, "BoundaryFailureResponse.input_bytes_hash")
        require_sha256_ref(
            self.response_commitment,
            "BoundaryFailureResponse.response_commitment",
        )
        if self.decision_kind is not AdapterDecisionKind.INVALID_INPUT:
            raise ValueError("BoundaryFailureResponse.decision_kind must be INVALID_INPUT")
        try:
            code = InvalidInputCode(self.reason_code)
        except ValueError as exc:
            raise ValueError(
                "BoundaryFailureResponse.reason_code must be a closed InvalidInputCode"
            ) from exc
        if type(self.reason_details) is not FrozenDict:
            raise TypeError("BoundaryFailureResponse.reason_details must be a FrozenDict")
        if frozenset(self.reason_details) != frozenset({"code", "field_path", "detail"}):
            raise ValueError("BoundaryFailureResponse.reason_details fields mismatch")
        if self.reason_details.get("code") != code.value:
            raise ValueError(
                "BoundaryFailureResponse.reason_details.code must match reason_code"
            )
        _require_nonempty_str(
            self.reason_details.get("field_path"),
            "BoundaryFailureResponse.reason_details.field_path",
        )
        if type(self.reason_details.get("detail")) is not str:
            raise TypeError("BoundaryFailureResponse.reason_details.detail must be a string")
        expected = canonical_hash(BOUNDARY_RESPONSE_HASH_DOMAIN, self._body_json())
        if self.response_commitment != expected:
            raise ValueError(
                "boundary response_commitment does not match recomputed hash; "
                "use build_boundary_failure_response"
            )
        DeeplyImmutable.__post_init__(self)

    def _body_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "protocol_version": self.protocol_version,
                "binding_hash": self.binding_hash,
                "input_bytes_hash": self.input_bytes_hash,
                "decision_kind": self.decision_kind.value,
                "reason_code": self.reason_code,
                "reason_details": self.reason_details,
            }
        )
        assert isinstance(value, FrozenDict)
        return value

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                **self._body_json(),
                "response_commitment": self.response_commitment,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


# ---------------------------------------------------------------------------
# Response builder — computes response_commitment, then constructs final
# AdapterResponse in one step. The builder echoes binding fields from the
# request, not from a local profile, so the response commits to the request
# that was actually received.
# ---------------------------------------------------------------------------


def build_response(
    *,
    request: AdapterRequest,
    decision_kind: AdapterDecisionKind,
    reason_code: str | None,
    reason_details: FrozenDict[JsonValue] | dict[str, JsonValue],
    pre_state: FrozenDict[JsonValue],
    pre_state_hash: str,
    post_state: FrozenDict[JsonValue] | None,
    post_state_hash: str | None,
    effects: tuple[FrozenDict[JsonValue], ...] = (),
    effect_plan_hash: str | None = None,
    receipt: FrozenDict[JsonValue] | None = None,
    state_violations: tuple[FrozenDict[JsonValue], ...] = (),
    projection_warnings: tuple[str, ...] = (),
) -> AdapterResponse:
    """Construct an AdapterResponse with a verified response_commitment.

    The commitment is the domain-separated hash of the response body
    (everything except response_commitment). The builder echoes binding_hash
    and request identity from the request, not from a local profile.
    """

    details = reason_details if isinstance(reason_details, FrozenDict) else FrozenDict(reason_details)
    body = freeze_json(
        {
            "schema": RESPONSE_SCHEMA,
            "protocol_version": ADAPTER_PROTOCOL_VERSION,
            "request_id": request.request_id,
            "case_id": request.case_id,
            "binding_hash": request.binding_hash,
            "request_hash": request.hash(),
            "decision_kind": decision_kind.value,
            "reason_code": reason_code,
            "reason_details": details,
            "pre_state": pre_state,
            "pre_state_hash": pre_state_hash,
            "post_state": post_state,
            "post_state_hash": post_state_hash,
            "effects": effects,
            "effect_plan_hash": effect_plan_hash,
            "receipt": receipt,
            "state_violations": state_violations,
            "projection_warnings": projection_warnings,
        }
    )
    assert isinstance(body, FrozenDict)
    commitment = canonical_hash(RESPONSE_HASH_DOMAIN, body)
    return AdapterResponse(
        schema=RESPONSE_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id=request.request_id,
        case_id=request.case_id,
        binding_hash=request.binding_hash,
        request_hash=request.hash(),
        decision_kind=decision_kind,
        reason_code=reason_code,
        reason_details=details,
        pre_state=pre_state,
        pre_state_hash=pre_state_hash,
        post_state=post_state,
        post_state_hash=post_state_hash,
        effects=effects,
        effect_plan_hash=effect_plan_hash,
        receipt=receipt,
        state_violations=state_violations,
        projection_warnings=projection_warnings,
        response_commitment=commitment,
    )


def build_invalid_input_response(
    *,
    request: AdapterRequest,
    invalid: InvalidInput,
    pre_state: FrozenDict[JsonValue],
    pre_state_hash: str,
) -> AdapterResponse:
    """Construct an INVALID_INPUT response carrying a typed boundary failure."""

    return build_response(
        request=request,
        decision_kind=AdapterDecisionKind.INVALID_INPUT,
        reason_code=invalid.code.value,
        reason_details=invalid.as_json(),
        pre_state=pre_state,
        pre_state_hash=pre_state_hash,
        post_state=None,
        post_state_hash=None,
        effects=(),
        effect_plan_hash=None,
        receipt=None,
        state_violations=(),
        projection_warnings=(),
    )


def build_boundary_failure_response(
    *,
    binding_hash: str,
    input_bytes_hash: str,
    invalid: InvalidInput,
) -> BoundaryFailureResponse:
    """Commit a typed failure when raw bytes cannot form an AdapterRequest."""

    if type(invalid) is not InvalidInput:
        raise TypeError("invalid must be an InvalidInput")
    details = invalid.as_json()
    body = freeze_json(
        {
            "schema": BOUNDARY_RESPONSE_SCHEMA,
            "protocol_version": ADAPTER_PROTOCOL_VERSION,
            "binding_hash": binding_hash,
            "input_bytes_hash": input_bytes_hash,
            "decision_kind": AdapterDecisionKind.INVALID_INPUT.value,
            "reason_code": invalid.code.value,
            "reason_details": details,
        }
    )
    assert isinstance(body, FrozenDict)
    commitment = canonical_hash(BOUNDARY_RESPONSE_HASH_DOMAIN, body)
    return BoundaryFailureResponse(
        schema=BOUNDARY_RESPONSE_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        binding_hash=binding_hash,
        input_bytes_hash=input_bytes_hash,
        decision_kind=AdapterDecisionKind.INVALID_INPUT,
        reason_code=invalid.code.value,
        reason_details=details,
        response_commitment=commitment,
    )


# ---------------------------------------------------------------------------
# Public type aliases.
# ---------------------------------------------------------------------------

AdapterJsonValue: TypeAlias = JsonValue
