from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cas import ContentAddressedStore
from .log import AppendOnlyLog, utc_now_iso
from .runner import run_recipe
from .schemas import (
    SCHEMA_ARTIFACT_V1,
    SCHEMA_CHECKPOINT_V1,
    SCHEMA_EDGE_V1,
    SCHEMA_EVIDENCE_V1,
    SCHEMA_HYPOTHESIS_V1,
    SCHEMA_RECIPE_V1,
)
from .validate import validate_object


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    raise ValueError(msg)


def _is_ref(x: Any) -> bool:
    return isinstance(x, str) and bool(_REF_RE.match(x))


@dataclass(frozen=True)
class AddResult:
    obj_ref: str
    record_hash: str


@dataclass(frozen=True)
class RunResult:
    ok: bool
    verdict: str  # PASS|FAIL|INCONCLUSIVE
    evidence_refs: list[str]
    edge_refs: list[str]


@dataclass(frozen=True)
class StatusResult:
    state: str  # unknown|supported|falsified|disputed
    supports: list[str]
    refutes: list[str]


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    issues: list[dict[str, Any]]
    stats: dict[str, Any]


class PopperPad:
    """
    Standalone PopperPad library:
    - CAS objects (sha256 of canonical bytes)
    - append-only log (hash-chained)
    - derived semantic graph (computed)
    """

    def __init__(self, *, root: Path):
        self.root = Path(root).resolve()
        self.cas = ContentAddressedStore(root=self.root / "cas")
        self.log = AppendOnlyLog(path=self.root / "log.jsonl")

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.log.init()

    def put_object(self, obj: Mapping[str, Any]) -> AddResult:
        validate_object(obj)
        put = self.cas.put_json(dict(obj))
        record_hash = self.log.append(
            {
                "schema": "popperpad/log_record/v1",
                "op": "add_object",
                "created_at": utc_now_iso(),
                "obj_ref": put.ref,
                "obj_schema": str(obj.get("schema")),
            }
        ).record_hash
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
        _require(_is_ref(ref), "invalid ref")
        return self.cas.get_json(ref)

    def get_blob(self, ref: str) -> bytes:
        _require(_is_ref(ref), "invalid ref")
        return self.cas.get_bytes(ref)

    def _iter_objects_by_schema(self, schema: str) -> Iterable[tuple[str, Mapping[str, Any]]]:
        for rec in self.log.iter_records():
            if rec.get("op") != "add_object":
                continue
            if rec.get("obj_schema") != schema:
                continue
            r = rec.get("obj_ref")
            if not _is_ref(r):
                continue
            obj = self.cas.get_json(r)
            if not isinstance(obj, Mapping):
                continue
            yield str(r), obj

    def run_hypothesis(self, hyp_ref: str, *, context_ref: str | None, mode: str) -> RunResult:
        """
        mode:
          - "prove": run recipes with verdict_on_pass == "support"
          - "refute": run recipes with verdict_on_pass == "refute"
        """
        _require(mode in {"prove", "refute"}, "invalid mode")
        hyp = self.get_object(hyp_ref)
        _require(isinstance(hyp, Mapping) and hyp.get("schema") == SCHEMA_HYPOTHESIS_V1, "ref is not a hypothesis")
        if context_ref is not None:
            _require(_is_ref(context_ref), "invalid context ref")

        recipe_refs = list(hyp.get("check_recipe_refs", []) or [])
        _require(recipe_refs, "hypothesis has no check recipes")

        evidence_refs: list[str] = []
        edge_refs: list[str] = []
        any_skip = False
        any_fail = False
        any_pass = False

        for rref in recipe_refs:
            if not _is_ref(rref):
                continue
            recipe = self.get_object(str(rref))
            if not (isinstance(recipe, Mapping) and recipe.get("schema") == SCHEMA_RECIPE_V1):
                continue
            verdict_on_pass = str(recipe.get("verdict_on_pass", "support"))
            if mode == "prove" and verdict_on_pass != "support":
                continue
            if mode == "refute" and verdict_on_pass != "refute":
                continue

            res = run_recipe(cas=self.cas, recipe=recipe, bindings={}, repo_root=None)
            if res.status == "SKIP":
                any_skip = True
            elif res.status == "FAIL":
                any_fail = True
            elif res.status == "PASS":
                any_pass = True

            ev_obj: dict[str, Any] = {
                "schema": SCHEMA_EVIDENCE_V1,
                "evidence_kind": "check",
                "created_at": utc_now_iso(),
                "recipe_ref": str(rref),
                "context_ref": context_ref,
                "subject_refs": [hyp_ref],
                "result": {"status": res.status.lower(), "exit_code": res.exit_code},
                "reason": res.reason,
                "stdout_ref": res.stdout_ref,
                "stderr_ref": res.stderr_ref,
                "outputs": [{"name": o["name"], "ref": o["ref"]} for o in res.outputs],
            }
            ev_ref = self.put_object(ev_obj).obj_ref
            evidence_refs.append(ev_ref)

            if res.status == "PASS":
                if mode == "prove":
                    edge = {
                        "schema": SCHEMA_EDGE_V1,
                        "edge_type": "supports",
                        "from_ref": ev_ref,
                        "to_ref": hyp_ref,
                        "context_ref": context_ref,
                        "evidence_refs": [ev_ref],
                    }
                    edge_ref = self.put_object(edge).obj_ref
                    edge_refs.append(edge_ref)
                if mode == "refute":
                    # Prefer a captured artifact as the counterexample node when available.
                    ce_ref = ev_ref
                    if res.outputs:
                        out0 = res.outputs[0]
                        art = {
                            "schema": SCHEMA_ARTIFACT_V1,
                            "name": str(out0["name"]),
                            "kind": "counterexample",
                            "media_type": "application/octet-stream",
                            "blob_ref": str(out0["ref"]),
                        }
                        ce_ref = self.put_object(art).obj_ref
                    edge = {
                        "schema": SCHEMA_EDGE_V1,
                        "edge_type": "refutes",
                        "from_ref": ce_ref,
                        "to_ref": hyp_ref,
                        "context_ref": context_ref,
                        "evidence_refs": [ev_ref],
                    }
                    edge_ref = self.put_object(edge).obj_ref
                    edge_refs.append(edge_ref)

        if not evidence_refs:
            return RunResult(ok=False, verdict="INCONCLUSIVE", evidence_refs=[], edge_refs=[])

        verdict = "INCONCLUSIVE"
        ok = False
        if any_skip:
            verdict = "INCONCLUSIVE"
        elif mode == "prove":
            verdict = "PASS" if (any_pass and not any_fail) else "FAIL"
        else:
            # refute: PASS means at least one refuter recipe succeeded
            verdict = "PASS" if any_pass else "FAIL"
        ok = verdict == "PASS"
        return RunResult(ok=ok, verdict=verdict, evidence_refs=evidence_refs, edge_refs=edge_refs)

    def status(self, hyp_ref: str, *, context_ref: str | None) -> StatusResult:
        _require(_is_ref(hyp_ref), "invalid hypothesis ref")
        if context_ref is not None:
            _require(_is_ref(context_ref), "invalid context ref")

        supports: list[str] = []
        refutes: list[str] = []
        for ref, edge in self._iter_objects_by_schema(SCHEMA_EDGE_V1):
            if str(edge.get("to_ref")) != hyp_ref:
                continue
            if context_ref is not None and str(edge.get("context_ref")) != context_ref:
                continue
            et = str(edge.get("edge_type"))
            if et == "supports":
                supports.append(ref)
            if et == "refutes":
                refutes.append(ref)

        state = "unknown"
        if supports and refutes:
            state = "disputed"
        elif refutes:
            state = "falsified"
        elif supports:
            state = "supported"
        return StatusResult(state=state, supports=sorted(supports), refutes=sorted(refutes))

    def transfer_paths(
        self,
        *,
        from_ref: str,
        to_ref: str,
        max_depth: int = 4,
        require_validated: bool = False,
    ) -> list[dict[str, Any]]:
        _require(_is_ref(from_ref) and _is_ref(to_ref), "invalid from/to ref")
        max_depth = int(max_depth)
        _require(1 <= max_depth <= 12, "max_depth out of bounds")

        edges: list[tuple[str, Mapping[str, Any]]] = list(self._iter_objects_by_schema(SCHEMA_EDGE_V1))
        sem: list[tuple[str, Mapping[str, Any]]] = [(r, e) for (r, e) in edges if e.get("edge_type") == "semantic"]

        adj: dict[str, list[tuple[str, str]]] = {}
        edge_by_ref: dict[str, Mapping[str, Any]] = {r: e for r, e in sem}

        for eref, e in sem:
            a = str(e.get("from_ref"))
            b = str(e.get("to_ref"))
            tag = str(e.get("tag"))
            if not (_is_ref(a) and _is_ref(b)):
                continue
            adj.setdefault(a, []).append((eref, b))
            if tag == "≅":
                adj.setdefault(b, []).append((eref, a))

        def edge_ok(eref: str) -> tuple[bool, list[dict[str, Any]]]:
            e = edge_by_ref.get(eref, {})
            obs = list(e.get("obligations", []) or [])
            ev_refs = list(e.get("evidence_refs", []) or [])
            open_: list[dict[str, Any]] = []
            # Trivially validated if no obligations.
            if not obs:
                return True, []
            # Load evidence once.
            evs: list[Mapping[str, Any]] = []
            for r in ev_refs:
                if not _is_ref(r):
                    continue
                ev = self.get_object(str(r))
                if isinstance(ev, Mapping) and ev.get("schema") == SCHEMA_EVIDENCE_V1:
                    evs.append(ev)
            for ob in obs:
                rid = str(ob.get("recipe_ref", ""))
                ok = False
                for ev in evs:
                    if str(ev.get("recipe_ref")) != rid:
                        continue
                    res = ev.get("result") or {}
                    if isinstance(res, Mapping) and str(res.get("status")) == "pass":
                        ok = True
                        break
                if not ok:
                    open_.append({"obligation_id": str(ob.get("obligation_id", "")), "recipe_ref": rid})
            return len(open_) == 0, open_

        # BFS paths, keeping edge sequence.
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
            for eref, nxt in adj.get(node, []):
                new_path = path + [eref]
                key = (nxt, tuple(new_path))
                if key in seen:
                    continue
                seen.add(key)
                if require_validated:
                    ok, _open = edge_ok(eref)
                    if not ok:
                        continue
                queue.append((nxt, new_path))

        out: list[dict[str, Any]] = []
        for p in paths:
            open_all: list[dict[str, Any]] = []
            for eref in p:
                _ok, open_ = edge_ok(eref)
                for ob in open_:
                    open_all.append({"edge_ref": eref, **ob})
            out.append({"path": p, "obligations_open": open_all})
        return out

    def checkpoint(self) -> AddResult:
        st = self.log.stats()
        obj = {
            "schema": SCHEMA_CHECKPOINT_V1,
            "created_at": utc_now_iso(),
            "log_head": st.get("head", ""),
            "event_count": int(st.get("event_count", 0)),
        }
        return self.put_object(obj)

    def doctor(self, *, strict: bool = True) -> DoctorReport:
        issues: list[dict[str, Any]] = []
        try:
            self.log.verify()
        except Exception as e:
            issues.append({"kind": "log", "error": f"{type(e).__name__}: {e}"})

        # Validate that every add_object/add_blob record references valid CAS content.
        objects = 0
        blobs = 0
        for i, rec in enumerate(self.log.iter_records()):
            op = rec.get("op")
            if op == "add_object":
                objects += 1
                obj_ref = rec.get("obj_ref")
                if not _is_ref(obj_ref):
                    issues.append({"kind": "record", "line": i + 1, "error": "invalid obj_ref"})
                    continue
                try:
                    obj = self.cas.get_json(str(obj_ref))
                    validate_object(obj)
                except Exception as e:
                    issues.append({"kind": "object", "ref": str(obj_ref), "error": f"{type(e).__name__}: {e}"})
            elif op == "add_blob":
                blobs += 1
                blob_ref = rec.get("blob_ref")
                if not _is_ref(blob_ref):
                    issues.append({"kind": "record", "line": i + 1, "error": "invalid blob_ref"})
                    continue
                media_type = rec.get("media_type")
                if media_type is not None and not isinstance(media_type, str):
                    issues.append({"kind": "record", "line": i + 1, "error": "invalid media_type"})
                try:
                    self.cas.get_bytes(str(blob_ref))
                except Exception as e:
                    issues.append({"kind": "blob", "ref": str(blob_ref), "error": f"{type(e).__name__}: {e}"})

        rep = DoctorReport(
            ok=len(issues) == 0,
            issues=issues,
            stats={"objects": objects, "blobs": blobs, **self.log.stats()},
        )
        if strict and not rep.ok:
            raise ValueError(json.dumps(rep.__dict__, sort_keys=True, indent=2))
        return rep
