from __future__ import annotations

import pytest

from popperpad.canonical import canonical_hash, canonical_json_bytes, sha256_bytes, stable_sha256
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


def _accepted_edge(*, hyp: str, suffix: str, edge_type: str) -> tuple[str, dict, dict[str, dict]]:
    edge_ref = "sha256:" + suffix * 64
    evidence_ref = "sha256:" + ("e" if edge_type == "supports" else "d") * 64
    recipe_ref = "sha256:" + ("c" if edge_type == "supports" else "f") * 64
    verdict = "support" if edge_type == "supports" else "refute"
    edge = {
        "schema": "popperpad/edge/v1",
        "edge_type": edge_type,
        "to_ref": hyp,
        "from_ref": evidence_ref,
        "context_ref": None,
        "evidence_refs": [evidence_ref],
    }
    objects = {
        evidence_ref: {
            "schema": "popperpad/evidence/v1",
            "recipe_ref": recipe_ref,
            "context_ref": None,
            "subject_refs": [hyp],
            "result": {"status": "pass"},
        },
        recipe_ref: {
            "schema": "popperpad/recipe/v1",
            "recipe_id": f"{edge_type}-recipe",
            "argv": ["true"],
            "verdict_on_pass": verdict,
        },
    }
    return edge_ref, edge, objects


def test_status_pure_over_loaded_evidence() -> None:
    hyp = "sha256:" + "1" * 64
    edge_ref, edge, objects = _accepted_edge(hyp=hyp, suffix="a", edge_type="supports")
    st = compute_status(
        [(edge_ref, edge)],
        hyp_ref=hyp,
        context_ref=None,
        objects=objects,
        accepted_recipe_refs=frozenset({objects[edge["evidence_refs"][0]]["recipe_ref"]}),
    )
    assert st.state == ClaimState.SUPPORTED.value
    assert st.supports == (edge_ref,)


def test_status_ignores_evidence_free_truth_edge() -> None:
    hyp = "sha256:" + "1" * 64
    edge_ref = "sha256:" + "a" * 64
    edge = {
        "schema": "popperpad/edge/v1",
        "edge_type": "supports",
        "to_ref": hyp,
        "from_ref": edge_ref,
        "evidence_refs": [],
    }
    st = compute_status(
        [(edge_ref, edge)],
        hyp_ref=hyp,
        context_ref=None,
        objects={},
        accepted_recipe_refs=frozenset(),
    )
    assert st.state == ClaimState.UNKNOWN.value
    assert st.supports == ()


def test_status_ignores_evidence_with_mismatched_recipe_verdict() -> None:
    hyp = "sha256:" + "1" * 64
    edge_ref, edge, objects = _accepted_edge(hyp=hyp, suffix="a", edge_type="supports")
    evidence_ref = edge["evidence_refs"][0]
    recipe_ref = objects[evidence_ref]["recipe_ref"]
    objects[recipe_ref]["verdict_on_pass"] = "refute"
    assert compute_status(
        [(edge_ref, edge)],
        hyp_ref=hyp,
        context_ref=None,
        objects=objects,
        accepted_recipe_refs=frozenset({recipe_ref}),
    ).state == "unknown"


def test_status_ignores_evidence_from_wrong_context() -> None:
    hyp = "sha256:" + "1" * 64
    edge_ref, edge, objects = _accepted_edge(hyp=hyp, suffix="a", edge_type="supports")
    evidence_ref = edge["evidence_refs"][0]
    recipe_ref = objects[evidence_ref]["recipe_ref"]
    objects[evidence_ref]["context_ref"] = "sha256:" + "9" * 64
    assert compute_status(
        [(edge_ref, edge)],
        hyp_ref=hyp,
        context_ref=None,
        objects=objects,
        accepted_recipe_refs=frozenset({recipe_ref}),
    ).state == "unknown"


def test_status_ignores_evidence_from_unaccepted_recipe() -> None:
    hyp = "sha256:" + "1" * 64
    edge_ref, edge, objects = _accepted_edge(hyp=hyp, suffix="a", edge_type="supports")
    assert compute_status(
        [(edge_ref, edge)],
        hyp_ref=hyp,
        context_ref=None,
        objects=objects,
        accepted_recipe_refs=frozenset(),
    ).state == "unknown"


def test_status_disputed_when_admissible_supports_and_refutes_exist() -> None:
    hyp = "sha256:" + "1" * 64
    support_ref, support_edge, support_objects = _accepted_edge(hyp=hyp, suffix="a", edge_type="supports")
    refute_ref, refute_edge, refute_objects = _accepted_edge(hyp=hyp, suffix="b", edge_type="refutes")
    objects = {**support_objects, **refute_objects}
    result = compute_status(
        [(support_ref, support_edge), (refute_ref, refute_edge)],
        hyp_ref=hyp,
        context_ref=None,
        objects=objects,
        accepted_recipe_refs=frozenset(
            {
                support_objects[support_edge["evidence_refs"][0]]["recipe_ref"],
                refute_objects[refute_edge["evidence_refs"][0]]["recipe_ref"],
            }
        ),
    )
    assert result.state == "disputed"
    assert result.supports == (support_ref,)
    assert result.refutes == (refute_ref,)


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
    paths_back = find_transfer_paths(
        edges, from_ref=b, to_ref=a, max_depth=2, require_validated=False, evidence_lookup=lambda _r: None
    )
    assert any(p["path"] == [edge_ref] for p in paths_back)


def test_canonical_round_trip_is_integer_only_and_deterministic() -> None:
    obj = {"b": [1, 2], "a": {"y": True, "x": None}, "n": 35}
    encoded = canonical_json_bytes(obj)
    assert encoded == canonical_json_bytes(obj)
    assert stable_sha256(obj) == sha256_bytes(encoded)
    assert canonical_hash("canonical-json/v2", obj) != stable_sha256(obj)
    with pytest.raises(TypeError, match="floating-point"):
        canonical_json_bytes({"n": 3.5})


def test_run_mode_enum_dispatches_prove_and_refute() -> None:
    assert RunMode("prove") is RunMode.PROVE
    assert RunMode("refute") is RunMode.REFUTE
    with pytest.raises(ValueError):
        RunMode("bogus")
