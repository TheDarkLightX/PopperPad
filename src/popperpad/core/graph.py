from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecipeRecord:
    ref: str
    verdict_on_pass: str


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    ref: str
    recipe_ref: str
    context_ref: str | None
    subject_refs: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class TruthEdge:
    ref: str
    kind: str  # supports|refutes
    from_ref: str
    to_ref: str
    context_ref: str | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    hypothesis_ref: str
    context_ref: str | None
    accepted_recipe_refs: frozenset[str]
    edges: tuple[TruthEdge, ...]
    evidence: tuple[EvidenceRecord, ...]
    recipes: tuple[RecipeRecord, ...]


@dataclass(frozen=True, slots=True)
class StatusResult:
    state: str  # unknown|supported|falsified|disputed
    supports: tuple[str, ...]
    refutes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Obligation:
    obligation_id: str
    recipe_ref: str


@dataclass(frozen=True, slots=True)
class SemanticEdge:
    ref: str
    from_ref: str
    to_ref: str
    tag: str
    obligations: tuple[Obligation, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransferSnapshot:
    edges: tuple[SemanticEdge, ...]
    evidence: tuple[EvidenceRecord, ...]


@dataclass(frozen=True, slots=True)
class OpenObligation:
    edge_ref: str
    obligation_id: str
    recipe_ref: str


@dataclass(frozen=True, slots=True)
class TransferPath:
    edge_refs: tuple[str, ...]
    obligations_open: tuple[OpenObligation, ...]


def derive_status(snapshot: StatusSnapshot) -> StatusResult:
    """Purely derive status from one complete immutable graph snapshot."""

    evidence_by_ref = {record.ref: record for record in snapshot.evidence}
    recipes_by_ref = {record.ref: record for record in snapshot.recipes}
    supports: list[str] = []
    refutes: list[str] = []

    for edge in sorted(snapshot.edges, key=lambda value: value.ref):
        if edge.to_ref != snapshot.hypothesis_ref:
            continue
        if snapshot.context_ref is not None and edge.context_ref != snapshot.context_ref:
            continue
        if not _truth_edge_admissible(
            edge,
            hypothesis_ref=snapshot.hypothesis_ref,
            accepted_recipe_refs=snapshot.accepted_recipe_refs,
            evidence_by_ref=evidence_by_ref,
            recipes_by_ref=recipes_by_ref,
        ):
            continue
        if edge.kind == "supports":
            supports.append(edge.ref)
        elif edge.kind == "refutes":
            refutes.append(edge.ref)

    return StatusResult(
        state=_classify(supports, refutes),
        supports=tuple(supports),
        refutes=tuple(refutes),
    )


def _truth_edge_admissible(
    edge: TruthEdge,
    *,
    hypothesis_ref: str,
    accepted_recipe_refs: frozenset[str],
    evidence_by_ref: dict[str, EvidenceRecord],
    recipes_by_ref: dict[str, RecipeRecord],
) -> bool:
    expected_verdict = {"supports": "support", "refutes": "refute"}.get(edge.kind)
    if expected_verdict is None:
        return False
    for evidence_ref in edge.evidence_refs:
        evidence = evidence_by_ref.get(evidence_ref)
        if evidence is None:
            continue
        if hypothesis_ref not in evidence.subject_refs:
            continue
        if evidence.context_ref != edge.context_ref:
            continue
        if evidence.status.lower() != "pass":
            continue
        if evidence.recipe_ref not in accepted_recipe_refs:
            continue
        recipe = recipes_by_ref.get(evidence.recipe_ref)
        if recipe is None or recipe.verdict_on_pass != expected_verdict:
            continue
        return True
    return False


def _classify(supports: list[str], refutes: list[str]) -> str:
    if supports and refutes:
        return "disputed"
    if refutes:
        return "falsified"
    if supports:
        return "supported"
    return "unknown"


def find_transfer_paths(
    snapshot: TransferSnapshot,
    *,
    from_ref: str,
    to_ref: str,
    max_depth: int,
    require_validated: bool,
) -> tuple[TransferPath, ...]:
    """Enumerate deterministic simple paths from a complete immutable snapshot."""

    if not 1 <= max_depth <= 12:
        raise ValueError("max_depth out of bounds")
    edge_by_ref = {edge.ref: edge for edge in snapshot.edges}
    evidence_by_ref = {record.ref: record for record in snapshot.evidence}
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in sorted(snapshot.edges, key=lambda value: value.ref):
        adjacency.setdefault(edge.from_ref, []).append((edge.ref, edge.to_ref))
        if edge.tag == "≅":
            adjacency.setdefault(edge.to_ref, []).append((edge.ref, edge.from_ref))
    for targets in adjacency.values():
        targets.sort()

    found: list[TransferPath] = []
    queue: list[tuple[str, tuple[str, ...], frozenset[str]]] = [
        (from_ref, (), frozenset({from_ref}))
    ]
    while queue:
        node, edge_path, visited_nodes = queue.pop(0)
        if node == to_ref:
            found.append(
                TransferPath(
                    edge_refs=edge_path,
                    obligations_open=_open_path_obligations(
                        edge_path, edge_by_ref=edge_by_ref, evidence_by_ref=evidence_by_ref
                    ),
                )
            )
            continue
        if len(edge_path) >= max_depth:
            continue
        for edge_ref, next_node in adjacency.get(node, ()):
            if next_node in visited_nodes:
                continue
            edge = edge_by_ref[edge_ref]
            open_obligations = _open_edge_obligations(edge, evidence_by_ref)
            if require_validated and open_obligations:
                continue
            queue.append(
                (
                    next_node,
                    (*edge_path, edge_ref),
                    visited_nodes | frozenset({next_node}),
                )
            )

    return tuple(sorted(found, key=lambda path: path.edge_refs))


def _open_path_obligations(
    edge_refs: tuple[str, ...],
    *,
    edge_by_ref: dict[str, SemanticEdge],
    evidence_by_ref: dict[str, EvidenceRecord],
) -> tuple[OpenObligation, ...]:
    obligations: list[OpenObligation] = []
    for edge_ref in edge_refs:
        obligations.extend(_open_edge_obligations(edge_by_ref[edge_ref], evidence_by_ref))
    return tuple(obligations)


def _open_edge_obligations(
    edge: SemanticEdge, evidence_by_ref: dict[str, EvidenceRecord]
) -> tuple[OpenObligation, ...]:
    open_values: list[OpenObligation] = []
    for obligation in edge.obligations:
        if _obligation_satisfied(obligation, edge.evidence_refs, evidence_by_ref):
            continue
        open_values.append(
            OpenObligation(
                edge_ref=edge.ref,
                obligation_id=obligation.obligation_id,
                recipe_ref=obligation.recipe_ref,
            )
        )
    return tuple(open_values)


def _obligation_satisfied(
    obligation: Obligation,
    evidence_refs: tuple[str, ...],
    evidence_by_ref: dict[str, EvidenceRecord],
) -> bool:
    for evidence_ref in evidence_refs:
        evidence = evidence_by_ref.get(evidence_ref)
        if evidence is None:
            continue
        if evidence.recipe_ref == obligation.recipe_ref and evidence.status.lower() == "pass":
            return True
    return False
