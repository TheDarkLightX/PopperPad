from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from .refs import is_ref


ObjectLookup = Callable[[str], Mapping[str, Any] | None]


class PadIndex:
    """Incremental derived index over the append-only log.

    Maintains a schema→refs multimap and an edge target index so graph queries
    (status, transfer-paths) are O(k) in the result size, not O(n) in the full
    log. The index is a pure projection: ``rebuild_from_log`` produces identical
    state to incremental ``on_record`` calls.

    Edge target indexing requires an object lookup because log records only
    store ``obj_ref`` and ``obj_schema``, not the edge's ``to_ref``. The lookup
    is called once per edge during indexing, then results are cached.
    """

    def __init__(self) -> None:
        self._schema_to_refs: dict[str, set[str]] = {}
        self._edge_refs: set[str] = set()
        self._edge_targets: dict[str, set[str]] | None = None
        self._semantic_adj: dict[str, list[tuple[str, str]]] | None = None

    def on_record(self, record: Mapping[str, Any]) -> None:
        if record.get("op") != "add_object":
            return
        ref = record.get("obj_ref")
        schema = record.get("obj_schema", "")
        if not is_ref(ref):
            return
        r = str(ref)
        self._schema_to_refs.setdefault(str(schema), set()).add(r)
        if schema == "popperpad/edge/v1":
            authority_scope = record.get("authority_scope")
            if authority_scope != "import_quarantined":
                self._edge_refs.add(r)
            self._edge_targets = None
            self._semantic_adj = None

    def rebuild_from_log(self, records: Iterable[Mapping[str, Any]]) -> None:
        self._schema_to_refs.clear()
        self._edge_refs.clear()
        self._edge_targets = None
        self._semantic_adj = None
        for record in records:
            self.on_record(record)

    def refs_by_schema(self, schema: str) -> set[str]:
        return set(self._schema_to_refs.get(schema, set()))

    def edges_by_target(self, target_ref: str, *, object_lookup: ObjectLookup) -> set[str]:
        if self._edge_targets is None:
            self._edge_targets = self._build_edge_targets(object_lookup)
        return set(self._edge_targets.get(target_ref, set()))

    def semantic_adjacency(self, *, object_lookup: ObjectLookup) -> dict[str, list[tuple[str, str]]]:
        if self._semantic_adj is None:
            self._semantic_adj = self._build_semantic_adjacency(object_lookup)
        return self._semantic_adj

    def _build_edge_targets(self, object_lookup: ObjectLookup) -> dict[str, set[str]]:
        targets: dict[str, set[str]] = {}
        for edge_ref in self._edge_refs:
            edge = object_lookup(edge_ref)
            if edge is None:
                continue
            to_ref = edge.get("to_ref")
            if is_ref(to_ref):
                targets.setdefault(str(to_ref), set()).add(edge_ref)
        return targets

    def _build_semantic_adjacency(self, object_lookup: ObjectLookup) -> dict[str, list[tuple[str, str]]]:
        adj: dict[str, list[tuple[str, str]]] = {}
        for edge_ref in self._edge_refs:
            edge = object_lookup(edge_ref)
            if edge is None:
                continue
            if str(edge.get("edge_type", "")) != "semantic":
                continue
            a, b = str(edge.get("from_ref", "")), str(edge.get("to_ref", ""))
            if not (is_ref(a) and is_ref(b)):
                continue
            adj.setdefault(a, []).append((edge_ref, b))
            if str(edge.get("tag", "")) == "≅":
                adj.setdefault(b, []).append((edge_ref, a))
        return adj
