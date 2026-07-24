from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cas import ContentAddressedStore
from .core.commit import CommitBundle, plan_commit
from .core.result import Reject
from .core.values import thaw_json
from .doctor import Doctor, DoctorReport
from .engine import CheckEngine, RunResult
from .graph import StatusResult, compute_status, find_transfer_paths, iter_objects_by_schema
from .index import PadIndex
from .log import AppendOnlyLog, utc_now_iso
from .refs import ValidationError, is_ref, require
from .schemas import SCHEMA_CHECKPOINT_V1, SCHEMA_HYPOTHESIS_V1
from .validate import validate_object


@dataclass(frozen=True, slots=True)
class AddResult:
    obj_ref: str
    record_hash: str


@dataclass(frozen=True, slots=True)
class CommitResult:
    commit_root: str
    record_hash: str
    object_refs: tuple[str, ...]
    blob_refs: tuple[str, ...]
    effect_ids: tuple[str, ...]


class PopperPad:
    """Standalone PopperPad imperative shell.

    Pure modules construct immutable values, decisions, and commit plans. This
    facade owns filesystem/CAS/log authority and interprets only those plans.
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

    def commit_values(
        self,
        *,
        objects: tuple[Mapping[str, Any], ...] = (),
        blobs: tuple[tuple[bytes, str], ...] = (),
        outbox: tuple[tuple[str, Mapping[str, Any]], ...] = (),
        evidence_root: str = "",
        created_at: str | None = None,
        policy_version: str = "popperpad-policy/v1",
        core_version: str = "popperpad-core/v1",
    ) -> CommitResult:
        """Validate, plan, and atomically authorize one immutable commit bundle.

        Content-addressed bytes are written before the compare-and-swap record.
        A crash or conflict can therefore leave unreferenced CAS bytes, but it
        cannot expose a partial authoritative state: the v2 log record is the
        single publication point.
        """

        owned_objects = tuple(dict(obj) for obj in objects)
        for obj in owned_objects:
            validate_object(obj)

        expected_head = self.log.head()
        planned = plan_commit(
            expected_head=expected_head,
            created_at=created_at or utc_now_iso(),
            objects=owned_objects,
            blobs=tuple((bytes(payload), str(media_type)) for payload, media_type in blobs),
            outbox=tuple((str(kind), dict(payload)) for kind, payload in outbox),
            evidence_root=evidence_root,
            policy_version=policy_version,
            core_version=core_version,
        )
        if isinstance(planned, Reject):
            details = thaw_json(planned.details)
            raise ValidationError(f"{planned.code}: {details}")

        self._stage_commit_payloads(planned)
        record = thaw_json(planned.record)
        require(isinstance(record, Mapping), "planned commit record must be an object")
        append = self.log.append_prepared(record, expected_head=expected_head)

        if self._index_built:
            for logical_record in planned.logical_records():
                plain = thaw_json(logical_record)
                if isinstance(plain, Mapping):
                    self._index.on_record(plain)

        return CommitResult(
            commit_root=planned.commit_root,
            record_hash=append.record_hash,
            object_refs=tuple(item.ref for item in planned.objects),
            blob_refs=tuple(item.ref for item in planned.blobs),
            effect_ids=tuple(effect.effect_id for effect in planned.outbox),
        )

    def _stage_commit_payloads(self, planned: CommitBundle) -> None:
        for item in planned.objects:
            stored = self.cas.put_bytes(item.payload)
            require(stored.ref == item.ref, "planned object ref differs from staged CAS ref")
        for item in planned.blobs:
            stored = self.cas.put_bytes(item.payload)
            require(stored.ref == item.ref, "planned blob ref differs from staged CAS ref")

    def put_object(self, obj: Mapping[str, Any]) -> AddResult:
        committed = self.commit_values(objects=(obj,))
        return AddResult(obj_ref=committed.object_refs[0], record_hash=committed.record_hash)

    def put_blob(self, data: bytes, *, media_type: str = "application/octet-stream") -> AddResult:
        committed = self.commit_values(blobs=((bytes(data), str(media_type)),))
        return AddResult(obj_ref=committed.blob_refs[0], record_hash=committed.record_hash)

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
        """Load the immutable evidence/recipe view consumed by the pure status core."""

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
        adjacency = self._index.semantic_adjacency(object_lookup=self.get_object)
        edge_refs: set[str] = set()
        for refs in adjacency.values():
            edge_refs.update(ref for ref, _target in refs)
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
