"""Exact provenance of a derived hypothesis status. Pure; same inputs as ``derive_status``.

A *derivation* is one reason a status counts: a support or refute edge to the hypothesis,
together with one evidence record that admits it under the hypothesis's accepted recipes.
The admission rule is ``core.graph.admitting_evidence``, the one ``derive_status`` uses, so
the derived state here always equals ``derive_status``.

Each derivation uses exactly one edge, one evidence record, one recipe and one source (the
edge's ``from_ref``). So removing every distinct item of one kind from a side removes all of
that side's derivations, and nothing smaller does. That count is the side's *cut* for that
kind; a cut of one is a single point of failure. *Shared* items are those used by every
derivation of a side.
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph import (
    EvidenceRecord,
    StatusSnapshot,
    admitting_evidence,
    classify_state,
    derive_status,
)
from .values import DeeplyImmutable

KINDS = ("edge", "evidence", "recipe", "source")


@dataclass(frozen=True, slots=True)
class Derivation(DeeplyImmutable):
    edge_ref: str
    evidence_ref: str
    recipe_ref: str
    source_ref: str

    def item(self, kind: str) -> str:
        return {"edge": self.edge_ref, "evidence": self.evidence_ref, "recipe": self.recipe_ref,
                "source": self.source_ref}[kind]


@dataclass(frozen=True, slots=True)
class Cut(DeeplyImmutable):
    """Removing ``items``, every distinct item of ``kind`` on one side, removes the side."""

    kind: str
    items: tuple[str, ...]
    shared: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError("cut kind must be edge, evidence, recipe or source")
        DeeplyImmutable.__post_init__(self)

    @property
    def size(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class SideProvenance(DeeplyImmutable):
    side: str  # supports|refutes
    derivations: tuple[Derivation, ...]
    cuts: tuple[Cut, ...]

    def __post_init__(self) -> None:
        if self.side not in {"supports", "refutes"}:
            raise ValueError("side must be supports or refutes")
        DeeplyImmutable.__post_init__(self)

    def cut(self, kind: str) -> Cut:
        return next(c for c in self.cuts if c.kind == kind)

    @property
    def single_points_of_failure(self) -> tuple[Cut, ...]:
        return tuple(c for c in self.cuts if c.size == 1)


@dataclass(frozen=True, slots=True)
class StateChange(DeeplyImmutable):
    """Removing ``items`` from the ``side`` derivations changes the state to ``to_state``."""

    side: str
    kind: str
    items: tuple[str, ...]
    to_state: str


@dataclass(frozen=True, slots=True)
class ProvenanceResult(DeeplyImmutable):
    state: str
    supports: SideProvenance
    refutes: SideProvenance
    changes: tuple[StateChange, ...]  # smallest removals first

    @property
    def smallest_change(self) -> int | None:
        return min((len(c.items) for c in self.changes), default=None)


def derive_provenance(snapshot: StatusSnapshot) -> ProvenanceResult:
    """Every derivation of the hypothesis's status, its cuts, and the removals that change it."""
    evidence_by_ref = {record.ref: record for record in snapshot.evidence}
    recipes_by_ref = {record.ref: record for record in snapshot.recipes}
    found: dict[str, list[Derivation]] = {"supports": [], "refutes": []}
    for edge in sorted(snapshot.edges, key=lambda value: value.ref):
        if edge.to_ref != snapshot.hypothesis_ref:
            continue
        if snapshot.context_ref is not None and edge.context_ref != snapshot.context_ref:
            continue
        admitted: tuple[EvidenceRecord, ...] = admitting_evidence(
            edge,
            hypothesis_ref=snapshot.hypothesis_ref,
            accepted_recipe_refs=snapshot.accepted_recipe_refs,
            evidence_by_ref=evidence_by_ref,
            recipes_by_ref=recipes_by_ref,
        )
        for evidence in admitted:
            found[edge.kind].append(Derivation(edge.ref, evidence.ref, evidence.recipe_ref, edge.from_ref))
    supports, refutes = _side("supports", found["supports"]), _side("refutes", found["refutes"])
    state = classify_state(bool(supports.derivations), bool(refutes.derivations))
    if state != derive_status(snapshot).state:  # The shared admission rule makes this unreachable.
        raise AssertionError("provenance and status disagree")
    return ProvenanceResult(state=state, supports=supports, refutes=refutes, changes=_changes(supports, refutes))


def _side(side: str, derivations: list[Derivation]) -> SideProvenance:
    ordered = tuple(sorted(set(derivations), key=lambda d: (d.edge_ref, d.evidence_ref)))
    cuts = []
    for kind in KINDS:
        items = tuple(sorted({d.item(kind) for d in ordered}))
        shared = items if len(items) == 1 else ()
        cuts.append(Cut(kind=kind, items=items, shared=shared))
    return SideProvenance(side=side, derivations=ordered, cuts=tuple(cuts))


def _changes(supports: SideProvenance, refutes: SideProvenance) -> tuple[StateChange, ...]:
    changes = []
    for side in (supports, refutes):
        if not side.derivations:
            continue
        for kind in KINDS:
            removed = set(side.cut(kind).items)
            # A source may appear on both sides; removing it removes its derivations there too.
            left = {"supports": supports, "refutes": refutes}
            remaining = {
                name: any(d.item(kind) not in removed for d in value.derivations) if kind == "source" or name == side.side
                else bool(value.derivations)
                for name, value in left.items()
            }
            to_state = classify_state(remaining["supports"], remaining["refutes"])
            changes.append(StateChange(side=side.side, kind=kind, items=side.cut(kind).items, to_state=to_state))
    return tuple(sorted(changes, key=lambda c: (len(c.items), c.side, KINDS.index(c.kind))))
