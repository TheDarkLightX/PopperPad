from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from popperpad.core.graph import (
    EvidenceRecord,
    RecipeRecord,
    StatusSnapshot,
    TruthEdge,
    derive_status,
)
from popperpad.core.provenance import derive_provenance


def ref(n: int) -> str:
    return f"sha256:{n:064x}"


H = ref(1)
SUPPORT_A, SUPPORT_B, REFUTE = ref(10), ref(11), ref(12)
RECIPES = (RecipeRecord(SUPPORT_A, "support"), RecipeRecord(SUPPORT_B, "support"), RecipeRecord(REFUTE, "refute"))
ACCEPTED = frozenset({SUPPORT_A, SUPPORT_B, REFUTE})


def evidence(n: int, recipe: str, status: str = "pass") -> EvidenceRecord:
    return EvidenceRecord(ref=ref(n), recipe_ref=recipe, context_ref=None, subject_refs=(H,), status=status)


def edge(n: int, kind: str, source: int, evidence_refs: tuple[int, ...]) -> TruthEdge:
    return TruthEdge(ref=ref(n), kind=kind, from_ref=ref(source), to_ref=H, context_ref=None,
                     evidence_refs=tuple(ref(e) for e in evidence_refs))


def snapshot(edges, records) -> StatusSnapshot:
    return StatusSnapshot(hypothesis_ref=H, context_ref=None, accepted_recipe_refs=ACCEPTED,
                          edges=tuple(edges), evidence=tuple(records), recipes=RECIPES)


def test_one_derivation_is_a_single_point_of_failure_of_every_kind() -> None:
    result = derive_provenance(snapshot([edge(100, "supports", 50, (200,))], [evidence(200, SUPPORT_A)]))
    assert result.state == "supported"
    assert len(result.supports.derivations) == 1
    assert {c.kind for c in result.supports.single_points_of_failure} == {"edge", "evidence", "recipe", "source"}
    assert result.smallest_change == 1
    assert {(c.kind, c.to_state) for c in result.changes} == {
        ("edge", "unknown"), ("evidence", "unknown"), ("recipe", "unknown"), ("source", "unknown")}


def test_independent_evidence_from_one_recipe_still_has_one_verification_method() -> None:
    result = derive_provenance(snapshot(
        [edge(100, "supports", 50, (200,)), edge(101, "supports", 51, (201,))],
        [evidence(200, SUPPORT_A), evidence(201, SUPPORT_A)],
    ))
    assert len(result.supports.derivations) == 2
    assert result.supports.cut("evidence").size == 2
    assert result.supports.cut("source").size == 2
    recipe = result.supports.cut("recipe")
    assert recipe.size == 1 and recipe.shared == (SUPPORT_A,)
    assert [c.kind for c in result.changes if len(c.items) == 1] == ["recipe"]


def test_one_edge_with_several_admitting_records_counts_each_record() -> None:
    result = derive_provenance(snapshot(
        [edge(100, "supports", 50, (200, 201, 202, 200))],
        [evidence(200, SUPPORT_A), evidence(201, SUPPORT_B), evidence(202, SUPPORT_B, status="fail")],
    ))
    assert len(result.supports.derivations) == 2  # the failing record admits nothing; duplicates count once
    assert result.supports.cut("edge").size == 1
    assert result.supports.cut("recipe").size == 2


def test_disputed_changes_by_removing_either_side_or_a_shared_source() -> None:
    result = derive_provenance(snapshot(
        [edge(100, "supports", 50, (200,)), edge(101, "refutes", 50, (201,)), edge(102, "refutes", 52, (202,))],
        [evidence(200, SUPPORT_A), evidence(201, REFUTE), evidence(202, REFUTE)],
    ))
    assert result.state == "disputed"
    to_state = {(c.side, c.kind): c.to_state for c in result.changes}
    assert to_state[("supports", "evidence")] == "falsified"
    assert to_state[("refutes", "evidence")] == "supported"
    # Source 50 backs the support and one refutation: removing it leaves only the other refutation.
    assert to_state[("supports", "source")] == "falsified"
    # Both refutations share one recipe, so either side can be removed with one item.
    assert result.refutes.cut("recipe").size == 1 and result.smallest_change == 1
    assert {c.side for c in result.changes if len(c.items) == 1} == {"supports", "refutes"}


def test_unknown_status_has_no_derivations_or_changes() -> None:
    result = derive_provenance(snapshot([edge(100, "supports", 50, (200,))], [evidence(200, SUPPORT_A, "fail")]))
    assert result.state == "unknown"
    assert result.changes == () and result.smallest_change is None


record_ids = st.integers(min_value=200, max_value=206)


@st.composite
def snapshots(draw) -> StatusSnapshot:
    records = [evidence(n, draw(st.sampled_from((SUPPORT_A, SUPPORT_B, REFUTE, ref(13)))),
                        draw(st.sampled_from(("pass", "pass", "fail"))))
               for n in sorted(draw(st.sets(record_ids, max_size=6)))]
    edges = [edge(100 + i, draw(st.sampled_from(("supports", "refutes"))), draw(st.integers(50, 53)),
                  tuple(draw(st.lists(record_ids, max_size=3))))
             for i in range(draw(st.integers(0, 6)))]
    return snapshot(edges, records)


@settings(max_examples=300, deadline=None)
@given(snapshots())
def test_provenance_agrees_with_derive_status(value: StatusSnapshot) -> None:
    status, result = derive_status(value), derive_provenance(value)
    assert result.state == status.state
    assert tuple(sorted({d.edge_ref for d in result.supports.derivations})) == status.supports
    assert tuple(sorted({d.edge_ref for d in result.refutes.derivations})) == status.refutes
    for change in result.changes:  # removing a change's items really reaches its state
        kept = {
            side.side: [d for d in side.derivations
                        if d.item(change.kind) not in change.items or (side.side != change.side and change.kind != "source")]
            for side in (result.supports, result.refutes)
        }
        reached = ("disputed" if kept["supports"] and kept["refutes"] else "falsified" if kept["refutes"]
                   else "supported" if kept["supports"] else "unknown")
        assert reached == change.to_state != result.state
