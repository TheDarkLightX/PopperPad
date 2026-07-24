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

from dataclasses import dataclass, field, replace
from typing import ClassVar, TypeAlias

from .codec import canonical_hash
from .values import (
    Amount,
    ClosedStrEnum,
    DeeplyImmutable,
    FrozenDict,
    JsonValue,
    freeze_json,
)


# ---------------------------------------------------------------------------
# Hash domains — distinct, domain-separated, never reused across value kinds.
# ---------------------------------------------------------------------------

PROFILE_HASH_DOMAIN = "popperpad-data-adapter-profile/v1"
REQUEST_HASH_DOMAIN = "popperpad-data-adapter-request/v1"
RESPONSE_HASH_DOMAIN = "popperpad-data-adapter-response/v1"
SOURCE_MANIFEST_HASH_DOMAIN = "popperpad-data-adapter-source-manifest/v1"

ADAPTER_SCHEMA = "popperpad/data-adapter-protocol/v1"
ADAPTER_PROTOCOL_VERSION = "v1"


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
    SOURCE_MANIFEST_MISMATCH: ClassVar[InvalidInputCode]
    MODEL_HASH_MISMATCH: ClassVar[InvalidInputCode]
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
        ("SOURCE_MANIFEST_MISMATCH", "source_manifest_mismatch"),
        ("MODEL_HASH_MISMATCH", "model_hash_mismatch"),
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
        if type(self.field_path) is not str or not self.field_path:
            raise ValueError("InvalidInput.field_path must be a non-empty string")
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
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFileBinding(DeeplyImmutable):
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if type(self.path) is not str or not self.path:
            raise ValueError("SourceFileBinding.path must be a non-empty string")
        if type(self.sha256) is not str or not self.sha256.startswith("sha256:"):
            raise ValueError("SourceFileBinding.sha256 must be sha256:<64hex>")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class SourceManifest(DeeplyImmutable):
    schema: str
    repository: str
    commit: str
    files: tuple[SourceFileBinding, ...]
    profile_hash: str
    codec_version: str

    def __post_init__(self) -> None:
        if self.schema != "popperpad/data-adapter-source-manifest/v1":
            raise ValueError("SourceManifest.schema mismatch")
        if type(self.repository) is not str or not self.repository:
            raise ValueError("SourceManifest.repository must be non-empty")
        if type(self.commit) is not str or not self.commit:
            raise ValueError("SourceManifest.commit must be non-empty")
        if not isinstance(self.files, tuple) or not self.files:
            raise ValueError("SourceManifest.files must be a non-empty tuple")
        if any(type(value) is not SourceFileBinding for value in self.files):
            raise TypeError("SourceManifest.files must contain SourceFileBinding values")
        if type(self.profile_hash) is not str or not self.profile_hash.startswith("sha256:"):
            raise ValueError("SourceManifest.profile_hash must be sha256:<64hex>")
        if type(self.codec_version) is not str or not self.codec_version:
            raise ValueError("SourceManifest.codec_version must be non-empty")
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
# Adapter profile — immutable, data-only, no callables/modules/classes/paths.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NumericBounds(DeeplyImmutable):
    min_atoms: int
    max_atoms: int

    def __post_init__(self) -> None:
        if type(self.min_atoms) is not int or type(self.max_atoms) is not int:
            raise TypeError("NumericBounds bounds must be exact integers")
        if self.min_atoms < 0 or self.max_atoms < self.min_atoms:
            raise ValueError("NumericBounds: 0 <= min <= max required")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class CardinalityBounds(DeeplyImmutable):
    min_count: int
    max_count: int

    def __post_init__(self) -> None:
        if type(self.min_count) is not int or type(self.max_count) is not int:
            raise TypeError("CardinalityBounds bounds must be exact integers")
        if self.min_count < 0 or self.max_count < self.min_count:
            raise ValueError("CardinalityBounds: 0 <= min <= max required")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class TimeRepresentative(DeeplyImmutable):
    time_class: str
    now_epoch_s: int

    def __post_init__(self) -> None:
        if type(self.time_class) is not str or not self.time_class:
            raise ValueError("TimeRepresentative.time_class must be non-empty")
        if type(self.now_epoch_s) is not int or isinstance(self.now_epoch_s, bool):
            raise TypeError("TimeRepresentative.now_epoch_s must be an integer")
        if self.now_epoch_s < 0:
            raise ValueError("TimeRepresentative.now_epoch_s must be non-negative")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class MarketAdapterProfile(DeeplyImmutable):
    """Immutable, data-only adapter profile binding an external model to the core.

    No field may contain a callable, module, class, file path selected by the
    request, URL, executable source, dynamic resolver, database handle, or
    shell client. All semantics are data.
    """

    schema: str
    profile_id: str
    profile_version: str
    protocol_version: str
    abstraction_id: str
    codec_version: str

    bounty_terms_json: FrozenDict[JsonValue]
    market_policy_json: FrozenDict[JsonValue]
    identity_aliases: FrozenDict[JsonValue]
    time_representatives: FrozenDict[JsonValue]
    numeric_bounds: FrozenDict[JsonValue]
    cardinality_bounds: FrozenDict[JsonValue]

    allowed_abstract_commands: frozenset[str]
    expected_rejection_precedence: tuple[str, ...]

    source_manifest_hash: str
    model_ir_hash: str | None
    explicit_nonclaims: tuple[str, ...]

    def __post_init__(self) -> None:
        self._validate_header()
        self._validate_json_fields()
        self._validate_collection_fields()
        self._validate_hashes()
        DeeplyImmutable.__post_init__(self)

    def _validate_header(self) -> None:
        if self.schema != ADAPTER_SCHEMA:
            raise ValueError("MarketAdapterProfile.schema mismatch")
        for name, value in (
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("protocol_version", self.protocol_version),
            ("abstraction_id", self.abstraction_id),
            ("codec_version", self.codec_version),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"MarketAdapterProfile.{name} must be non-empty string")

    def _validate_json_fields(self) -> None:
        for name, value in (
            ("bounty_terms_json", self.bounty_terms_json),
            ("market_policy_json", self.market_policy_json),
            ("identity_aliases", self.identity_aliases),
            ("time_representatives", self.time_representatives),
            ("numeric_bounds", self.numeric_bounds),
            ("cardinality_bounds", self.cardinality_bounds),
        ):
            if type(value) is not FrozenDict:
                raise TypeError(f"MarketAdapterProfile.{name} must be a FrozenDict")

    def _validate_collection_fields(self) -> None:
        if type(self.allowed_abstract_commands) is not frozenset:
            raise TypeError("allowed_abstract_commands must be a frozenset")
        if not self.allowed_abstract_commands:
            raise ValueError("allowed_abstract_commands must be non-empty")
        if not all(type(value) is str and value for value in self.allowed_abstract_commands):
            raise TypeError("allowed_abstract_commands must contain non-empty strings")
        if type(self.expected_rejection_precedence) is not tuple:
            raise TypeError("expected_rejection_precedence must be a tuple")
        if not all(type(value) is str and value for value in self.expected_rejection_precedence):
            raise TypeError("expected_rejection_precedence must contain non-empty strings")
        if type(self.explicit_nonclaims) is not tuple:
            raise TypeError("explicit_nonclaims must be a tuple")

    def _validate_hashes(self) -> None:
        if type(self.source_manifest_hash) is not str or not self.source_manifest_hash.startswith("sha256:"):
            raise ValueError("source_manifest_hash must be sha256:<64hex>")
        if self.model_ir_hash is not None:
            if type(self.model_ir_hash) is not str or not self.model_ir_hash.startswith("sha256:"):
                raise ValueError("model_ir_hash must be null or sha256:<64hex>")

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
                "bounty_terms": self.bounty_terms_json,
                "market_policy": self.market_policy_json,
                "identity_aliases": self.identity_aliases,
                "time_representatives": self.time_representatives,
                "numeric_bounds": self.numeric_bounds,
                "cardinality_bounds": self.cardinality_bounds,
                "allowed_abstract_commands": tuple(sorted(self.allowed_abstract_commands)),
                "expected_rejection_precedence": self.expected_rejection_precedence,
                "source_manifest_hash": self.source_manifest_hash,
                "model_ir_hash": self.model_ir_hash,
                "explicit_nonclaims": self.explicit_nonclaims,
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
        if type(self.time_class) is not str or not self.time_class:
            raise ValueError("ExecutionContext.time_class must be non-empty")
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
# Adapter request — immutable, carries abstract state/command/context as JSON.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterRequest(DeeplyImmutable):
    schema: str
    protocol_version: str
    request_id: str
    case_id: str

    profile_id: str
    profile_hash: str
    source_manifest_hash: str
    model_ir_hash: str | None

    operation: AdapterOperation
    state: FrozenDict[JsonValue]
    command: FrozenDict[JsonValue] | None
    execution_context: ExecutionContext
    expected_pre_state_hash: str

    def __post_init__(self) -> None:
        self._validate_header()
        self._validate_profile_binding()
        self._validate_operation_and_payload()
        self._validate_hash_field("expected_pre_state_hash", self.expected_pre_state_hash)
        DeeplyImmutable.__post_init__(self)

    def _validate_header(self) -> None:
        if self.schema != ADAPTER_SCHEMA:
            raise ValueError("AdapterRequest.schema mismatch")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("AdapterRequest.protocol_version mismatch")
        for name, value in (
            ("request_id", self.request_id),
            ("case_id", self.case_id),
            ("profile_id", self.profile_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"AdapterRequest.{name} must be non-empty string")

    def _validate_profile_binding(self) -> None:
        self._validate_hash_field("profile_hash", self.profile_hash)
        self._validate_hash_field("source_manifest_hash", self.source_manifest_hash)
        if self.model_ir_hash is not None:
            self._validate_hash_field("model_ir_hash", self.model_ir_hash)

    def _validate_hash_field(self, name: str, value: str) -> None:
        if type(value) is not str or not value.startswith("sha256:"):
            raise ValueError(f"AdapterRequest.{name} must be sha256:<64hex>")

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

    def hash(self) -> str:
        return canonical_hash(REQUEST_HASH_DOMAIN, self.as_json())

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "protocol_version": self.protocol_version,
                "request_id": self.request_id,
                "case_id": self.case_id,
                "profile_id": self.profile_id,
                "profile_hash": self.profile_hash,
                "source_manifest_hash": self.source_manifest_hash,
                "model_ir_hash": self.model_ir_hash,
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
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterResponse(DeeplyImmutable):
    schema: str
    protocol_version: str
    request_id: str
    case_id: str

    profile_id: str
    profile_hash: str
    source_manifest_hash: str
    model_ir_hash: str | None

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
        DeeplyImmutable.__post_init__(self)

    def _validate_header(self) -> None:
        if self.schema != ADAPTER_SCHEMA:
            raise ValueError("AdapterResponse.schema mismatch")
        if self.protocol_version != ADAPTER_PROTOCOL_VERSION:
            raise ValueError("AdapterResponse.protocol_version mismatch")
        for name, value in (
            ("request_id", self.request_id),
            ("case_id", self.case_id),
            ("profile_id", self.profile_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"AdapterResponse.{name} must be non-empty string")
        if type(self.reason_details) is not FrozenDict:
            raise TypeError("reason_details must be a FrozenDict")
        if type(self.pre_state) is not FrozenDict:
            raise TypeError("pre_state must be a FrozenDict")
        if type(self.effects) is not tuple:
            raise TypeError("effects must be a tuple")
        if any(type(value) is not FrozenDict for value in self.effects):
            raise TypeError("effects must contain FrozenDict values")
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
        elif kind in (AdapterDecisionKind.ACCEPT, AdapterDecisionKind.COMMITTED_FAILURE):
            self._assert_committed_shape(kind)
        if self.reason_code is not None and type(self.reason_code) is not str:
            raise TypeError("reason_code must be null or a string")

    def _assert_invalid_input_shape(self) -> None:
        if self.post_state is not None or self.effects or self.receipt is not None:
            raise ValueError("INVALID_INPUT must have null post_state, empty effects, null receipt")

    def _assert_reject_shape(self) -> None:
        if self.post_state is not None and self.post_state != self.pre_state:
            raise ValueError("REJECT post_state must equal pre_state")
        if self.post_state_hash is not None and self.post_state_hash != self.pre_state_hash:
            raise ValueError("REJECT post_state_hash must equal pre_state_hash")
        if self.effects or self.receipt is not None:
            raise ValueError("REJECT must have empty effects and null receipt")

    def _assert_committed_shape(self, kind: AdapterDecisionKind) -> None:
        if self.post_state is None:
            raise ValueError(f"{kind.value} requires non-null post_state")
        if self.post_state_hash is None:
            raise ValueError(f"{kind.value} requires non-null post_state_hash")
        if self.receipt is None:
            raise ValueError(f"{kind.value} requires non-null receipt")
        if kind is AdapterDecisionKind.COMMITTED_FAILURE and (
            type(self.reason_code) is not str or not self.reason_code
        ):
            raise ValueError("COMMITTED_FAILURE requires a non-null reason_code")

    def _validate_hashes(self) -> None:
        for name, value in (
            ("profile_hash", self.profile_hash),
            ("source_manifest_hash", self.source_manifest_hash),
            ("request_hash", self.request_hash),
            ("pre_state_hash", self.pre_state_hash),
            ("response_commitment", self.response_commitment),
        ):
            if type(value) is not str or not value.startswith("sha256:"):
                raise ValueError(f"AdapterResponse.{name} must be sha256:<64hex>")
        if self.model_ir_hash is not None:
            if type(self.model_ir_hash) is not str or not self.model_ir_hash.startswith("sha256:"):
                raise ValueError("AdapterResponse.model_ir_hash must be null or sha256:<64hex>")
        if self.post_state_hash is not None:
            if type(self.post_state_hash) is not str or not self.post_state_hash.startswith("sha256:"):
                raise ValueError("AdapterResponse.post_state_hash must be null or sha256:<64hex>")
        if self.effect_plan_hash is not None:
            if type(self.effect_plan_hash) is not str or not self.effect_plan_hash.startswith("sha256:"):
                raise ValueError("AdapterResponse.effect_plan_hash must be null or sha256:<64hex>")

    def as_json_without_commitment(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "schema": self.schema,
                "protocol_version": self.protocol_version,
                "request_id": self.request_id,
                "case_id": self.case_id,
                "profile_id": self.profile_id,
                "profile_hash": self.profile_hash,
                "source_manifest_hash": self.source_manifest_hash,
                "model_ir_hash": self.model_ir_hash,
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
                "profile_id": self.profile_id,
                "profile_hash": self.profile_hash,
                "source_manifest_hash": self.source_manifest_hash,
                "model_ir_hash": self.model_ir_hash,
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
# Response builder — computes response_commitment over the response without it.
# ---------------------------------------------------------------------------


def build_response(
    *,
    request: AdapterRequest,
    profile: MarketAdapterProfile,
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
    """Construct an AdapterResponse with a computed response_commitment.

    The commitment is the domain-separated hash of the response document
    without the ``response_commitment`` field. This prevents self-referential
    hash cycles and ensures the commitment binds every other field.
    """

    details = reason_details if isinstance(reason_details, FrozenDict) else FrozenDict(reason_details)
    partial = AdapterResponse(
        schema=ADAPTER_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id=request.request_id,
        case_id=request.case_id,
        profile_id=profile.profile_id,
        profile_hash=profile.hash(),
        source_manifest_hash=profile.source_manifest_hash,
        model_ir_hash=profile.model_ir_hash,
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
        response_commitment="sha256:" + "0" * 64,
    )
    commitment = canonical_hash(RESPONSE_HASH_DOMAIN, partial.as_json_without_commitment())
    return replace(partial, response_commitment=commitment)


def build_invalid_input_response(
    *,
    request: AdapterRequest,
    profile: MarketAdapterProfile,
    invalid: InvalidInput,
    pre_state: FrozenDict[JsonValue],
    pre_state_hash: str,
) -> AdapterResponse:
    """Construct an INVALID_INPUT response carrying a typed boundary failure."""

    return build_response(
        request=request,
        profile=profile,
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


# ---------------------------------------------------------------------------
# Public type aliases.
# ---------------------------------------------------------------------------

AdapterJsonValue: TypeAlias = JsonValue
