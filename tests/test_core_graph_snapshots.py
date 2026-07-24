from __future__ import annotations

from popperpad.core.graph import (
    EvidenceRecord,
    Obligation,
    RecipeRecord,
    SemanticEdge,
    StatusSnapshot,
    TransferSnapshot,
    TruthEdge,
    derive_status,
    find_transfer_paths,
)
from popperpad.graph import find_transfer_paths as find_transfer_paths_shell


def R(char: str) -> str:
    return "sha256:" + char * 64


def test_status_is_derived_from_one_complete_immutable_snapshot() -> None:
    hypothesis = R("1")
    recipe = R("2")
    evidence = R("3")
    edge = R("4")
    snapshot = StatusSnapshot(
        hypothesis_ref=hypothesis,
        context_ref=None,
        accepted_recipe_refs=frozenset({recipe}),
        edges=(
            TruthEdge(
                ref=edge,
                kind="supports",
                from_ref=evidence,
                to_ref=hypothesis,
                context_ref=None,
                evidence_refs=(evidence,),
            ),
        ),
        evidence=(
            EvidenceRecord(
                ref=evidence,
                recipe_ref=recipe,
                context_ref=None,
                subject_refs=(hypothesis,),
                status="pass",
            ),
        ),
        recipes=(RecipeRecord(ref=recipe, verdict_on_pass="support"),),
    )
    result = derive_status(snapshot)
    assert result.state == "supported"
    assert result.supports == (edge,)


def test_status_is_order_invariant_and_fails_closed_on_recipe_mismatch() -> None:
    hypothesis = R("1")
    recipe = R("2")
    evidence_a = R("3")
    evidence_b = R("4")
    edge_a = TruthEdge(R("a"), "supports", evidence_a, hypothesis, None, (evidence_a,))
    edge_b = TruthEdge(R("b"), "refutes", evidence_b, hypothesis, None, (evidence_b,))
    records = (
        EvidenceRecord(evidence_a, recipe, None, (hypothesis,), "pass"),
        EvidenceRecord(evidence_b, recipe, None, (hypothesis,), "pass"),
    )
    first = derive_status(
        StatusSnapshot(
            hypothesis,
            None,
            frozenset({recipe}),
            (edge_b, edge_a),
            records,
            (RecipeRecord(recipe, "support"),),
        )
    )
    second = derive_status(
        StatusSnapshot(
            hypothesis,
            None,
            frozenset({recipe}),
            (edge_a, edge_b),
            tuple(reversed(records)),
            (RecipeRecord(recipe, "support"),),
        )
    )
    assert first == second
    assert first.state == "supported"
    assert first.refutes == ()


def test_transfer_search_uses_explicit_evidence_snapshot_and_simple_paths() -> None:
    a, b, c = R("a"), R("b"), R("c")
    recipe = R("d")
    evidence = R("e")
    edge_ab = SemanticEdge(
        ref=R("1"),
        from_ref=a,
        to_ref=b,
        tag="↦",
        obligations=(Obligation("check-ab", recipe),),
        evidence_refs=(evidence,),
    )
    edge_bc = SemanticEdge(
        ref=R("2"),
        from_ref=b,
        to_ref=c,
        tag="↦",
        obligations=(),
        evidence_refs=(),
    )
    edge_ca = SemanticEdge(
        ref=R("3"),
        from_ref=c,
        to_ref=a,
        tag="↦",
        obligations=(),
        evidence_refs=(),
    )
    snapshot = TransferSnapshot(
        edges=(edge_ca, edge_bc, edge_ab),
        evidence=(EvidenceRecord(evidence, recipe, None, (), "pass"),),
    )
    paths = find_transfer_paths(
        snapshot,
        from_ref=a,
        to_ref=c,
        max_depth=4,
        require_validated=True,
    )
    assert len(paths) == 1
    assert paths[0].edge_refs == (edge_ab.ref, edge_bc.ref)
    assert paths[0].obligations_open == ()


def test_unmet_obligation_is_reported_or_blocks_validated_path() -> None:
    a, b = R("a"), R("b")
    edge = SemanticEdge(
        ref=R("1"),
        from_ref=a,
        to_ref=b,
        tag="↦",
        obligations=(Obligation("proof", R("d")),),
        evidence_refs=(),
    )
    snapshot = TransferSnapshot(edges=(edge,), evidence=())
    open_paths = find_transfer_paths(
        snapshot,
        from_ref=a,
        to_ref=b,
        max_depth=2,
        require_validated=False,
    )
    assert open_paths[0].obligations_open[0].obligation_id == "proof"
    assert find_transfer_paths(
        snapshot,
        from_ref=a,
        to_ref=b,
        max_depth=2,
        require_validated=True,
    ) == ()


def test_shell_resolves_each_evidence_ref_once_before_core_search() -> None:
    a, b = R("a"), R("b")
    recipe, evidence, edge_ref = R("c"), R("d"), R("e")
    edge = {
        "edge_type": "semantic",
        "from_ref": a,
        "to_ref": b,
        "tag": "↦",
        "obligations": [{"obligation_id": "o", "recipe_ref": recipe}],
        "evidence_refs": [evidence],
    }
    calls: list[str] = []

    def lookup(ref: str):
        calls.append(ref)
        return {
            "schema": "popperpad/evidence/v1",
            "recipe_ref": recipe,
            "subject_refs": [],
            "result": {"status": "pass"},
        }

    paths = find_transfer_paths_shell(
        [(edge_ref, edge)],
        from_ref=a,
        to_ref=b,
        max_depth=2,
        require_validated=True,
        evidence_lookup=lookup,
    )
    assert calls == [evidence]
    assert paths == [{"path": [edge_ref], "obligations_open": []}]
