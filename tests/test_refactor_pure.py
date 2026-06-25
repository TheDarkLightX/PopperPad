from __future__ import annotations

import pytest

from popperpad.canonical import canonical_json_bytes, sha256_bytes, stable_sha256
from popperpad.graph import compute_status, find_transfer_paths
from popperpad.refs import ClaimState, Ref, RunMode, ValidationError, is_ref


def test_ref_rejects_invalid_and_serializes_as_str() -> None:
    assert str(Ref("sha256:" + "a" * 64)) == "sha256:" + "a" * 64
    with pytest.raises(ValidationError):
        Ref("not-a-ref")
    with pytest.raises(ValidationError):
        Ref("sha256:abcd")
    assert is_ref("sha256:" + "0" * 64)
    assert not is_ref("nope")
    assert Ref.parse(None) is None
    assert Ref.parse("") is None


def test_status_pure_over_loaded_edges() -> None:
    hyp = "sha256:" + "1" * 64
    ev = "sha256:" + "2" * 64
    edges = [
        (ev, {"schema": "popperpad/edge/v1", "edge_type": "supports", "to_ref": hyp, "from_ref": ev, "evidence_refs": []}),
    ]
    st = compute_status(edges, hyp_ref=hyp, context_ref=None)
    assert st.state == ClaimState.SUPPORTED.value
    assert st.supports == [ev]


def test_status_disputed_when_supports_and_refutes() -> None:
    hyp = "sha256:" + "1" * 64
    a = "sha256:" + "a" * 64
    b = "sha256:" + "b" * 64
    edges = [
        (a, {"edge_type": "supports", "to_ref": hyp, "from_ref": a, "evidence_refs": []}),
        (b, {"edge_type": "refutes", "to_ref": hyp, "from_ref": b, "evidence_refs": []}),
    ]
    assert compute_status(edges, hyp_ref=hyp, context_ref=None).state == "disputed"


def test_transfer_paths_pure_bfs_with_equivalence() -> None:
    a = "sha256:" + "a" * 64
    b = "sha256:" + "b" * 64
    edge_ref = "sha256:" + "e" * 64
    edges = [
        (edge_ref, {"edge_type": "semantic", "from_ref": a, "to_ref": b, "tag": "≅", "obligations": [], "evidence_refs": []}),
    ]
    paths = find_transfer_paths(
        edges, from_ref=a, to_ref=b, max_depth=2, require_validated=False, evidence_lookup=lambda _r: None
    )
    assert any(p["path"] == [edge_ref] for p in paths)
    # equivalence is symmetric
    paths_back = find_transfer_paths(
        edges, from_ref=b, to_ref=a, max_depth=2, require_validated=False, evidence_lookup=lambda _r: None
    )
    assert any(p["path"] == [edge_ref] for p in paths_back)


def test_canonical_round_trip_is_idempotent_and_deterministic() -> None:
    obj = {"b": [1, 2], "a": {"y": True, "x": None}, "n": 3.5}
    bytes_a = canonical_json_bytes(obj)
    bytes_b = canonical_json_bytes(obj)
    assert bytes_a == bytes_b
    assert stable_sha256(obj) == sha256_bytes(bytes_a)
    assert canonical_json_bytes(obj) == canonical_json_bytes(canonical_json_bytes(obj).decode("utf-8") and obj)


def test_run_mode_enum_dispatches_prove_and_refute() -> None:
    assert RunMode("prove") is RunMode.PROVE
    assert RunMode("refute") is RunMode.REFUTE
    with pytest.raises(ValueError):
        RunMode("bogus")
