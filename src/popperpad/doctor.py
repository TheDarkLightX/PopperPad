from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .refs import is_ref
from .schemas import (
    SCHEMA_CONTEXT_V1,
    SCHEMA_DOMAIN_V1,
    SCHEMA_EDGE_V1,
    SCHEMA_EVIDENCE_V1,
    SCHEMA_HYPOTHESIS_V1,
    SCHEMA_RECIPE_V1,
)
from .validate import validate_object


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    issues: list[dict[str, Any]]
    stats: dict[str, Any]


@dataclass
class _LoadedObjects:
    objects: int = 0
    blobs: int = 0
    schema_by_ref: dict[str, str] = field(default_factory=dict)
    obj_by_ref: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    schema_counts: dict[str, int] = field(default_factory=dict)


class Doctor:
    """Consistency checks: hash chain + object validation + graph integrity."""

    def __init__(self, *, cas: Any, log: Any) -> None:
        self._cas = cas
        self._log = log

    def check(self, *, strict: bool = True) -> DoctorReport:
        issues: list[dict[str, Any]] = []
        self._verify_log(issues)
        loaded = self._load_objects(issues)
        self._check_references(issues, loaded)
        self._check_supersedes_cycles(issues, loaded.obj_by_ref)

        report = DoctorReport(
            ok=len(issues) == 0,
            issues=issues,
            stats={
                "objects": loaded.objects,
                "blobs": loaded.blobs,
                "schemas": dict(loaded.schema_counts),
                **self._log.stats(),
            },
        )
        if strict and not report.ok:
            import json
            raise ValueError(json.dumps(report.__dict__, sort_keys=True, indent=2))
        return report

    def _verify_log(self, issues: list[dict[str, Any]]) -> None:
        try:
            self._log.verify()
        except Exception as e:
            issues.append({"kind": "log", "error": f"{type(e).__name__}: {e}"})

    def _load_objects(self, issues: list[dict[str, Any]]) -> _LoadedObjects:
        loaded = _LoadedObjects()
        for i, record in enumerate(self._log.iter_records()):
            op = record.get("op")
            if op == "add_object":
                loaded.objects += 1
                self._load_one_object(i, record, loaded, issues)
            elif op == "add_blob":
                loaded.blobs += 1
                self._load_one_blob(i, record, issues)
        return loaded

    def _load_one_object(
        self, i: int, record: Mapping[str, Any], loaded: _LoadedObjects, issues: list[dict[str, Any]]
    ) -> None:
        obj_ref = record.get("obj_ref")
        if not is_ref(obj_ref):
            issues.append({"kind": "record", "line": i + 1, "error": "invalid obj_ref"})
            return
        try:
            obj = self._cas.get_json(str(obj_ref))
            validate_object(obj)
            if isinstance(obj, Mapping):
                schema = str(obj.get("schema", ""))
                loaded.schema_by_ref[str(obj_ref)] = schema
                loaded.obj_by_ref[str(obj_ref)] = obj
                loaded.schema_counts[schema] = loaded.schema_counts.get(schema, 0) + 1
        except Exception as e:
            issues.append({"kind": "object", "ref": str(obj_ref), "error": f"{type(e).__name__}: {e}"})

    def _load_one_blob(self, i: int, record: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
        blob_ref = record.get("blob_ref")
        if not is_ref(blob_ref):
            issues.append({"kind": "record", "line": i + 1, "error": "invalid blob_ref"})
            return
        media_type = record.get("media_type")
        if media_type is not None and not isinstance(media_type, str):
            issues.append({"kind": "record", "line": i + 1, "error": "invalid media_type"})
        try:
            self._cas.get_bytes(str(blob_ref))
        except Exception as e:
            issues.append({"kind": "blob", "ref": str(blob_ref), "error": f"{type(e).__name__}: {e}"})

    def _check_references(self, issues: list[dict[str, Any]], loaded: _LoadedObjects) -> None:
        for ref, obj in loaded.obj_by_ref.items():
            try:
                self._check_one_object_refs(ref, obj, loaded.schema_by_ref, issues)
            except Exception as e:
                issues.append({"kind": "doctor", "ref": ref, "error": f"{type(e).__name__}: {e}"})

    def _check_one_object_refs(
        self,
        ref: str,
        obj: Mapping[str, Any],
        schema_by_ref: dict[str, str],
        issues: list[dict[str, Any]],
    ) -> None:
        schema = str(obj.get("schema", ""))
        if schema == SCHEMA_EDGE_V1:
            self._check_edge_refs(ref, obj, schema_by_ref, issues)
        elif schema == SCHEMA_EVIDENCE_V1:
            self._check_evidence_refs(ref, obj, schema_by_ref, issues)
        elif schema == "popperpad/artifact/v1":
            self._require_blob_ref(obj.get("blob_ref"), where=f"artifact.blob_ref ({ref})", issues=issues)
        elif schema == SCHEMA_HYPOTHESIS_V1:
            self._check_hypothesis_refs(ref, obj, schema_by_ref, issues)
        elif schema == SCHEMA_CONTEXT_V1:
            self._check_context_refs(ref, obj, schema_by_ref, issues)
        elif schema == SCHEMA_RECIPE_V1:
            self._check_recipe_refs(ref, obj, issues)

    def _check_edge_refs(
        self, ref: str, obj: Mapping[str, Any], schema_by_ref: dict[str, str], issues: list[dict[str, Any]]
    ) -> None:
        edge_type = str(obj.get("edge_type", ""))
        self._require_obj_ref(obj.get("from_ref"), where=f"edge.from_ref ({ref})", schema_by_ref=schema_by_ref, issues=issues)
        self._require_obj_ref(obj.get("to_ref"), where=f"edge.to_ref ({ref})", schema_by_ref=schema_by_ref, issues=issues)
        if obj.get("context_ref") is not None:
            self._require_obj_ref(
                obj.get("context_ref"),
                where=f"edge.context_ref ({ref})",
                expected_schema=SCHEMA_CONTEXT_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )
        for i, evidence in enumerate(list(obj.get("evidence_refs", []) or [])):
            self._require_obj_ref(
                evidence,
                where=f"edge.evidence_refs[{i}] ({ref})",
                expected_schema=SCHEMA_EVIDENCE_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )
        if edge_type == "semantic":
            self._check_obligations(ref, obj, schema_by_ref, issues)

    def _check_obligations(
        self, ref: str, obj: Mapping[str, Any], schema_by_ref: dict[str, str], issues: list[dict[str, Any]]
    ) -> None:
        for i, obligation in enumerate(list(obj.get("obligations", []) or [])):
            if not isinstance(obligation, Mapping):
                issues.append({"kind": "edge", "where": f"edge.obligations[{i}] ({ref})", "error": "obligation must be an object"})
                continue
            self._require_obj_ref(
                obligation.get("recipe_ref"),
                where=f"edge.obligations[{i}].recipe_ref ({ref})",
                expected_schema=SCHEMA_RECIPE_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )

    def _check_evidence_refs(
        self, ref: str, obj: Mapping[str, Any], schema_by_ref: dict[str, str], issues: list[dict[str, Any]]
    ) -> None:
        self._require_obj_ref(
            obj.get("recipe_ref"),
            where=f"evidence.recipe_ref ({ref})",
            expected_schema=SCHEMA_RECIPE_V1,
            schema_by_ref=schema_by_ref,
            issues=issues,
        )
        if obj.get("context_ref") is not None:
            self._require_obj_ref(
                obj.get("context_ref"),
                where=f"evidence.context_ref ({ref})",
                expected_schema=SCHEMA_CONTEXT_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )
        for i, subject in enumerate(list(obj.get("subject_refs", []) or [])):
            self._require_obj_ref(subject, where=f"evidence.subject_refs[{i}] ({ref})", schema_by_ref=schema_by_ref, issues=issues)
        if obj.get("stdout_ref"):
            self._require_blob_ref(obj.get("stdout_ref"), where=f"evidence.stdout_ref ({ref})", issues=issues)
        if obj.get("stderr_ref"):
            self._require_blob_ref(obj.get("stderr_ref"), where=f"evidence.stderr_ref ({ref})", issues=issues)
        for i, out in enumerate(list(obj.get("outputs", []) or [])):
            if isinstance(out, Mapping):
                self._require_blob_ref(out.get("ref"), where=f"evidence.outputs[{i}].ref ({ref})", issues=issues)

    def _check_hypothesis_refs(
        self, ref: str, obj: Mapping[str, Any], schema_by_ref: dict[str, str], issues: list[dict[str, Any]]
    ) -> None:
        if obj.get("domain_ref") is not None:
            self._require_obj_ref(
                obj.get("domain_ref"),
                where=f"hypothesis.domain_ref ({ref})",
                expected_schema=SCHEMA_DOMAIN_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )
        if obj.get("context_ref") is not None:
            self._require_obj_ref(
                obj.get("context_ref"),
                where=f"hypothesis.context_ref ({ref})",
                expected_schema=SCHEMA_CONTEXT_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )
        for i, recipe in enumerate(list(obj.get("check_recipe_refs", []) or [])):
            self._require_obj_ref(
                recipe,
                where=f"hypothesis.check_recipe_refs[{i}] ({ref})",
                expected_schema=SCHEMA_RECIPE_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )

    def _check_context_refs(
        self, ref: str, obj: Mapping[str, Any], schema_by_ref: dict[str, str], issues: list[dict[str, Any]]
    ) -> None:
        if obj.get("domain_ref") is not None:
            self._require_obj_ref(
                obj.get("domain_ref"),
                where=f"context.domain_ref ({ref})",
                expected_schema=SCHEMA_DOMAIN_V1,
                schema_by_ref=schema_by_ref,
                issues=issues,
            )

    def _check_recipe_refs(self, ref: str, obj: Mapping[str, Any], issues: list[dict[str, Any]]) -> None:
        files = obj.get("files", {}) or {}
        if isinstance(files, Mapping):
            for name, spec in files.items():
                if isinstance(spec, Mapping) and "ref" in spec:
                    self._require_blob_ref(spec.get("ref"), where=f"recipe.files[{name!r}].ref ({ref})", issues=issues)
        stdin = obj.get("stdin")
        if isinstance(stdin, Mapping) and "ref" in stdin:
            self._require_blob_ref(stdin.get("ref"), where=f"recipe.stdin.ref ({ref})", issues=issues)

    def _require_obj_ref(
        self,
        ref: Any,
        *,
        where: str,
        issues: list[dict[str, Any]],
        schema_by_ref: dict[str, str],
        expected_schema: str | None = None,
    ) -> None:
        if not is_ref(ref):
            issues.append({"kind": "ref", "where": where, "error": "invalid sha256 ref", "ref": str(ref)})
            return
        r = str(ref)
        if r not in schema_by_ref:
            self._report_unlogged_object(r, where, issues)
            return
        if expected_schema is not None:
            got = schema_by_ref.get(r, "")
            if got != expected_schema:
                issues.append({
                    "kind": "ref",
                    "where": where,
                    "error": "schema mismatch",
                    "ref": r,
                    "expected": expected_schema,
                    "got": got,
                })

    def _report_unlogged_object(self, ref: str, where: str, issues: list[dict[str, Any]]) -> None:
        try:
            obj = self._cas.get_json(ref)
            if isinstance(obj, Mapping):
                validate_object(obj)
                issues.append({"kind": "ref", "where": where, "error": "ref exists in CAS but is not logged", "ref": ref})
            else:
                issues.append({"kind": "ref", "where": where, "error": "ref exists in CAS but is not an object", "ref": ref})
        except Exception:
            issues.append({"kind": "ref", "where": where, "error": "missing object ref", "ref": ref})

    def _require_blob_ref(self, ref: Any, *, where: str, issues: list[dict[str, Any]]) -> None:
        if not is_ref(ref):
            issues.append({"kind": "blob_ref", "where": where, "error": "invalid sha256 ref", "ref": str(ref)})
            return
        try:
            self._cas.get_bytes(str(ref))
        except Exception as e:
            issues.append({"kind": "blob_ref", "where": where, "error": f"{type(e).__name__}: {e}", "ref": str(ref)})

    def _check_supersedes_cycles(self, issues: list[dict[str, Any]], obj_by_ref: dict[str, Mapping[str, Any]]) -> None:
        graph = self._supersedes_graph(obj_by_ref)
        cycle = _find_cycle(graph)
        if cycle is not None:
            issues.append({"kind": "supersedes_cycle", "cycle": cycle})

    def _supersedes_graph(self, obj_by_ref: dict[str, Mapping[str, Any]]) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for ref, edge in obj_by_ref.items():
            if str(edge.get("schema", "")) != SCHEMA_EDGE_V1:
                continue
            if str(edge.get("edge_type", "")) != "supersedes":
                continue
            a, b = edge.get("from_ref"), edge.get("to_ref")
            if is_ref(a) and is_ref(b):
                graph.setdefault(str(a), []).append(str(b))
        return graph


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    visited: set[str] = set()
    on_stack: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        on_stack.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt in on_stack:
                return _extract_cycle(stack, nxt)
            if nxt not in visited:
                found = dfs(nxt)
                if found is not None:
                    return found
        stack.pop()
        on_stack.remove(node)
        return None

    for start in list(graph.keys()):
        if start in visited:
            continue
        cycle = dfs(start)
        if cycle is not None:
            return cycle
    return None


def _extract_cycle(stack: list[str], target: str) -> list[str]:
    if target in stack:
        j = stack.index(target)
        return stack[j:] + [target]
    return [target, target]
