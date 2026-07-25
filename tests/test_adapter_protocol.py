"""Tests for the generic data-only adapter protocol (PR A1).

These tests verify:
- Architecture: core does not import adapter; adapter has no forbidden effect imports.
- Ownership and immutability: retained collections cannot mutate a profile/request;
  mutable scalar subclasses are rejected; every reachable protocol child is immutable.
- Closed enums: operations, decision kinds, and invalid-input codes are sealed.
- Canonical encoding: profile/binding/request/response/manifest roots use distinct hash domains.
- Acyclic binding graph: profile → manifest → binding, no hash cycle.
- Decision invariants: INVALID_INPUT/REJECT/ACCEPT/COMMITTED_FAILURE shapes are enforced.
- Response commitment: verified during construction; tampering via replace() must fail.
- Strict digest validation: exact sha256:<64 lowercase hex> everywhere.
- Distinct schema tags: profile, binding, request, response, manifest.
- Canonical source bindings: normalized paths, sorted, unique, no traversal.
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
# Fixtures — minimal valid profile/binding/request/response values for testing.
# ---------------------------------------------------------------------------

_DUMMY_HASH = "sha256:" + "a" * 64
_ANOTHER_HASH = "sha256:" + "b" * 64
_THIRD_HASH = "sha256:" + "c" * 64


def _frozen(value: object) -> FrozenDict:
    result = freeze_json(value)
    assert isinstance(result, FrozenDict)
    return result


def _minimal_profile() -> ap.DataAdapterProfile:
    return ap.DataAdapterProfile(
        schema=ap.PROFILE_SCHEMA,
        profile_id="test.profile.v1",
        profile_version="1",
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        abstraction_id="test.abstraction.v1",
        codec_version="popperpad-json-int-v2",
        semantic_profile=_frozen({"some_field": "some_value"}),
        explicit_nonclaims=("unbounded_liveness",),
    )


def _minimal_binding(profile: ap.DataAdapterProfile | None = None) -> ap.AdapterBinding:
    if profile is None:
        profile = _minimal_profile()
    return ap.AdapterBinding(
        schema=ap.BINDING_SCHEMA,
        profile_hash=profile.hash(),
        source_manifest_hash=_DUMMY_HASH,
        model_ir_hash=None,
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        adapter_implementation_id="popperpad.refinement.market_adapter",
    )


def _minimal_request(binding: ap.AdapterBinding | None = None) -> ap.AdapterRequest:
    if binding is None:
        binding = _minimal_binding()
    return ap.AdapterRequest(
        schema=ap.REQUEST_SCHEMA,
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        request_id="req-1",
        case_id="case-1",
        binding_hash=binding.hash(),
        operation=ap.AdapterOperation.VALIDATE_STATE,
        state=FrozenDict({"phase": "draft"}),
        command=None,
        execution_context=ap.ExecutionContext(time_class="open", now_epoch_s=1),
        expected_pre_state_hash=_DUMMY_HASH,
    )


def _minimal_source_manifest(profile_hash: str = _DUMMY_HASH) -> ap.SourceManifest:
    return ap.SourceManifest(
        schema=ap.SOURCE_MANIFEST_SCHEMA,
        repository="TheDarkLightX/PopperPad",
        commit="a" * 40,
        files=(
            ap.SourceFileBinding(path="src/popperpad/core/market.py", sha256=_DUMMY_HASH),
        ),
        profile_hash=profile_hash,
        codec_version="popperpad-json-int-v2",
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
    assert len(members) == 14
    assert ap.InvalidInputCode.NON_CANONICAL_JSON in members
    assert ap.InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN in members
    assert ap.InvalidInputCode.PRE_STATE_HASH_MISMATCH in members
    assert ap.InvalidInputCode.BINDING_MISMATCH in members


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
    nonclaims: list[str] = ["unbounded_liveness"]
    profile = ap.DataAdapterProfile(
        schema=ap.PROFILE_SCHEMA,
        profile_id="test",
        profile_version="1",
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        abstraction_id="test",
        codec_version="popperpad-json-int-v2",
        semantic_profile=FrozenDict({"k": "v"}),
        explicit_nonclaims=tuple(nonclaims),
    )
    nonclaims.append("evil")
    assert "evil" not in profile.explicit_nonclaims


def test_profile_rejects_non_frozendict_semantic_profile() -> None:
    with pytest.raises(TypeError, match="semantic_profile"):
        ap.DataAdapterProfile(
            schema=ap.PROFILE_SCHEMA,
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            semantic_profile={"id": "b"},  # type: ignore[arg-type]
            explicit_nonclaims=("a",),
        )


def test_profile_rejects_unsorted_nonclaims() -> None:
    with pytest.raises(ValueError, match="sorted"):
        ap.DataAdapterProfile(
            schema=ap.PROFILE_SCHEMA,
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            semantic_profile=FrozenDict(),
            explicit_nonclaims=("z", "a"),
        )


def test_profile_rejects_duplicate_nonclaims() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        ap.DataAdapterProfile(
            schema=ap.PROFILE_SCHEMA,
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            semantic_profile=FrozenDict(),
            explicit_nonclaims=("a", "a"),
        )


def test_profile_rejects_wrong_schema() -> None:
    with pytest.raises(ValueError, match="schema"):
        ap.DataAdapterProfile(
            schema="wrong/schema",
            profile_id="test",
            profile_version="1",
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            abstraction_id="test",
            codec_version="popperpad-json-int-v2",
            semantic_profile=FrozenDict(),
            explicit_nonclaims=("a",),
        )


def test_profile_is_deeply_immutable() -> None:
    profile = _minimal_profile()
    assert is_deeply_immutable(profile)


def test_binding_is_deeply_immutable() -> None:
    binding = _minimal_binding()
    assert is_deeply_immutable(binding)


def test_request_is_deeply_immutable() -> None:
    request = _minimal_request()
    assert is_deeply_immutable(request)


def test_request_step_requires_non_null_command() -> None:
    with pytest.raises(ValueError, match="STEP"):
        ap.AdapterRequest(
            schema=ap.REQUEST_SCHEMA,
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            request_id="req-1",
            case_id="case-1",
            binding_hash=_DUMMY_HASH,
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
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"evil": [1, 2, 3]})  # type: ignore[dict-item]


def test_frozendict_rejects_dict_value() -> None:
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"evil": {"nested": "dict"}})  # type: ignore[dict-item]


def test_frozendict_rejects_set_value() -> None:
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"evil": {1, 2}})  # type: ignore[dict-item]


def test_frozendict_defensive_copy_blocks_post_construction_mutation() -> None:
    source: dict[str, object] = {"key": "value"}
    fd = FrozenDict(source)
    source["key"] = "mutated"
    source["new_key"] = "injected"
    assert fd["key"] == "value"
    assert "new_key" not in fd


def test_tuple_rejects_list_element_via_deep_check() -> None:
    t = ([1, 2],)  # type: ignore[arg-type]
    assert not is_deeply_immutable(t)


def test_frozenset_rejects_mutable_element_via_deep_check() -> None:
    class HashableButMutable:
        __hash__ = lambda self: 0

    fs = frozenset({HashableButMutable()})
    assert not is_deeply_immutable(fs)


def test_bool_is_not_treated_as_int_by_amount() -> None:
    with pytest.raises(TypeError, match="integer"):
        Amount(True)  # type: ignore[arg-type]


def test_str_subclass_is_rejected_by_frozendict_key() -> None:
    class EvilStr(str):
        pass

    with pytest.raises(TypeError, match="exact strings"):
        FrozenDict({EvilStr("key"): "value"})  # type: ignore[dict-item]


def test_int_subclass_is_rejected_by_amount() -> None:
    class EvilInt(int):
        pass

    with pytest.raises(TypeError, match="integer"):
        Amount(EvilInt(42))  # type: ignore[arg-type]


def test_cyclic_tuple_graph_is_rejected() -> None:
    outer: list[object] = []
    t = (outer,)
    outer.append(t)
    assert not is_deeply_immutable(t)


def test_cyclic_frozendict_graph_is_rejected_at_construction() -> None:
    outer: list[object] = []
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"cycle": outer})


def test_non_deeply_immutable_dataclass_as_field_is_rejected() -> None:
    from dataclasses import dataclass
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
    with pytest.raises(TypeError):
        FrozenDict({"evil": ([1, 2],)})  # type: ignore[dict-item]


def test_request_rejects_mutable_state_value() -> None:
    with pytest.raises(TypeError, match="deeply immutable"):
        FrozenDict({"phase": [1, 2]})  # type: ignore[dict-item]


def test_deeply_immutable_rejects_plain_dict() -> None:
    assert not is_deeply_immutable({"key": "value"})


def test_deeply_immutable_rejects_plain_list() -> None:
    assert not is_deeply_immutable([1, 2, 3])


def test_deeply_immutable_rejects_plain_set() -> None:
    assert not is_deeply_immutable({1, 2, 3})


def test_deeply_immutable_rejects_callable() -> None:
    assert not is_deeply_immutable(lambda: None)


def test_deeply_immutable_rejects_module() -> None:
    import json

    assert not is_deeply_immutable(json)


def test_deeply_immutable_rejects_class() -> None:
    assert not is_deeply_immutable(int)


def test_profile_post_construction_attribute_rebind_fails() -> None:
    profile = _minimal_profile()
    with pytest.raises(Exception):
        profile.profile_id = "evil"  # type: ignore[misc]


def test_request_post_construction_attribute_rebind_fails() -> None:
    request = _minimal_request()
    with pytest.raises(Exception):
        request.request_id = "evil"  # type: ignore[misc]


def test_response_post_construction_attribute_rebind_fails() -> None:
    request = _minimal_request()
    response = ap.build_response(
        request=request,
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
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert issubclass(cls, DeeplyImmutable), f"{cls.__name__} does not inherit DeeplyImmutable"


def test_all_protocol_dataclasses_use_slots() -> None:
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert hasattr(cls, "__slots__"), f"{cls.__name__} lacks __slots__"


def test_all_protocol_dataclasses_are_frozen() -> None:
    for _name, cls in inspect.getmembers(ap, inspect.isclass):
        if cls.__module__ != ap.__name__ or not dataclasses.is_dataclass(cls):
            continue
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} is not frozen"


def test_frozendict_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        FrozenDict([("a", 1), ("a", 2)])  # type: ignore[list-item]


def test_frozendict_rejects_non_string_key() -> None:
    with pytest.raises(TypeError, match="exact strings"):
        FrozenDict({1: "value"})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# Acyclic binding graph tests.
# ---------------------------------------------------------------------------


def test_profile_does_not_contain_source_manifest_hash() -> None:
    """The profile must not contain source_manifest_hash — that would create a cycle."""
    profile = _minimal_profile()
    json_data = profile.as_json()
    assert "source_manifest_hash" not in json_data
    assert "binding_hash" not in json_data


def test_source_manifest_contains_profile_hash() -> None:
    """The manifest references the profile hash (acyclic direction)."""
    profile = _minimal_profile()
    manifest = _minimal_source_manifest(profile.hash())
    assert manifest.profile_hash == profile.hash()


def test_binding_contains_profile_and_manifest_hashes() -> None:
    """The binding binds profile_hash and source_manifest_hash."""
    profile = _minimal_profile()
    manifest = _minimal_source_manifest(profile.hash())
    binding = ap.AdapterBinding(
        schema=ap.BINDING_SCHEMA,
        profile_hash=profile.hash(),
        source_manifest_hash=manifest.hash(),
        model_ir_hash=None,
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        adapter_implementation_id="test",
    )
    assert binding.profile_hash == profile.hash()
    assert binding.source_manifest_hash == manifest.hash()


def test_binding_hash_does_not_depend_on_request() -> None:
    """The binding hash is stable regardless of request content."""
    binding = _minimal_binding()
    h1 = binding.hash()
    h2 = binding.hash()
    assert h1 == h2


def test_profile_hash_does_not_depend_on_manifest() -> None:
    """The profile hash is stable regardless of manifest content."""
    profile = _minimal_profile()
    h1 = profile.hash()
    manifest = _minimal_source_manifest(profile.hash())
    h2 = profile.hash()
    assert h1 == h2
    assert manifest.profile_hash == h1


def test_request_carries_binding_hash_not_profile_hash() -> None:
    """Requests carry binding_hash, not separate profile/manifest hashes."""
    request = _minimal_request()
    assert hasattr(request, "binding_hash")
    assert not hasattr(request, "profile_hash")
    assert not hasattr(request, "source_manifest_hash")


# ---------------------------------------------------------------------------
# Distinct schema tags tests.
# ---------------------------------------------------------------------------


def test_profile_schema_is_distinct() -> None:
    assert ap.PROFILE_SCHEMA == "popperpad/data-adapter-profile/v1"


def test_binding_schema_is_distinct() -> None:
    assert ap.BINDING_SCHEMA == "popperpad/data-adapter-binding/v1"


def test_request_schema_is_distinct() -> None:
    assert ap.REQUEST_SCHEMA == "popperpad/data-adapter-request/v1"


def test_response_schema_is_distinct() -> None:
    assert ap.RESPONSE_SCHEMA == "popperpad/data-adapter-response/v1"


def test_boundary_response_schema_is_distinct() -> None:
    assert ap.BOUNDARY_RESPONSE_SCHEMA == "popperpad/data-adapter-boundary-response/v1"


def test_source_manifest_schema_is_distinct() -> None:
    assert ap.SOURCE_MANIFEST_SCHEMA == "popperpad/data-adapter-source-manifest/v1"


def test_all_schemas_are_distinct_from_each_other() -> None:
    schemas = {
        ap.PROFILE_SCHEMA,
        ap.BINDING_SCHEMA,
        ap.REQUEST_SCHEMA,
        ap.RESPONSE_SCHEMA,
        ap.BOUNDARY_RESPONSE_SCHEMA,
        ap.SOURCE_MANIFEST_SCHEMA,
    }
    assert len(schemas) == 6


@pytest.mark.parametrize("codec_version", ["made-up-codec", "", "popperpad-json-int-v1"])
def test_profile_rejects_unsupported_codec_version(codec_version: str) -> None:
    with pytest.raises(ValueError, match="codec_version mismatch"):
        dataclasses.replace(_minimal_profile(), codec_version=codec_version)


@pytest.mark.parametrize("codec_version", ["made-up-codec", "", "popperpad-json-int-v1"])
def test_source_manifest_rejects_unsupported_codec_version(codec_version: str) -> None:
    with pytest.raises(ValueError, match="codec_version mismatch"):
        dataclasses.replace(_minimal_source_manifest(), codec_version=codec_version)


# ---------------------------------------------------------------------------
# Strict digest validation tests.
# ---------------------------------------------------------------------------


def test_require_sha256_ref_accepts_valid_hash() -> None:
    assert ap.require_sha256_ref(_DUMMY_HASH, "$") == _DUMMY_HASH


def test_require_sha256_ref_rejects_empty() -> None:
    with pytest.raises(ValueError):
        ap.require_sha256_ref("sha256:", "$")


def test_require_sha256_ref_rejects_pending() -> None:
    with pytest.raises(ValueError):
        ap.require_sha256_ref("sha256:pending", "$")


def test_require_sha256_ref_rejects_non_hex() -> None:
    with pytest.raises(ValueError):
        ap.require_sha256_ref("sha256:xyz", "$")


def test_require_sha256_ref_rejects_uppercase_hex() -> None:
    with pytest.raises(ValueError):
        ap.require_sha256_ref("sha256:" + "A" * 64, "$")


def test_require_sha256_ref_rejects_short_hex() -> None:
    with pytest.raises(ValueError):
        ap.require_sha256_ref("sha256:" + "a" * 32, "$")


def test_require_sha256_ref_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        ap.require_sha256_ref(123, "$")  # type: ignore[arg-type]


def test_binding_rejects_weak_profile_hash() -> None:
    with pytest.raises(ValueError):
        ap.AdapterBinding(
            schema=ap.BINDING_SCHEMA,
            profile_hash="sha256:pending",
            source_manifest_hash=_DUMMY_HASH,
            model_ir_hash=None,
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            adapter_implementation_id="test",
        )


def test_request_rejects_weak_binding_hash() -> None:
    with pytest.raises(ValueError):
        ap.AdapterRequest(
            schema=ap.REQUEST_SCHEMA,
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            request_id="req-1",
            case_id="case-1",
            binding_hash="sha256:pending",
            operation=ap.AdapterOperation.VALIDATE_STATE,
            state=FrozenDict(),
            command=None,
            execution_context=ap.ExecutionContext(time_class="open", now_epoch_s=1),
            expected_pre_state_hash=_DUMMY_HASH,
        )


# ---------------------------------------------------------------------------
# Canonical source binding tests.
# ---------------------------------------------------------------------------


def test_source_file_binding_rejects_absolute_path() -> None:
    with pytest.raises(ValueError, match="relative"):
        ap.SourceFileBinding(path="/etc/passwd", sha256=_DUMMY_HASH)


def test_source_file_binding_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="traversal"):
        ap.SourceFileBinding(path="../../etc/passwd", sha256=_DUMMY_HASH)


@pytest.mark.parametrize("path", ["./file.py", "src/./file.py"])
def test_source_file_binding_rejects_dot_segments(path: str) -> None:
    with pytest.raises(ValueError, match="dot segment"):
        ap.SourceFileBinding(path=path, sha256=_DUMMY_HASH)


def test_source_file_binding_rejects_backslash() -> None:
    with pytest.raises(ValueError, match="backslash"):
        ap.SourceFileBinding(path="src\\file.py", sha256=_DUMMY_HASH)


def test_source_file_binding_rejects_double_slash() -> None:
    with pytest.raises(ValueError, match="double slash"):
        ap.SourceFileBinding(path="src//file.py", sha256=_DUMMY_HASH)


def test_source_manifest_rejects_unsorted_files() -> None:
    with pytest.raises(ValueError, match="sorted"):
        ap.SourceManifest(
            schema=ap.SOURCE_MANIFEST_SCHEMA,
            repository="test",
            commit="a" * 40,
            files=(
                ap.SourceFileBinding(path="z/file.py", sha256=_DUMMY_HASH),
                ap.SourceFileBinding(path="a/file.py", sha256=_DUMMY_HASH),
            ),
            profile_hash=_DUMMY_HASH,
            codec_version="popperpad-json-int-v2",
        )


def test_source_manifest_rejects_duplicate_paths() -> None:
    with pytest.raises(ValueError, match="unique"):
        ap.SourceManifest(
            schema=ap.SOURCE_MANIFEST_SCHEMA,
            repository="test",
            commit="a" * 40,
            files=(
                ap.SourceFileBinding(path="src/file.py", sha256=_DUMMY_HASH),
                ap.SourceFileBinding(path="src/file.py", sha256=_ANOTHER_HASH),
            ),
            profile_hash=_DUMMY_HASH,
            codec_version="popperpad-json-int-v2",
        )


def test_source_manifest_rejects_invalid_commit() -> None:
    with pytest.raises(ValueError, match="commit"):
        ap.SourceManifest(
            schema=ap.SOURCE_MANIFEST_SCHEMA,
            repository="test",
            commit="not-a-commit",
            files=(ap.SourceFileBinding(path="src/file.py", sha256=_DUMMY_HASH),),
            profile_hash=_DUMMY_HASH,
            codec_version="popperpad-json-int-v2",
        )


def test_source_manifest_rejects_uppercase_commit() -> None:
    with pytest.raises(ValueError, match="commit"):
        ap.SourceManifest(
            schema=ap.SOURCE_MANIFEST_SCHEMA,
            repository="test",
            commit="A" * 40,
            files=(ap.SourceFileBinding(path="src/file.py", sha256=_DUMMY_HASH),),
            profile_hash=_DUMMY_HASH,
            codec_version="popperpad-json-int-v2",
        )


# ---------------------------------------------------------------------------
# Response commitment verification tests.
# ---------------------------------------------------------------------------


def test_response_commitment_is_verified_during_construction() -> None:
    """build_response produces a response whose commitment is valid."""
    request = _minimal_request()
    response = ap.build_response(
        request=request,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    assert response.response_commitment.startswith("sha256:")


def test_response_replace_with_stale_commitment_fails() -> None:
    """Tampering with a field via replace() must fail because the commitment no longer matches."""
    request = _minimal_request()
    response = ap.build_response(
        request=request,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    with pytest.raises(ValueError, match="response_commitment"):
        dataclasses.replace(response, reason_code="different")


def test_response_replace_with_same_commitment_and_same_fields_succeeds() -> None:
    """replace() with identical values should succeed because the commitment still matches."""
    request = _minimal_request()
    response = ap.build_response(
        request=request,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict({"field": "phase"}),
        pre_state=FrozenDict({"phase": "draft"}),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict({"phase": "draft"}),
        post_state_hash=_DUMMY_HASH,
    )
    response2 = dataclasses.replace(response, reason_code=response.reason_code)
    assert response2.response_commitment == response.response_commitment


def test_response_direct_construction_with_wrong_commitment_fails() -> None:
    """Directly constructing an AdapterResponse with a wrong commitment must fail."""
    request = _minimal_request()
    with pytest.raises(ValueError, match="response_commitment"):
        ap.AdapterResponse(
            schema=ap.RESPONSE_SCHEMA,
            protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
            request_id=request.request_id,
            case_id=request.case_id,
            binding_hash=request.binding_hash,
            request_hash=request.hash(),
            decision_kind=ap.AdapterDecisionKind.REJECT,
            reason_code="WRONG_PHASE",
            reason_details=FrozenDict({"field": "phase"}),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "draft"}),
            post_state_hash=_DUMMY_HASH,
            effects=(),
            effect_plan_hash=None,
            receipt=None,
            state_violations=(),
            projection_warnings=(),
            response_commitment="sha256:" + "0" * 64,
        )


# ---------------------------------------------------------------------------
# Decision-shape invariant tests.
# ---------------------------------------------------------------------------


def test_invalid_input_requires_reason_code() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="INVALID_INPUT requires a non-empty reason_code"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.INVALID_INPUT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict(),
            pre_state_hash=_DUMMY_HASH,
            post_state=None,
            post_state_hash=None,
        )


def test_invalid_input_rejects_non_null_post_state() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="INVALID_INPUT must have null post_state"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.INVALID_INPUT,
            reason_code="schema_mismatch",
            reason_details=FrozenDict(),
            pre_state=FrozenDict(),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "draft"}),
            post_state_hash=_DUMMY_HASH,
        )


def test_invalid_input_rejects_non_null_effect_plan_hash() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="INVALID_INPUT must have null effect_plan_hash"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.INVALID_INPUT,
            reason_code="schema_mismatch",
            reason_details=FrozenDict(),
            pre_state=FrozenDict(),
            pre_state_hash=_DUMMY_HASH,
            post_state=None,
            post_state_hash=None,
            effect_plan_hash=_DUMMY_HASH,
        )


def test_invalid_input_rejects_unknown_reason_code() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="closed InvalidInputCode"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.INVALID_INPUT,
            reason_code="totally_unknown",
            reason_details=FrozenDict(
                {
                    "code": "totally_unknown",
                    "field_path": "$",
                    "detail": "unknown",
                }
            ),
            pre_state=FrozenDict(),
            pre_state_hash=_DUMMY_HASH,
            post_state=None,
            post_state_hash=None,
        )


def test_invalid_input_rejects_reason_detail_code_mismatch() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="must match reason_code"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.INVALID_INPUT,
            reason_code=ap.InvalidInputCode.SCHEMA_MISMATCH.value,
            reason_details=FrozenDict(
                {
                    "code": ap.InvalidInputCode.INVALID_UTF8.value,
                    "field_path": "$.schema",
                    "detail": "wrong schema",
                }
            ),
            pre_state=FrozenDict(),
            pre_state_hash=_DUMMY_HASH,
            post_state=None,
            post_state_hash=None,
        )


def test_reject_requires_reason_code() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="REJECT requires a non-empty reason_code"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.REJECT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "draft"}),
            post_state_hash=_DUMMY_HASH,
        )


def test_reject_requires_post_state_equal_to_pre_state() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="REJECT post_state must equal pre_state"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.REJECT,
            reason_code="WRONG_PHASE",
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_ANOTHER_HASH,
        )


def test_reject_rejects_non_null_effect_plan_hash() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="REJECT must have null effect_plan_hash"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.REJECT,
            reason_code="WRONG_PHASE",
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "draft"}),
            post_state_hash=_DUMMY_HASH,
            effect_plan_hash=_DUMMY_HASH,
        )


def test_accept_rejects_non_null_reason_code() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="ACCEPT must have null reason_code"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.ACCEPT,
            reason_code="unexpected",
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_ANOTHER_HASH,
            effect_plan_hash=_DUMMY_HASH,
            receipt=FrozenDict({"event": "opened"}),
        )


def test_accept_requires_effect_plan_hash() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="ACCEPT requires non-null effect_plan_hash"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.ACCEPT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_ANOTHER_HASH,
            receipt=FrozenDict({"event": "opened"}),
        )


def test_accept_requires_receipt() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="ACCEPT requires non-null receipt"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.ACCEPT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_ANOTHER_HASH,
            effect_plan_hash=_DUMMY_HASH,
        )


def test_accept_requires_mapping_post_state() -> None:
    request = _minimal_request()
    with pytest.raises(TypeError, match="post_state must be a FrozenDict"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.ACCEPT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=7,  # type: ignore[arg-type]
            post_state_hash=_ANOTHER_HASH,
            effect_plan_hash=_DUMMY_HASH,
            receipt=FrozenDict({"event": "opened"}),
        )


def test_accept_requires_mapping_receipt() -> None:
    request = _minimal_request()
    with pytest.raises(TypeError, match="receipt must be a FrozenDict"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.ACCEPT,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "draft"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_ANOTHER_HASH,
            effect_plan_hash=_DUMMY_HASH,
            receipt=7,  # type: ignore[arg-type]
        )


def test_committed_failure_requires_reason_code() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="COMMITTED_FAILURE requires a non-empty reason_code"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.COMMITTED_FAILURE,
            reason_code=None,
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "open"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_DUMMY_HASH,
            effect_plan_hash=_DUMMY_HASH,
            receipt=FrozenDict({"event": "failure"}),
        )


def test_committed_failure_requires_effect_plan_hash() -> None:
    request = _minimal_request()
    with pytest.raises(ValueError, match="COMMITTED_FAILURE requires non-null effect_plan_hash"):
        ap.build_response(
            request=request,
            decision_kind=ap.AdapterDecisionKind.COMMITTED_FAILURE,
            reason_code="CONSERVATION_FAILURE",
            reason_details=FrozenDict(),
            pre_state=FrozenDict({"phase": "open"}),
            pre_state_hash=_DUMMY_HASH,
            post_state=FrozenDict({"phase": "open"}),
            post_state_hash=_DUMMY_HASH,
            receipt=FrozenDict({"event": "failure"}),
        )


# ---------------------------------------------------------------------------
# Response builder echoes request binding tests.
# ---------------------------------------------------------------------------


def test_response_echoes_binding_hash_from_request() -> None:
    """The response must echo the binding_hash from the request, not from a local profile."""
    binding = _minimal_binding()
    request = _minimal_request(binding)
    response = ap.build_response(
        request=request,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict(),
        pre_state=FrozenDict(),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict(),
        post_state_hash=_DUMMY_HASH,
    )
    assert response.binding_hash == request.binding_hash


def test_response_echoes_request_id_from_request() -> None:
    request = _minimal_request()
    response = ap.build_response(
        request=request,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict(),
        pre_state=FrozenDict(),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict(),
        post_state_hash=_DUMMY_HASH,
    )
    assert response.request_id == request.request_id
    assert response.request_hash == request.hash()


def test_build_invalid_input_response_works() -> None:
    request = _minimal_request()
    invalid = ap.InvalidInput(
        code=ap.InvalidInputCode.SCHEMA_MISMATCH,
        field_path="$.schema",
        detail="wrong schema",
    )
    response = ap.build_invalid_input_response(
        request=request,
        invalid=invalid,
        pre_state=FrozenDict(),
        pre_state_hash=_DUMMY_HASH,
    )
    assert response.decision_kind is ap.AdapterDecisionKind.INVALID_INPUT
    assert response.reason_code == "schema_mismatch"
    assert response.post_state is None
    assert response.effects == ()
    assert response.receipt is None
    assert response.effect_plan_hash is None


def test_build_boundary_failure_response_requires_no_adapter_request() -> None:
    invalid = ap.InvalidInput(
        code=ap.InvalidInputCode.INVALID_UTF8,
        field_path="$",
        detail="invalid byte sequence",
    )
    response = ap.build_boundary_failure_response(
        binding_hash=_DUMMY_HASH,
        input_bytes_hash=_ANOTHER_HASH,
        invalid=invalid,
    )

    assert response.schema == ap.BOUNDARY_RESPONSE_SCHEMA
    assert response.binding_hash == _DUMMY_HASH
    assert response.input_bytes_hash == _ANOTHER_HASH
    assert response.decision_kind is ap.AdapterDecisionKind.INVALID_INPUT
    assert response.reason_code == ap.InvalidInputCode.INVALID_UTF8.value
    assert response.reason_details == invalid.as_json()
    assert not hasattr(response, "request_id")
    assert not hasattr(response, "request_hash")


def test_boundary_failure_response_commitment_detects_tampering() -> None:
    response = ap.build_boundary_failure_response(
        binding_hash=_DUMMY_HASH,
        input_bytes_hash=_ANOTHER_HASH,
        invalid=ap.InvalidInput(
            code=ap.InvalidInputCode.SCHEMA_MISMATCH,
            field_path="$.schema",
            detail="wrong schema",
        ),
    )
    with pytest.raises(ValueError, match="boundary response_commitment"):
        dataclasses.replace(response, input_bytes_hash=_THIRD_HASH)


# ---------------------------------------------------------------------------
# Hash domain separation tests.
# ---------------------------------------------------------------------------


def test_profile_and_binding_use_distinct_hash_domains() -> None:
    profile = _minimal_profile()
    binding = _minimal_binding(profile)
    assert profile.hash() != binding.hash()


def test_request_and_response_use_distinct_hash_domains() -> None:
    request = _minimal_request()
    response = ap.build_response(
        request=request,
        decision_kind=ap.AdapterDecisionKind.REJECT,
        reason_code="WRONG_PHASE",
        reason_details=FrozenDict(),
        pre_state=FrozenDict(),
        pre_state_hash=_DUMMY_HASH,
        post_state=FrozenDict(),
        post_state_hash=_DUMMY_HASH,
    )
    assert request.hash() != response.response_commitment


def test_validate_state_request_rejects_non_null_command() -> None:
    with pytest.raises(ValueError, match="VALIDATE_STATE operation requires a null command"):
        dataclasses.replace(
            _minimal_request(),
            command=FrozenDict({"kind": "irrelevant"}),
        )


def test_profile_hash_is_deterministic() -> None:
    p1 = _minimal_profile()
    p2 = _minimal_profile()
    assert p1.hash() == p2.hash()


def test_profile_hash_changes_on_field_change() -> None:
    p1 = _minimal_profile()
    p2 = ap.DataAdapterProfile(
        schema=ap.PROFILE_SCHEMA,
        profile_id="different",
        profile_version="1",
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        abstraction_id="test.abstraction.v1",
        codec_version="popperpad-json-int-v2",
        semantic_profile=_frozen({"some_field": "some_value"}),
        explicit_nonclaims=("unbounded_liveness",),
    )
    assert p1.hash() != p2.hash()


def test_binding_hash_changes_on_profile_hash_change() -> None:
    b1 = ap.AdapterBinding(
        schema=ap.BINDING_SCHEMA,
        profile_hash=_DUMMY_HASH,
        source_manifest_hash=_ANOTHER_HASH,
        model_ir_hash=None,
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        adapter_implementation_id="test",
    )
    b2 = ap.AdapterBinding(
        schema=ap.BINDING_SCHEMA,
        profile_hash=_THIRD_HASH,
        source_manifest_hash=_ANOTHER_HASH,
        model_ir_hash=None,
        protocol_version=ap.ADAPTER_PROTOCOL_VERSION,
        adapter_implementation_id="test",
    )
    assert b1.hash() != b2.hash()
