from __future__ import annotations

from typing import AbstractSet, Any, Callable, Iterable, Mapping

from .core.graph import (
    EvidenceRecord,
    Obligation,
    RecipeRecord,
    SemanticEdge,
    StatusResult,
    StatusSnapshot,
    TransferSnapshot,
    TruthEdge,
    derive_status,
    find_transfer_paths as find_transfer_paths_core,
)
from .refs import is_ref, require
from .schemas import SCHEMA_EDGE_V1, SCHEMA_EVIDENCE_V1, SCHEMA_RECIPE_V1


EvidenceLookup = Callable[[str], Mapping[str, Any] | None]
StatusObjects = Mapping[str, Mapping[str, Any]]


def _parse_evidence(ref: str, raw: Mapping[str, Any]) -> EvidenceRecord | None:
    if str(raw.get("schema")) != SCHEMA_EVIDENCE_V1:
        return None
    recipe_ref = raw.get("recipe_ref")
    if not is_ref(recipe_ref):
        return None
    context_raw = raw.get("context_ref")
    context_ref = None if context_raw is None else str(context_raw)
    if context_ref is not None and not is_ref(context_ref):
        return None
    subjects_raw = raw.get("subject_refs", ()) or ()
    if not isinstance(subjects_raw, (list, tuple)) or isinstance(subjects_raw, (str, bytes)):
        return None
    subject_refs = tuple(str(value) for value in subjects_raw if is_ref(value))
    result = raw.get("result")
    if not isinstance(result, Mapping):
        return None
    return EvidenceRecord(
        ref=ref,
        recipe_ref=str(recipe_ref),
        context_ref=context_ref,
        subject_refs=subject_refs,
        status=str(result.get("status", "")),
    )


def _parse_recipe(ref: str, raw: Mapping[str, Any]) -> RecipeRecord | None:
    if str(raw.get("schema")) != SCHEMA_RECIPE_V1:
        return None
    return RecipeRecord(ref=ref, verdict_on_pass=str(raw.get("verdict_on_pass", "support")))


def _parse_truth_edge(ref: str, raw: Mapping[str, Any]) -> TruthEdge | None:
    if str(raw.get("schema")) != SCHEMA_EDGE_V1:
        return None
    kind = str(raw.get("edge_type", ""))
    if kind not in {"supports", "refutes"}:
        return None
    from_ref = raw.get("from_ref")
    to_ref = raw.get("to_ref")
    if not (is_ref(from_ref) and is_ref(to_ref)):
        return None
    context_raw = raw.get("context_ref")
    context_ref = None if context_raw is None else str(context_raw)
    if context_ref is not None and not is_ref(context_ref):
        return None
    evidence_raw = raw.get("evidence_refs", ()) or ()
    if not isinstance(evidence_raw, (list, tuple)) or isinstance(evidence_raw, (str, bytes)):
        return None
    return TruthEdge(
        ref=ref,
        kind=kind,
        from_ref=str(from_ref),
        to_ref=str(to_ref),
        context_ref=context_ref,
        evidence_refs=tuple(str(value) for value in evidence_raw if is_ref(value)),
    )


def compute_status(
    edges: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    hyp_ref: str,
    context_ref: str | None,
    objects: StatusObjects,
    accepted_recipe_refs: AbstractSet[str],
) -> StatusResult:
    """Shell adapter: load one immutable snapshot, then call pure graph semantics."""

    require(is_ref(hyp_ref), "invalid hypothesis ref")
    if context_ref is not None:
        require(is_ref(context_ref), "invalid context ref")

    parsed_edges: list[TruthEdge] = []
    evidence_refs: set[str] = set()
    for ref, raw in edges:
        parsed = _parse_truth_edge(ref, raw)
        if parsed is None:
            continue
        parsed_edges.append(parsed)
        evidence_refs.update(parsed.evidence_refs)

    evidence: list[EvidenceRecord] = []
    for ref in sorted(evidence_refs):
        raw = objects.get(ref)
        if isinstance(raw, Mapping):
            parsed = _parse_evidence(ref, raw)
            if parsed is not None:
                evidence.append(parsed)

    recipes: list[RecipeRecord] = []
    for ref in sorted(accepted_recipe_refs):
        raw = objects.get(ref)
        if isinstance(raw, Mapping):
            parsed = _parse_recipe(ref, raw)
            if parsed is not None:
                recipes.append(parsed)

    return derive_status(
        StatusSnapshot(
            hypothesis_ref=hyp_ref,
            context_ref=context_ref,
            accepted_recipe_refs=frozenset(str(ref) for ref in accepted_recipe_refs),
            edges=tuple(parsed_edges),
            evidence=tuple(evidence),
            recipes=tuple(recipes),
        )
    )


def _parse_semantic_edge(ref: str, raw: Mapping[str, Any]) -> SemanticEdge | None:
    if str(raw.get("edge_type")) != "semantic":
        return None
    from_ref = raw.get("from_ref")
    to_ref = raw.get("to_ref")
    if not (is_ref(from_ref) and is_ref(to_ref)):
        return None
    obligations: list[Obligation] = []
    raw_obligations = raw.get("obligations", ()) or ()
    if isinstance(raw_obligations, (list, tuple)) and not isinstance(raw_obligations, (str, bytes)):
        for value in raw_obligations:
            if not isinstance(value, Mapping):
                continue
            recipe_ref = value.get("recipe_ref")
            if not is_ref(recipe_ref):
                continue
            obligations.append(
                Obligation(
                    obligation_id=str(value.get("obligation_id", "")),
                    recipe_ref=str(recipe_ref),
                )
            )
    evidence_raw = raw.get("evidence_refs", ()) or ()
    evidence_refs = (
        tuple(str(value) for value in evidence_raw if is_ref(value))
        if isinstance(evidence_raw, (list, tuple)) and not isinstance(evidence_raw, (str, bytes))
        else ()
    )
    return SemanticEdge(
        ref=ref,
        from_ref=str(from_ref),
        to_ref=str(to_ref),
        tag=str(raw.get("tag", "")),
        obligations=tuple(obligations),
        evidence_refs=evidence_refs,
    )


def find_transfer_paths(
    edges: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    from_ref: str,
    to_ref: str,
    max_depth: int,
    require_validated: bool,
    evidence_lookup: EvidenceLookup,
) -> list[dict[str, Any]]:
    """Shell adapter that resolves evidence before invoking pure path search."""

    require(is_ref(from_ref) and is_ref(to_ref), "invalid from/to ref")
    require(1 <= max_depth <= 12, "max_depth out of bounds")

    parsed_edges: list[SemanticEdge] = []
    evidence_refs: set[str] = set()
    for ref, raw in edges:
        parsed = _parse_semantic_edge(ref, raw)
        if parsed is None:
            continue
        parsed_edges.append(parsed)
        evidence_refs.update(parsed.evidence_refs)

    evidence: list[EvidenceRecord] = []
    for ref in sorted(evidence_refs):
        raw = evidence_lookup(ref)
        if isinstance(raw, Mapping):
            parsed = _parse_evidence(ref, raw)
            if parsed is not None:
                evidence.append(parsed)

    paths = find_transfer_paths_core(
        TransferSnapshot(edges=tuple(parsed_edges), evidence=tuple(evidence)),
        from_ref=from_ref,
        to_ref=to_ref,
        max_depth=max_depth,
        require_validated=require_validated,
    )
    return [
        {
            "path": list(path.edge_refs),
            "obligations_open": [
                {
                    "edge_ref": obligation.edge_ref,
                    "obligation_id": obligation.obligation_id,
                    "recipe_ref": obligation.recipe_ref,
                }
                for obligation in path.obligations_open
            ],
        }
        for path in paths
    ]


def iter_objects_by_schema(
    records: Iterable[Mapping[str, Any]],
    object_lookup: Callable[[str], Mapping[str, Any] | None],
    schema: str,
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Yield ``(ref, object)`` for logical log records adding a schema."""

    for record in records:
        if record.get("op") != "add_object" or record.get("obj_schema") != schema:
            continue
        ref = record.get("obj_ref")
        if not is_ref(ref):
            continue
        obj = object_lookup(str(ref))
        if isinstance(obj, Mapping):
            yield str(ref), obj
