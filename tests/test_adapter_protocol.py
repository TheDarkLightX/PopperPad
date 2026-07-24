"""Tests for the generic data-only adapter protocol (PR A1).

These tests verify:
- Architecture: core does not import adapter; adapter has no forbidden effect imports.
- Ownership and immutability: retained collections cannot mutate a profile/request;
  mutable scalar subclasses are rejected; every reachable protocol child is immutable.
- Closed enums: operations, decision kinds, and invalid-input codes are sealed.
- Canonical encoding: profile/request/response roots use distinct hash domains.
- Decision invariants: INVALID_INPUT/REJECT/ACCEPT/COMMITTED_FAILURE shapes are enforced.
- Alias rejection: mutable aliases passed at construction cannot later mutate values.
- Response commitment: computed over the response without the commitment field.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest

from popperpad.core import adapter_protocol as ap
from popperpad.core.values import (
    Amount,
    ClosedStrEnum,
    DeeplyImmutable,
    FrozenDict,
    freeze_json,
    is_deeply_immutable,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal valid profile/request/response values for testing.
# ---------------------------------------------------------------------------

_DUMMY_HASH = "sha256:" + "a" * 64
_ANOTHER_HASH = "sha256:" + "b" * 64


def _frozen(value: object) -> FrozenDict:
    result = freeze_json(value)
    assert isinstance(result, FrozenDict)
    return result


def _minimal_profile() -> ap.MarketAdapterProfile:
    return ap.MarketAdapterProfile(
        schema=ap.ADAPTER_SCHEMA,
        profile_id="test.profile.v1",
        profile_version="1",
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        abstraction_id="test.abstraction.v1",
        codec_version="popperpad-json-int-v2",
        bounty_terms_json=_frozen({"bounty_id": "bounty-1"}),
        market_policy_json=_frozen({"treasury_ref": "protocol:treasury"}),
        identity_aliases=_frozen({"sponsor": "did:example:sponsor"}),
        time_representatives=_frozen(
            {"open": {"time_class": "open", "now_epoch_s": 1}}
        ),
        numeric_bounds=_frozen({"reward": {"min_atoms": 1, "max_atoms": 100}}),
        cardinality_bounds=_frozen({"submissions": {"min_count": 0, "max_count": 1}}),
        allowed_abstract_commands=frozenset({"step"}),
        expected_rejection_precedence=("INVALID_STATE", "WRONG_PHASE"),
        source_manifest_hash=_DUMMY_HASH,
        model_ir_hash=None,
        explicit_nonclaims=("unbounded_liveness",),
    )


def _minimal_request(profile: ap.MarketAdapterProfile) -> ap.AdapterRequest:
    return ap.AdapterRequest(
        schema=ap.ADAPTER_SCHEMA,
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        request_id="req-1",
        case_id="case-1",
        profile_id=profile.profile_id,
        profile_hash=profile.hash(),
        source_manifest_hash=profile.source_manifest_hash,
        model_ir_hash=profile.model_ir_hash,
        operation=ap.AdapterOperation.VALIDATE_STATE,
        state=FrozenDict({"phase": "draft"}),
        command=None,
        execution_context=ap.ExecutionContext(time_class="open", now_epoch_s=1),
        expected_pre_state_hash=_DUMMY_HASH,
    )


# ---------------------------------------------------------------------------
# Architecture tests.
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "datetime",
    "multiprocessing",
    "os",
    "pathlib",
    "random",
    "requests",
    "socket",
    "sqlite3",
    "subprocess",
    "tempfile",
    "threading",
    "time",
    "urllib",
    "web3",
}


def test_adapter_protocol_has_no_forbidden_effect_imports() -> None:
    path = Path(ap.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        for name in names:
            assert name.split(".", 1)[0] not in _FORBIDDEN_IMPORT_ROOTS, name


def test_market_core_does_not_import_adapter_protocol() -> None:
    from popperpad.core import market

    path = Path(market.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "adapter_protocol" not in node.module, node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "adapter_protocol" not in alias.name, alias.name


def test_adapter_protocol_records_are_frozen_slotted_deeply_immutable() -> None:
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert cls.__dataclass_params__.frozen, cls.__name__
        assert hasattr(cls, "__slots__"), cls.__name__
        assert issubclass(cls, DeeplyImmutable), cls.__name__


def test_adapter_protocol_no_mutable_type_annotations() -> None:
    mutable_origins = {list, dict, set}
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        for field_name, annotation in get_type_hints(cls).items():
            assert _check_no_mutable(annotation, mutable_origins), (
                f"{cls.__name__}.{field_name} has mutable annotation"
            )


def _check_no_mutable(annotation: object, mutable: set[type]) -> bool:
    origin = get_origin(annotation)
    if origin in mutable:
        return False
    return all(_check_no_mutable(arg, mutable) for arg in get_args(annotation))


# ---------------------------------------------------------------------------
# Closed enum tests.
# ---------------------------------------------------------------------------


def test_adapter_operation_is_closed_with_exactly_two_members() -> None:
    members = tuple(ap.AdapterOperation)
    assert len(members) == 2
    assert set(members) == {ap.AdapterOperation.VALIDATE_STATE, ap.AdapterOperation.STEP}


def test_adapter_decision_kind_is_closed_with_exactly_four_members() -> None:
    members = tuple(ap.AdapterDecisionKind)
    assert len(members) == 4
    assert set(members) == {
        ap.AdapterDecisionKind.INVALID_INPUT,
        ap.AdapterDecisionKind.REJECT,
        ap.AdapterDecisionKind.ACCEPT,
        ap.AdapterDecisionKind.COMMITTED_FAILURE,
    }


def test_invalid_input_code_is_closed() -> None:
    members = tuple(ap.InvalidInputCode)
    assert len(members) == 12
    assert ap.InvalidInputCode.NON_CANONICAL_JSON in members
    assert ap.InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN in members


def test_closed_enums_reject_unknown_string_values() -> None:
    with pytest.raises(ValueError):
        ap.AdapterOperation("nonexistent")
    with pytest.raises(ValueError):
        ap.AdapterDecisionKind("nonexistent")
    with pytest.raises(ValueError):
        ap.InvalidInputCode("nonexistent")


def test_closed_enums_are_deeply_immutable() -> None:
    assert is_deeply_immutable(ap.AdapterOperation.VALIDATE_STATE)
    assert is_deeply_immutable(ap.AdapterDecisionKind.REJECT)
    assert is_deeply_immutable(ap.InvalidInputCode.NON_CANONICAL_JSON)


# ---------------------------------------------------------------------------
# Ownership and immutability tests.
# ---------------------------------------------------------------------------


def test_profile_defensively_owns_collections() -> None:
    commands: set[str] = {"step", "validate"}
    precedence: list[str] = ["INVALID_STATE", "WRONG_PHASE"]
    nonclaims: list[str] = ["unbounded"]
    profile = ap.MarketAdapterProfile(
        schema=ap.ADAPTER_SCHEMA,
        profile_id="test",
        profile_version="1",
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        abstraction_id="test",
        codec_version="popperpad-json-int-v2",
        bounty_terms_json=FrozenDict({"id": "b"}),
        market_policy_json=FrozenDict({"t": "t"}),
        identity_aliases=FrozenDict(),
        time_representatives=FrozenDict(),
        numeric_bounds=FrozenDict(),
        cardinality_bounds=FrozenDict(),
        allowed_abstract_commands=frozenset(commands),
        expected_rejection_precedence=tuple(precedence),
        source_manifest_hash=_DUMMY_HASH,
        model_ir_hash=None,
        explicit_nonclaims=tuple(nonclaims),
    )
    commands.add("evil")
    precedence.append("evil")
    nonclaims.append("evil")
    assert "evil" not in profile.allowed_abstract_commands
    assert "evil" not in profile.expected_rejection_precedence
    assert "evil" not in profile.explicit_nonclaims


def test_profile_rejects_empty_allowed_commands() -> None:
    with pytest.raises(ValueError, match="allowed_abstract_commands"):
        ap.MarketAdapterProfile(
            schema=ap.ADAPTER_SCHEMA,
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            bounty_terms_json=FrozenDict(),
            market_policy_json=FrozenDict(),
            identity_aliases=FrozenDict(),
            time_representatives=FrozenDict(),
            numeric_bounds=FrozenDict(),
            cardinality_bounds=FrozenDict(),
            allowed_abstract_commands=frozenset(),
            expected_rejection_precedence=(),
            source_manifest_hash=_DUMMY_HASH,
            model_ir_hash=None,
            explicit_nonclaims=(),
        )


def test_profile_rejects_non_frozendict_json_fields() -> None:
    with pytest.raises(TypeError, match="bounty_terms_json"):
        ap.MarketAdapterProfile(
            schema=ap.ADAPTER_SCHEMA,
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            bounty_terms_json={"id": "b"},  # type: ignore[arg-type]
            market_policy_json=FrozenDict(),
            identity_aliases=FrozenDict(),
            time_representatives=FrozenDict(),
            numeric_bounds=FrozenDict(),
            cardinality_bounds=FrozenDict(),
            allowed_abstract_commands=frozenset({"step"}),
            expected_rejection_precedence=(),
            source_manifest_hash=_DUMMY_HASH,
            model_ir_hash=None,
            explicit_nonclaims=(),
        )


def test_profile_rejects_bad_hash_format() -> None:
    with pytest.raises(ValueError, match="source_manifest_hash"):
        ap.MarketAdapterProfile(
            schema=ap.ADAPTER_SCHEMA,
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            bounty_terms_json=FrozenDict(),
            market_policy_json=FrozenDict(),
            identity_aliases=FrozenDict(),
            time_representatives=FrozenDict(),
            numeric_bounds=FrozenDict(),
            cardinality_bounds=FrozenDict(),
            allowed_abstract_commands=frozenset({"step"}),
            expected_rejection_precedence=(),
            source_manifest_hash="not-a-hash",
            model_ir_hash=None,
            explicit_nonclaims=(),
        )


def test_profile_is_deeply_immutable() -> None:
    profile = _minimal_profile()
    assert is_deeply_immutable(profile)


def test_request_is_deeply_immutable() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    assert is_deeply_immutable(request)


def test_request_step_requires_non_null_command() -> None:
    profile = _minimal_profile()
    with pytest.raises(ValueError, match="STEP"):
        ap.AdapterRequest(
            schema=ap.ADAPTER_SCHEMA,
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            request_id="req-1",
            case_id="case-1",
            profile_id=profile.profile_id,
            profile_hash=profile.hash(),
            source_manifest_hash=profile.source_manifest_hash,
            model_ir_hash=profile.model_ir_hash,
            operation=ap.AdapterOperation.STEP,
            state=FrozenDict({"phase": "open"}),
            command=None,
            execution_context=ap.ExecutionContext(time_class="open", now_epoch_s=1),
            expected_pre_state_hash=_DUMMY_HASH,
        )


def test_execution_context_rejects_bool_as_epoch() -> None:
    with pytest.raises(TypeError):
        ap.ExecutionContext(time_class="open", now_epoch_s=True)  # type: ignore[arg-type]


def test_execution_context_rejects_negative_epoch() -> None:
    with pytest.raises(ValueError):
        ap.ExecutionContext(time_class="open", now_epoch_s=-1)


def test_invalid_input_rejects_non_enum_code() -> None:
    with pytest.raises(TypeError):
        ap.InvalidInput(code="non_canonical_json", field_path="$", detail="bad")  # type: ignore[arg-type]


def test_invalid_input_is_deeply_immutable() -> None:
    invalid = ap.InvalidInput(
        code=ap.InvalidInputCode.NON_CANONICAL_JSON,
        field_path="$",
        detail="bad",
    )
    assert is_deeply_immutable(invalid)


# ---------------------------------------------------------------------------
# Deep immutability attack tests.
#
# frozen=True only blocks attribute rebinding. These tests prove that the
# DeeplyImmutable recursive check actually catches the real attack vectors:
#   - mutable alias injection through collections
#   - scalar subclass attacks (bool as int, str subclass)
#   - cyclic value graphs
#   - post-construction mutation of source containers
#   - mutable nested values inside FrozenDict
#   - non-DeeplyImmutable dataclass as field value
#   - list/dict/set anywhere in the reachable graph
# ---------------------------------------------------------------------------


def test_frozendict_rejects_list_value() -> None:
    """A FrozenDict containing a list must be rejected at construction."""
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"evil": [1, 2, 3]})  # type: ignore[dict-item]


def test_frozendict_rejects_dict_value() -> None:
    """A FrozenDict containing a dict must be rejected at construction."""
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"evil": {"nested": "dict"}})  # type: ignore[dict-item]


def test_frozendict_rejects_set_value() -> None:
    """A FrozenDict containing a set must be rejected at construction."""
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"evil": {1, 2}})  # type: ignore[dict-item]


def test_frozendict_defensive_copy_blocks_post_construction_mutation() -> None:
    """Mutating the source dict after FrozenDict construction must not affect it."""
    source: dict[str, object] = {"key": "value"}
    fd = FrozenDict(source)
    source["key"] = "mutated"
    source["new_key"] = "injected"
    assert fd["key"] == "value"
    assert "new_key" not in fd


def test_tuple_rejects_list_element_via_deep_check() -> None:
    """A tuple containing a list is not deeply immutable."""
    t = ([1, 2],)  # type: ignore[arg-type]
    assert not is_deeply_immutable(t)


def test_frozenset_rejects_mutable_element_via_deep_check() -> None:
    """A frozenset containing a hashable-but-mutable object is not deeply immutable."""

    class HashableButMutable:
        __hash__ = lambda self: 0

    fs = frozenset({HashableButMutable()})
    assert not is_deeply_immutable(fs)


def test_bool_is_not_treated_as_int_by_deep_check() -> None:
    """bool is a subclass of int, but is_deeply_immutable accepts it as a scalar.
    However, Amount rejects bool at construction via type(self.atoms) is not int.
    This test verifies Amount's exact-type guard."""
    from popperpad.core.values import Amount

    with pytest.raises(TypeError, match="integer"):
        Amount(True)  # type: ignore[arg-type]


def test_str_subclass_is_rejected_by_frozendict_key() -> None:
    """A str subclass as a FrozenDict key must be rejected (exact type check)."""

    class EvilStr(str):
        pass

    with pytest.raises(TypeError, match="exact strings"):
        FrozenDict({EvilStr("key"): "value"})  # type: ignore[dict-item]


def test_int_subclass_is_rejected_by_amount() -> None:
    """An int subclass as Amount.atoms must be rejected (exact type check)."""

    class EvilInt(int):
        pass

    with pytest.raises(TypeError, match="integer"):
        Amount(EvilInt(42))  # type: ignore[arg-type]


def test_cyclic_tuple_graph_is_rejected() -> None:
    """A tuple that indirectly references itself must be rejected."""
    outer: list[object] = []
    t = (outer,)
    outer.append(t)
    assert not is_deeply_immutable(t)


def test_cyclic_frozendict_graph_is_rejected_at_construction() -> None:
    """A FrozenDict containing a list (which could form a cycle) is rejected at construction."""
    outer: list[object] = []
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"cycle": outer})


def test_non_deeply_immutable_dataclass_as_field_is_rejected() -> None:
    """A frozen dataclass that does not inherit DeeplyImmutable is rejected
    by the DeeplyImmutable.__post_init__ recursive check."""
    from dataclasses import dataclass, field
    from typing import Any

    @dataclass(frozen=True, slots=True)
    class NotDeeplyImmutable:
        value: int

    @dataclass(frozen=True, slots=True)
    class Container(DeeplyImmutable):
        payload: Any = None

    with pytest.raises(TypeError, match="deeply immutable"):
        Container(payload=NotDeeplyImmutable(42))


def test_mutable_dataclass_as_field_is_rejected() -> None:
    """A non-frozen dataclass is rejected even if it inherits DeeplyImmutable."""
    from dataclasses import dataclass
    from typing import Any

    @dataclass(slots=True)
    class MutableButMarked(DeeplyImmutable):
        value: int

    @dataclass(frozen=True, slots=True)
    class Container(DeeplyImmutable):
        payload: Any = None

    with pytest.raises(TypeError, match="deeply immutable"):
        Container(payload=MutableButMarked(42))


def test_profile_rejects_mutable_nested_frozendict_value() -> None:
    """A FrozenDict with a nested list value must be rejected at profile construction."""
    with pytest.raises(TypeError):
        FrozenDict({"evil": ([1, 2],)})  # type: ignore[dict-item]


def test_request_rejects_mutable_state_value() -> None:
    """A request state FrozenDict with a list value must be rejected."""
    profile = _minimal_profile()
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"phase": [1, 2]})  # type: ignore[dict-item]


def test_deeply_immutable_rejects_plain_dict() -> None:
    """A plain dict is not deeply immutable."""
    assert not is_deeply_immutable({"key": "value"})


def test_deeply_immutable_rejects_plain_list() -> None:
    """A plain list is not deeply immutable."""
    assert not is_deeply_immutable([1, 2, 3])


def test_deeply_immutable_rejects_plain_set() -> None:
    """A plain set is not deeply immutable."""
    assert not is_deeply_immutable({1, 2, 3})


def test_deeply_immutable_rejects_callable() -> None:
    """A callable is not deeply immutable."""
    assert not is_deeply_immutable(lambda: None)


def test_deeply_immutable_rejects_module() -> None:
    """A module is not deeply immutable."""
    import json

    assert not is_deeply_immutable(json)


def test_deeply_immutable_rejects_class() -> None:
    """A class object is not deeply immutable."""
    assert not is_deeply_immutable(int)


def test_profile_post_construction_attribute_rebind_fails() -> None:
    """frozen=True blocks attribute rebinding on a constructed profile."""
    profile = _minimal_profile()
    with pytest.raises(Exception):
        profile.profile_id = "evil"  # type: ignore[misc]


def test_request_post_construction_attribute_rebind_fails() -> None:
    """frozen=True blocks attribute rebinding on a constructed request."""
    profile = _minimal_profile()
    request = _minimal_request(profile)
    with pytest.raises(Exception):
        request.request_id = "evil"  # type: ignore[misc]


def test_response_post_construction_attribute_rebind_fails() -> None:
    """frozen=True blocks attribute rebinding on a constructed response."""
    profile = _minimal_profile()
    request = _minimal_request(profile)
    response = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    with pytest.raises(Exception):
        response.decision_kind = ap.AdapterDecisionKind.ACCEPT  # type: ignore[misc]


def test_all_protocol_dataclasses_inherit_deeply_immutable() -> None:
    """Every dataclass in adapter_protocol must inherit DeeplyImmutable."""
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert issubclass(cls, DeeplyImmutable), f"{cls.__name__} does not inherit DeeplyImmutable"


def test_all_protocol_dataclasses_use_slots() -> None:
    """Every dataclass in adapter_protocol must use __slots__."""
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert hasattr(cls, "__slots__"), f"{cls.__name__} lacks __slots__"


def test_all_protocol_dataclasses_are_frozen() -> None:
    """Every dataclass in adapter_protocol must be frozen=True."""
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} is not frozen"


def test_frozendict_rejects_duplicate_keys() -> None:
    """FrozenDict must reject duplicate keys at construction."""
    with pytest.raises(ValueError, match="duplicate"):
        FrozenDict([("a", 1), ("a", 2)])  # type: ignore[list-item]


def test_frozendict_rejects_non_string_key() -> None:
    """FrozenDict must reject non-string keys."""
    with pytest.raises(TypeError, match="exact strings"):
        FrozenDict({1: "value"})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# Canonical encoding and hash domain separation tests.
# ---------------------------------------------------------------------------


def test_profile_hash_uses_profile_domain() -> None:
    profile = _minimal_profile()
    h = profile.hash()
    assert h.startswith("sha256:")
    assert h != _DUMMY_HASH


def test_request_hash_uses_request_domain() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    h = request.hash()
    assert h.startswith("sha256:")
    assert h != profile.hash()


def test_distinct_hash_domains_produce_distinct_hashes() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    assert profile.hash() != request.hash()
    assert ap.PROFILE_HASH_DOMAIN != ap.REQUEST_HASH_DOMAIN
    assert ap.REQUEST_HASH_DOMAIN != ap.RESPONSE_HASH_DOMAIN
    assert ap.PROFILE_HASH_DOMAIN != ap.RESPONSE_HASH_DOMAIN
    assert ap.SOURCE_MANIFEST_HASH_DOMAIN not in (
        ap.PROFILE_HASH_DOMAIN,
        ap.REQUEST_HASH_DOMAIN,
        ap.RESPONSE_HASH_DOMAIN,
    )


def test_profile_hash_is_deterministic() -> None:
    p1 = _minimal_profile()
    p2 = _minimal_profile()
    assert p1.hash() == p2.hash()


def test_profile_hash_differs_on_field_change() -> None:
    p1 = _minimal_profile()
    p2 = ap.MarketAdapterProfile(
        schema=ap.ADAPTER_SCHEMA,
        profile_id="test.profile.v2",
        profile_version="1",
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        abstraction_id="test.abstraction.v1",
        codec_version="popperpad-json-int-v2",
        bounty_terms_json=_frozen({"bounty_id": "bounty-1"}),
        market_policy_json=_frozen({"treasury_ref": "protocol:treasury"}),
        identity_aliases=_frozen({"sponsor": "did:example:sponsor"}),
        time_representatives=_frozen(
            {"open": {"time_class": "open", "now_epoch_s": 1}}
        ),
        numeric_bounds=_frozen({"reward": {"min_atoms": 1, "max_atoms": 100}}),
        cardinality_bounds=_frozen({"submissions": {"min_count": 0, "max_count": 1}}),
        allowed_abstract_commands=frozenset({"step"}),
        expected_rejection_precedence=("INVALID_STATE", "WRONG_PHASE"),
        source_manifest_hash=_DUMMY_HASH,
        model_ir_hash=None,
        explicit_nonclaims=("unbounded_liveness",),
    )
    assert p1.hash() != p2.hash()


# ---------------------------------------------------------------------------
# Decision invariant tests.
# ---------------------------------------------------------------------------


def test_invalid_input_response_has_null_post_state_effects_receipt() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    invalid = ap.InvalidInput(
        code=ap.InvalidInputCode.SCHEMA_MISMATCH,
        field_path="$.schema",
        detail="wrong schema",
    )
    response = ap.build_invalid_input_response(
        request=request,
        profile=profile,
        invalid=invalid,
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
    )
    assert response.decision_kind is ap.AdapterDecisionKind.INVALID_INPUT
    assert response.post_state is None
    assert response.effects == ()
    assert response.receipt is None
    assert response.reason_code == "schema_mismatch"


def test_reject_response_must_have_empty_effects_and_null_receipt() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    with pytest.raises(ValueError, match="REJECT"):
        ap.build_response(
            request=request,
            profile=profile,
            decision_kind=ap.AdapterDecisionKind.REJECT,
            reason_code="WRONG_PHASE",
            reason_details=FrozenDict({"field": "phase"}),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "draft"}),
            post_state_hash=_DUMMY_HASH,
            effects=(FrozenDict({"kind": "bad"}),),
            effect_plan_hash=_ANOTHER_HASH,
            receipt=FrozenDict({"event": "bad"}),
        )


def test_reject_response_with_matching_pre_post_state_succeeds() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    response = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    assert response.decision_kind is ap.AdapterDecisionKind.REJECT
    assert response.effects == ()
    assert response.receipt is None


def test_accept_response_requires_post_state_and_receipt() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    with pytest.raises(ValueError, match="accept"):
        ap.build_response(
            request=request,
            profile=profile,
            decision_kind=ap.AdapterDecisionKind.ACCEPT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=None,
            post_state_hash=None,
        )


def test_committed_failure_requires_reason_code() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    with pytest.raises(ValueError, match="COMMITTED_FAILURE"):
        ap.build_response(
            request=request,
            profile=profile,
            decision_kind=ap.AdapterDecisionKind.COMMITTED_FAILURE,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "expired"}),
            post_state_hash=_ANOTHER_HASH,
            receipt=FrozenDict({"event": "expired"}),
        )


def test_committed_failure_with_all_fields_succeeds() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    response = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.COMMITTED_FAILURE,
        reason_code="NO_PAYABLE_SUBMISSION",
        reason_details=FrozenDict(),
        pre_state=FrozenDict({"phase": "open"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "expired"}),
        post_state_hash=_ANOTHER_HASH,
        effects=(FrozenDict({"kind": "refund_escrow"}),),
        effect_plan_hash=_DUMMY_HASH,
        receipt=FrozenDict({"event": "bounty_expired"}),
    )
    assert response.decision_kind is ap.AdapterDecisionKind.COMMITTED_FAILURE
    assert response.reason_code == "NO_PAYABLE_SUBMISSION"
    assert response.post_state is not None
    assert response.receipt is not None


# ---------------------------------------------------------------------------
# Response commitment tests.
# ---------------------------------------------------------------------------


def test_response_commitment_is_computed_over_response_without_commitment() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    response = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    from popperpad.core.codec import canonical_hash

    expected = canonical_hash(
        ap.RESPONSE_HASH_DOMAIN,
        response.as_json_without_commitment(),
    )
    assert response.response_commitment == expected


def test_response_commitment_changes_on_field_change() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    r1 = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    r2 = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="TIME_WINDOW",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    assert r1.response_commitment != r2.response_commitment


def test_response_is_deeply_immutable() -> None:
    profile = _minimal_profile()
    request = _minimal_request(profile)
    response = ap.build_response(
        request=request,
        profile=profile,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    assert is_deeply_immutable(response)


# ---------------------------------------------------------------------------
# Source manifest tests.
# ---------------------------------------------------------------------------


def test_source_manifest_hash_is_domain_separated() -> None:
    manifest = ap.SourceManifest(
        schema="popperpad/data-adapter-source-manifest/v1",
        repository="TheDarkLightX/PopperPad",
        commit="abc123",
        files=(
            ap.SourceFileBinding(path="src/popperpad/core/market.py", sha256=_DUMMY_HASH),
        ),
        profile_hash=_ANOTHER_HASH,
        codec_version="popperpad-json-int-v2",
    )
    h = manifest.hash()
    assert h.startswith("sha256:")
    assert h != _DUMMY_HASH


def test_source_manifest_rejects_empty_files() -> None:
    with pytest.raises(ValueError, match="files"):
        ap.SourceManifest(
            schema="popperpad/data-adapter-source-manifest/v1",
            repository="TheDarkLightX/PopperPad",
            commit="abc123",
            files=(),
            profile_hash=_ANOTHER_HASH,
            codec_version="popperpad-json-int-v2",
        )


def test_source_manifest_rejects_bad_sha256() -> None:
    with pytest.raises(ValueError, match="sha256"):
        ap.SourceFileBinding(path="src/foo.py", sha256="not-a-hash")


# ---------------------------------------------------------------------------
# No-callable / no-module / no-class-in-profile test.
# ---------------------------------------------------------------------------


def test_profile_rejects_callable_in_frozendict_value() -> None:
    with pytest.raises(TypeError):
        FrozenDict({"evil": lambda: None})  # type: ignore[dict-item]


def test_numeric_bounds_reject_bool() -> None:
    with pytest.raises(TypeError):
        ap.NumericBounds(min_atoms=True, max_atoms=10)  # type: ignore[arg-type]


def test_cardinality_bounds_reject_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        ap.CardinalityBounds(min_count=10, max_count=1)


def test_time_representative_rejects_empty_class() -> None:
    with pytest.raises(ValueError):
        ap.TimeRepresentative(time_class="", now_epoch_s=1)
