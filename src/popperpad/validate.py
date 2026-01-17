from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .schemas import (
    SCHEMA_ARTIFACT_V1,
    SCHEMA_CHECKPOINT_V1,
    SCHEMA_CONTEXT_V1,
    SCHEMA_DOMAIN_V1,
    SCHEMA_EDGE_V1,
    SCHEMA_EVIDENCE_V1,
    SCHEMA_HYPOTHESIS_V1,
    SCHEMA_RECIPE_V1,
)


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_\-./:]{1,64}$")

_EDGE_TYPES = {"supports", "refutes", "supersedes", "depends_on", "topic", "semantic"}
_SEMANTIC_TAGS = {"≅", "↦", "⊑", "⊒", "~"}
_RECIPE_VERDICTS = {"support", "refute", "neutral"}


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    raise ValueError(msg)


def _is_ref(x: Any) -> bool:
    return isinstance(x, str) and bool(_REF_RE.match(x))


def _require_ref(x: Any, msg: str) -> None:
    _require(_is_ref(x), msg)


def _require_str(x: Any, msg: str) -> None:
    _require(isinstance(x, str), msg)


def _require_list(x: Any, msg: str) -> None:
    _require(isinstance(x, Sequence) and not isinstance(x, (str, bytes)), msg)


def _require_file_spec(spec: Any, msg: str) -> None:
    _require(isinstance(spec, Mapping), msg)
    if "ref" in spec:
        _require_ref(spec.get("ref"), "file spec ref must be sha256:<64hex>")
        return
    if "text" in spec:
        _require_str(spec.get("text"), "file spec text must be a string")
        return
    if "binding" in spec:
        _require_str(spec.get("binding"), "file spec binding must be a string")
        return
    raise ValueError("file spec must contain one of: ref, text, binding")


def validate_object(obj: Any) -> None:
    _require(isinstance(obj, Mapping), "object must be a JSON object")
    schema = obj.get("schema")
    _require_str(schema, "object.schema must be a string")

    if schema == SCHEMA_DOMAIN_V1:
        _require_str(obj.get("domain_id"), "domain.domain_id must be a string")
        _require_str(obj.get("name"), "domain.name must be a string")
        tags = obj.get("tags", [])
        _require_list(tags, "domain.tags must be a list")
        for t in tags:
            _require_str(t, "domain.tags items must be strings")
            _require(bool(_TAG_RE.match(t)), "domain.tags contains an invalid tag")
        return

    if schema == SCHEMA_CONTEXT_V1:
        _require_str(obj.get("context_key"), "context.context_key must be a string")
        if "domain_ref" in obj and obj["domain_ref"] is not None:
            _require_ref(obj["domain_ref"], "context.domain_ref must be sha256:<64hex>")
        tc = obj.get("toolchain", {})
        if tc:
            _require(isinstance(tc, Mapping), "context.toolchain must be an object")
            _require_str(tc.get("name"), "context.toolchain.name must be a string")
            _require_ref(tc.get("digest"), "context.toolchain.digest must be sha256:<64hex>")
        h = obj.get("harness", {})
        if h:
            _require(isinstance(h, Mapping), "context.harness must be an object")
            _require_str(h.get("id"), "context.harness.id must be a string")
            _require_ref(h.get("digest"), "context.harness.digest must be sha256:<64hex>")
        return

    if schema == SCHEMA_RECIPE_V1:
        _require_str(obj.get("recipe_id", ""), "recipe.recipe_id must be a string")
        argv = obj.get("argv")
        _require_list(argv, "recipe.argv must be a list")
        _require(len(argv) > 0, "recipe.argv must be non-empty")
        for a in argv:
            _require_str(a, "recipe.argv items must be strings")

        verdict = obj.get("verdict_on_pass", "support")
        _require_str(verdict, "recipe.verdict_on_pass must be a string")
        _require(verdict in _RECIPE_VERDICTS, f"recipe.verdict_on_pass must be one of {sorted(_RECIPE_VERDICTS)}")

        req = obj.get("requires", [])
        _require_list(req, "recipe.requires must be a list")
        for e in req:
            _require_str(e, "recipe.requires items must be strings")

        reqp = obj.get("requires_paths", [])
        _require_list(reqp, "recipe.requires_paths must be a list")
        for p in reqp:
            _require_str(p, "recipe.requires_paths items must be strings")

        env = obj.get("env", {})
        _require(isinstance(env, Mapping), "recipe.env must be an object")

        files = obj.get("files", {})
        _require(isinstance(files, Mapping), "recipe.files must be an object")
        for name, spec in files.items():
            _require_str(name, "recipe.files keys must be strings")
            _require_file_spec(spec, "recipe.files values must be file specs")

        stdin = obj.get("stdin", None)
        if stdin is not None:
            _require_file_spec(stdin, "recipe.stdin must be a file spec")

        if "timeout_ms" in obj:
            _require(isinstance(obj.get("timeout_ms"), int) and int(obj.get("timeout_ms")) > 0, "recipe.timeout_ms must be a positive int")
        if "max_output_bytes" in obj:
            _require(
                isinstance(obj.get("max_output_bytes"), int) and int(obj.get("max_output_bytes")) > 0,
                "recipe.max_output_bytes must be a positive int",
            )
        if "max_capture_bytes" in obj:
            _require(
                isinstance(obj.get("max_capture_bytes"), int) and int(obj.get("max_capture_bytes")) > 0,
                "recipe.max_capture_bytes must be a positive int",
            )

        expect = obj.get("expect", {})
        _require(isinstance(expect, Mapping), "recipe.expect must be an object")
        if "exit_code" in expect:
            _require(isinstance(expect.get("exit_code"), int), "recipe.expect.exit_code must be an int")
        if "stdout_contains" in expect:
            _require_str(expect.get("stdout_contains"), "recipe.expect.stdout_contains must be a string")
        if "stderr_contains" in expect:
            _require_str(expect.get("stderr_contains"), "recipe.expect.stderr_contains must be a string")
        if "stdout_not_contains" in expect:
            _require_str(expect.get("stdout_not_contains"), "recipe.expect.stdout_not_contains must be a string")
        if "stderr_not_contains" in expect:
            _require_str(expect.get("stderr_not_contains"), "recipe.expect.stderr_not_contains must be a string")
        if "stdout_regex" in expect:
            _require_str(expect.get("stdout_regex"), "recipe.expect.stdout_regex must be a string")
        if "stderr_regex" in expect:
            _require_str(expect.get("stderr_regex"), "recipe.expect.stderr_regex must be a string")
        if "files_exist" in expect:
            fe = expect.get("files_exist")
            _require_list(fe, "recipe.expect.files_exist must be a list")
            for p in fe:
                _require_str(p, "recipe.expect.files_exist items must be strings")
        if "files_not_exist" in expect:
            fe = expect.get("files_not_exist")
            _require_list(fe, "recipe.expect.files_not_exist must be a list")
            for p in fe:
                _require_str(p, "recipe.expect.files_not_exist items must be strings")

        cap = obj.get("capture_paths", [])
        _require_list(cap, "recipe.capture_paths must be a list")
        for p in cap:
            _require_str(p, "recipe.capture_paths items must be strings")

        artifacts = obj.get("artifacts", {})
        _require(isinstance(artifacts, Mapping), "recipe.artifacts must be an object")
        for aid, spec in artifacts.items():
            _require_str(aid, "recipe.artifacts keys must be strings")
            _require(isinstance(spec, Mapping), "recipe.artifacts values must be objects")
            _require_str(spec.get("path"), "recipe.artifacts[*].path must be a string")
            if "max_bytes" in spec:
                _require(isinstance(spec.get("max_bytes"), int) and int(spec.get("max_bytes")) > 0, "recipe.artifacts[*].max_bytes must be a positive int")
            if "media_type" in spec:
                _require_str(spec.get("media_type"), "recipe.artifacts[*].media_type must be a string")

        return

    if schema == SCHEMA_HYPOTHESIS_V1:
        _require_str(obj.get("hypothesis_id"), "hypothesis.hypothesis_id must be a string")
        _require_str(obj.get("title"), "hypothesis.title must be a string")
        kind = obj.get("kind", "other")
        _require_str(kind, "hypothesis.kind must be a string")
        st = obj.get("statement")
        _require(isinstance(st, Mapping), "hypothesis.statement must be an object")
        _require_str(st.get("lang"), "hypothesis.statement.lang must be a string")
        _require_str(st.get("body"), "hypothesis.statement.body must be a string")

        tags = obj.get("tags", [])
        _require_list(tags, "hypothesis.tags must be a list")
        for t in tags:
            _require_str(t, "hypothesis.tags items must be strings")
            _require(bool(_TAG_RE.match(t)), "hypothesis.tags contains an invalid tag")

        if "domain_ref" in obj and obj["domain_ref"] is not None:
            _require_ref(obj["domain_ref"], "hypothesis.domain_ref must be sha256:<64hex>")
        if "context_ref" in obj and obj["context_ref"] is not None:
            _require_ref(obj["context_ref"], "hypothesis.context_ref must be sha256:<64hex>")

        checks = obj.get("check_recipe_refs", [])
        _require_list(checks, "hypothesis.check_recipe_refs must be a list")
        _require(len(checks) > 0, "hypothesis must include at least one check recipe (falsifiability gate)")
        for r in checks:
            _require_ref(r, "hypothesis.check_recipe_refs must contain sha256:<64hex>")
        return

    if schema == SCHEMA_EVIDENCE_V1:
        _require_str(obj.get("evidence_kind"), "evidence.evidence_kind must be a string")
        _require_ref(obj.get("recipe_ref"), "evidence.recipe_ref must be sha256:<64hex>")
        if "context_ref" in obj and obj["context_ref"] is not None:
            _require_ref(obj.get("context_ref"), "evidence.context_ref must be sha256:<64hex>")
        subs = obj.get("subject_refs", [])
        _require_list(subs, "evidence.subject_refs must be a list")
        for r in subs:
            _require_ref(r, "evidence.subject_refs must contain sha256:<64hex>")
        res = obj.get("result", {})
        _require(isinstance(res, Mapping), "evidence.result must be an object")
        _require_str(res.get("status"), "evidence.result.status must be a string")
        if "exit_code" in res and res["exit_code"] is not None:
            _require(isinstance(res.get("exit_code"), int), "evidence.result.exit_code must be an int or null")
        if obj.get("stdout_ref"):
            _require_ref(obj.get("stdout_ref"), "evidence.stdout_ref must be sha256:<64hex>")
        if obj.get("stderr_ref"):
            _require_ref(obj.get("stderr_ref"), "evidence.stderr_ref must be sha256:<64hex>")
        outs = obj.get("outputs", [])
        _require_list(outs, "evidence.outputs must be a list")
        for o in outs:
            _require(isinstance(o, Mapping), "evidence.outputs items must be objects")
            _require_str(o.get("name"), "evidence.outputs[*].name must be a string")
            _require_ref(o.get("ref"), "evidence.outputs[*].ref must be sha256:<64hex>")

        if "argv" in obj:
            argv = obj.get("argv")
            _require_list(argv, "evidence.argv must be a list")
            for a in argv:
                _require_str(a, "evidence.argv items must be strings")
        if "duration_ms" in obj:
            _require(isinstance(obj.get("duration_ms"), int) and int(obj.get("duration_ms")) >= 0, "evidence.duration_ms must be an int >= 0")
        for k in ("stdout_truncated", "stderr_truncated"):
            if k in obj:
                _require(isinstance(obj.get(k), bool), f"evidence.{k} must be a bool")
        tc = obj.get("toolchain", {})
        if tc:
            _require(isinstance(tc, Mapping), "evidence.toolchain must be an object")
            exes = tc.get("executables", {})
            _require(isinstance(exes, Mapping), "evidence.toolchain.executables must be an object")
            for _k, v in exes.items():
                _require(isinstance(v, Mapping), "evidence.toolchain.executables values must be objects")
                _require_str(v.get("path"), "evidence.toolchain.executables[*].path must be a string")
                h = v.get("sha256", "")
                if h:
                    _require_ref(h, "evidence.toolchain.executables[*].sha256 must be sha256:<64hex>")
        return

    if schema == SCHEMA_ARTIFACT_V1:
        _require_str(obj.get("name"), "artifact.name must be a string")
        _require_str(obj.get("kind"), "artifact.kind must be a string")
        _require_str(obj.get("media_type"), "artifact.media_type must be a string")
        _require_ref(obj.get("blob_ref"), "artifact.blob_ref must be sha256:<64hex>")
        return

    if schema == SCHEMA_EDGE_V1:
        et = obj.get("edge_type")
        _require_str(et, "edge.edge_type must be a string")
        _require(et in _EDGE_TYPES, f"edge.edge_type must be one of {sorted(_EDGE_TYPES)}")
        _require_ref(obj.get("from_ref"), "edge.from_ref must be sha256:<64hex>")
        _require_ref(obj.get("to_ref"), "edge.to_ref must be sha256:<64hex>")
        if "context_ref" in obj and obj["context_ref"] is not None:
            _require_ref(obj.get("context_ref"), "edge.context_ref must be sha256:<64hex>")
        if et == "semantic":
            tag = obj.get("tag")
            _require_str(tag, "edge.tag must be a string for semantic edges")
            _require(tag in _SEMANTIC_TAGS, f"edge.tag must be one of {sorted(_SEMANTIC_TAGS)}")
            obs = obj.get("obligations", [])
            _require_list(obs, "edge.obligations must be a list")
            for ob in obs:
                _require(isinstance(ob, Mapping), "edge.obligations items must be objects")
                _require_str(ob.get("obligation_id"), "obligation.obligation_id must be a string")
                _require_ref(ob.get("recipe_ref"), "obligation.recipe_ref must be sha256:<64hex>")
        ev = obj.get("evidence_refs", [])
        _require_list(ev, "edge.evidence_refs must be a list")
        for r in ev:
            _require_ref(r, "edge.evidence_refs must contain sha256:<64hex>")
        return

    if schema == SCHEMA_CHECKPOINT_V1:
        _require_str(obj.get("created_at"), "checkpoint.created_at must be a string")
        _require_str(obj.get("log_head"), "checkpoint.log_head must be a string")
        if obj.get("log_head"):
            _require_ref(obj.get("log_head"), "checkpoint.log_head must be sha256:<64hex>")
        _require(isinstance(obj.get("event_count"), int), "checkpoint.event_count must be an int")
        return

    raise ValueError(f"unknown schema: {schema}")
