from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cas import ContentAddressedStore
from .doctor import Doctor, DoctorReport
from .engine import CheckEngine, RunResult
from .graph import StatusResult, compute_status, find_transfer_paths, iter_objects_by_schema
from .index import PadIndex
from .log import AppendOnlyLog, utc_now_iso
from .refs import is_ref, require
from .schemas import SCHEMA_CHECKPOINT_V1, SCHEMA_HYPOTHESIS_V1
from .validate import validate_object


@dataclass(frozen=True)
class AddResult:
    obj_ref: str
    record_hash: str


class PopperPad:
    """Standalone PopperPad library facade.

    Composes a content-addressed store, an append-only hash-chained log, a
    derived semantic graph, and an incremental index. Cohesive behaviour lives
    in :mod:`engine`, :mod:`graph`, :mod:`doctor`, and :mod:`index`; this class
    wires them together and exposes the public pad API.
    """

    def __init__(self, *, root: Path):
        self.root = Path(root).resolve()
        self.cas = ContentAddressedStore(root=self.root / "cas")
        self.log = AppendOnlyLog(path=self.root / "log.jsonl")
        self._engine = CheckEngine(self)
        self._doctor = Doctor(cas=self.cas, log=self.log)
        self._index = PadIndex()
        self._index_built = False

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.log.init()

    def _ensure_index(self) -> None:
        if not self._index_built:
            self._index.rebuild_from_log(self.log.iter_records())
            self._index_built = True

    def put_object(self, obj: Mapping[str, Any]) -> AddResult:
        validate_object(obj)
        put = self.cas.put_json(dict(obj))
        record = {
            "schema": "popperpad/log_record/v1",
            "op": "add_object",
            "created_at": utc_now_iso(),
            "obj_ref": put.ref,
            "obj_schema": str(obj.get("schema")),
        }
        record_hash = self.log.append(record).record_hash
        if self._index_built:
            self._index.on_record(record)
        return AddResult(obj_ref=put.ref, record_hash=record_hash)

    def put_blob(self, data: bytes, *, media_type: str = "application/octet-stream") -> AddResult:
        put = self.cas.put_bytes(bytes(data))
        record_hash = self.log.append(
            {
                "schema": "popperpad/log_record/v1",
                "op": "add_blob",
                "created_at": utc_now_iso(),
                "blob_ref": put.ref,
                "media_type": str(media_type),
            }
        ).record_hash
        return AddResult(obj_ref=put.ref, record_hash=record_hash)

    def get_object(self, ref: str) -> Any:
        require(is_ref(ref), "invalid ref")
        return self.cas.get_json(ref)

    def get_blob(self, ref: str) -> bytes:
        require(is_ref(ref), "invalid ref")
        return self.cas.get_bytes(ref)

    def _iter_objects_by_schema(self, schema: str) -> Iterable[tuple[str, Mapping[str, Any]]]:
        return iter_objects_by_schema(self.log.iter_records(), self.get_object, schema)

    def run_hypothesis(self, hyp_ref: str, *, context_ref: str | None, mode: str) -> RunResult:
        return self._engine.run_hypothesis(hyp_ref, context_ref=context_ref, mode=mode)

    def status(self, hyp_ref: str, *, context_ref: str | None) -> StatusResult:
        hypothesis = self.get_object(hyp_ref)
        require(
            isinstance(hypothesis, Mapping) and hypothesis.get("schema") == SCHEMA_HYPOTHESIS_V1,
            "ref is not a hypothesis",
        )
        accepted_recipe_refs = frozenset(
            str(ref) for ref in hypothesis.get("check_recipe_refs", []) if is_ref(ref)
        )
        self._ensure_index()
        edge_refs = self._index.edges_by_target(hyp_ref, object_lookup=self.get_object)
        edges = [(ref, self.get_object(ref)) for ref in edge_refs]
        objects = self._load_status_objects(edges)
        return compute_status(
            edges,
            hyp_ref=hyp_ref,
            context_ref=context_ref,
            objects=objects,
            accepted_recipe_refs=accepted_recipe_refs,
        )

    def _load_status_objects(
        self, edges: Iterable[tuple[str, Mapping[str, Any]]]
    ) -> dict[str, Mapping[str, Any]]:
        """Load the evidence and recipe view consumed by the pure status core.

        Missing, malformed, or unreadable references are omitted so status
        derivation fails closed instead of treating an assertion as evidence.
        """
        objects: dict[str, Mapping[str, Any]] = {}
        for _edge_ref, edge in edges:
            evidence_refs = edge.get("evidence_refs", [])
            if not isinstance(evidence_refs, (list, tuple)) or isinstance(evidence_refs, (str, bytes)):
                continue
            for raw_evidence_ref in evidence_refs:
                if not is_ref(raw_evidence_ref):
                    continue
                evidence_ref = str(raw_evidence_ref)
                try:
                    evidence = self.get_object(evidence_ref)
                except Exception:
                    continue
                if not isinstance(evidence, Mapping):
                    continue
                objects[evidence_ref] = evidence

                recipe_ref = evidence.get("recipe_ref")
                if not is_ref(recipe_ref):
                    continue
                recipe_key = str(recipe_ref)
                if recipe_key in objects:
                    continue
                try:
                    recipe = self.get_object(recipe_key)
                except Exception:
                    continue
                if isinstance(recipe, Mapping):
                    objects[recipe_key] = recipe
        return objects

    def transfer_paths(
        self,
        *,
        from_ref: str,
        to_ref: str,
        max_depth: int = 4,
        require_validated: bool = False,
    ) -> list[dict[str, Any]]:
        self._ensure_index()
        adj = self._index.semantic_adjacency(object_lookup=self.get_object)
        edge_refs = set()
        for refs in adj.values():
            edge_refs.update(ref for ref, _ in refs)
        edges = [(ref, self.get_object(ref)) for ref in edge_refs]
        return find_transfer_paths(
            edges,
            from_ref=from_ref,
            to_ref=to_ref,
            max_depth=int(max_depth),
            require_validated=require_validated,
            evidence_lookup=self.get_object,
        )

    def checkpoint(self) -> AddResult:
        stats = self.log.stats()
        obj = {
            "schema": SCHEMA_CHECKPOINT_V1,
            "created_at": utc_now_iso(),
            "log_head": stats.get("head", ""),
            "event_count": int(stats.get("event_count", 0)),
        }
        return self.put_object(obj)

    def doctor(self, *, strict: bool = True) -> DoctorReport:
        return self._doctor.check(strict=strict)
