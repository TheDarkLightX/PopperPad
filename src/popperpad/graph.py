from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .refs import ClaimState, Ref, ValidationError, is_ref, require
from .schemas import SCHEMA_EDGE_V1, SCHEMA_EVIDENCE_V1


EvidenceLookup = Callable[[str], Mapping[str, Any] | None]


@dataclass(frozen=True)
class StatusResult:
    state: str  # unknown|supported|falsified|disputed
    supports: list[str]
    refutes: list[str]


def _edge_targets(edge: Mapping[str, Any], hyp_ref: str, context_ref: str | None) -> bool:
    if str(edge.get("to_ref")) != hyp_ref:
        return False
    if context_ref is not None and str(edge.get("context_ref")) != context_ref:
        return False
    return True


def compute_status(
    edges: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    hyp_ref: str,
    context_ref: str | None,
) -> StatusResult:
    """Derive claim status from supports/refutes edges (pure over loaded edges)."""
    require(is_ref(hyp_ref), "invalid hypothesis ref")
    if context_ref is not None:
        require(is_ref(context_ref), "invalid context ref")

    supports: list[str] = []
    refutes: list[str] = []
    for ref, edge in edges:
        if not _edge_targets(edge, hyp_ref, context_ref):
            continue
        edge_type = str(edge.get("edge_type"))
        if edge_type == "supports":
            supports.append(ref)
        elif edge_type == "refutes":
            refutes.append(ref)

    return StatusResult(
        state=_classify(supports, refutes),
        supports=sorted(supports),
        refutes=sorted(refutes),
    )


def _classify(supports: list[str], refutes: list[str]) -> str:
    if supports and refutes:
        return ClaimState.DISPUTED.value
    if refutes:
        return ClaimState.FALSIFIED.value
    if supports:
        return ClaimState.SUPPORTED.value
    return ClaimState.UNKNOWN.value


@dataclass(frozen=True)
class SemanticEdge:
    ref: str
    from_ref: str
    to_ref: str
    tag: str
    raw: Mapping[str, Any]


def _semantic_edges(edges: Iterable[tuple[str, Mapping[str, Any]]]) -> list[SemanticEdge]:
    out: list[SemanticEdge] = []
    for ref, edge in edges:
        if str(edge.get("edge_type")) != "semantic":
            continue
        a, b = str(edge.get("from_ref")), str(edge.get("to_ref"))
        if not (is_ref(a) and is_ref(b)):
            continue
        out.append(SemanticEdge(ref=ref, from_ref=a, to_ref=b, tag=str(edge.get("tag")), raw=edge))
    return out


def _build_adjacency(sem: list[SemanticEdge]) -> dict[str, list[tuple[str, str]]]:
    adj: dict[str, list[tuple[str, str]]] = {}
    for edge in sem:
        adj.setdefault(edge.from_ref, []).append((edge.ref, edge.to_ref))
        if edge.tag == "≅":
            adj.setdefault(edge.to_ref, []).append((edge.ref, edge.from_ref))
    return adj


def _edge_obligations_open(edge: Mapping[str, Any], evidence_lookup: EvidenceLookup) -> list[dict[str, Any]]:
    obligations = list(edge.get("obligations", []) or [])
    if not obligations:
        return []
    evidence_refs = list(edge.get("evidence_refs", []) or [])
    open_obligations: list[dict[str, Any]] = []
    for obligation in obligations:
        if _obligation_satisfied(obligation, evidence_refs, evidence_lookup):
            continue
        open_obligations.append({
            "obligation_id": str(obligation.get("obligation_id", "")),
            "recipe_ref": str(obligation.get("recipe_ref", "")),
        })
    return open_obligations


def _obligation_satisfied(
    obligation: Mapping[str, Any], evidence_refs: list[str], evidence_lookup: EvidenceLookup
) -> bool:
    recipe_ref = str(obligation.get("recipe_ref", ""))
    for evidence_ref in evidence_refs:
        if not is_ref(evidence_ref):
            continue
        evidence = evidence_lookup(str(evidence_ref))
        if evidence is None:
            continue
        if str(evidence.get("recipe_ref")) != recipe_ref:
            continue
        result = evidence.get("result") or {}
        if isinstance(result, Mapping) and str(result.get("status")) == "pass":
            return True
    return False


def find_transfer_paths(
    edges: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    from_ref: str,
    to_ref: str,
    max_depth: int,
    require_validated: bool,
    evidence_lookup: EvidenceLookup,
) -> list[dict[str, Any]]:
    """BFS over semantic edges between two refs (pure over loaded edges)."""
    require(is_ref(from_ref) and is_ref(to_ref), "invalid from/to ref")
    require(1 <= max_depth <= 12, "max_depth out of bounds")

    sem = _semantic_edges(edges)
    adj = _build_adjacency(sem)
    edge_by_ref = {edge.ref: edge.raw for edge in sem}

    def edge_ok(edge_ref: str) -> tuple[bool, list[dict[str, Any]]]:
        open_obligations = _edge_obligations_open(edge_by_ref.get(edge_ref, {}), evidence_lookup)
        return len(open_obligations) == 0, open_obligations

    paths = _bfs_paths(adj, from_ref, to_ref, max_depth, require_validated, edge_ok)

    out: list[dict[str, Any]] = []
    for path in paths:
        open_all: list[dict[str, Any]] = []
        for edge_ref in path:
            _ok, open_obligations = edge_ok(edge_ref)
            for ob in open_obligations:
                open_all.append({"edge_ref": edge_ref, **ob})
        out.append({"path": path, "obligations_open": open_all})
    return out


def _bfs_paths(
    adj: dict[str, list[tuple[str, str]]],
    from_ref: str,
    to_ref: str,
    max_depth: int,
    require_validated: bool,
    edge_ok: Callable[[str], tuple[bool, list[dict[str, Any]]]],
) -> list[list[str]]:
    paths: list[list[str]] = []
    queue: list[tuple[str, list[str]]] = [(from_ref, [])]
    seen: set[tuple[str, tuple[str, ...]]] = set()
    while queue:
        node, path = queue.pop(0)
        if len(path) > max_depth:
            continue
        if node == to_ref:
            paths.append(path)
            continue
        for edge_ref, nxt in adj.get(node, []):
            new_path = path + [edge_ref]
            key = (nxt, tuple(new_path))
            if key in seen:
                continue
            seen.add(key)
            if require_validated:
                ok, _ = edge_ok(edge_ref)
                if not ok:
                    continue
            queue.append((nxt, new_path))
    return paths


def iter_objects_by_schema(
    records: Iterable[Mapping[str, Any]],
    object_lookup: Callable[[str], Mapping[str, Any] | None],
    schema: str,
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Yield ``(ref, object)`` for log records adding objects of ``schema``."""
    for record in records:
        if record.get("op") != "add_object":
            continue
        if record.get("obj_schema") != schema:
            continue
        ref = record.get("obj_ref")
        if not is_ref(ref):
            continue
        obj = object_lookup(str(ref))
        if isinstance(obj, Mapping):
            yield str(ref), obj
