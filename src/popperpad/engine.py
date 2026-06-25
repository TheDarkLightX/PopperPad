from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .log import utc_now_iso
from .refs import RunMode, Verdict, is_ref, require
from .runner import run_recipe
from .schemas import (
    SCHEMA_ARTIFACT_V1,
    SCHEMA_EDGE_V1,
    SCHEMA_EVIDENCE_V1,
    SCHEMA_HYPOTHESIS_V1,
    SCHEMA_RECIPE_V1,
)


@dataclass(frozen=True)
class RunResult:
    ok: bool
    verdict: str  # PASS|FAIL|INCONCLUSIVE
    evidence_refs: list[str]
    edge_refs: list[str]


@dataclass(frozen=True)
class _RecipeOutcome:
    evidence_ref: str
    edge_refs: list[str]
    category: str  # "pass" | "fail" | "inconclusive"


def _status_category(status: str) -> str:
    if status == "PASS":
        return "pass"
    if status == "FAIL":
        return "fail"
    return "inconclusive"


class _PadLike(Protocol):
    def get_object(self, ref: str) -> Any: ...
    def put_object(self, obj: Mapping[str, Any]) -> Any: ...
    @property
    def cas(self) -> Any: ...


def _recipe_matches_mode(recipe: Mapping[str, Any], mode: RunMode) -> bool:
    verdict_on_pass = str(recipe.get("verdict_on_pass", "support"))
    if mode is RunMode.PROVE:
        return verdict_on_pass == "support"
    return verdict_on_pass == "refute"


def _build_evidence_object(
    *, result: Any, recipe_ref: str, hyp_ref: str, context_ref: str | None
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema": SCHEMA_EVIDENCE_V1,
        "evidence_kind": "check",
        "created_at": utc_now_iso(),
        "recipe_ref": recipe_ref,
        "context_ref": context_ref,
        "subject_refs": [hyp_ref],
        "result": {"status": result.status.lower(), "exit_code": result.exit_code},
        "reason": result.reason,
        "toolchain": result.toolchain,
        "duration_ms": result.duration_ms,
        "argv": list(result.argv),
        "stdout_truncated": bool(result.stdout_truncated),
        "stderr_truncated": bool(result.stderr_truncated),
        "outputs": list(result.outputs),
    }
    if result.stdout_ref:
        evidence["stdout_ref"] = result.stdout_ref
    if result.stderr_ref:
        evidence["stderr_ref"] = result.stderr_ref
    return evidence


def _build_supports_edge(*, ev_ref: str, hyp_ref: str, context_ref: str | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA_EDGE_V1,
        "edge_type": "supports",
        "from_ref": ev_ref,
        "to_ref": hyp_ref,
        "context_ref": context_ref,
        "evidence_refs": [ev_ref],
    }


def _build_refutes_edge(
    *, pad: _PadLike, ev_ref: str, hyp_ref: str, context_ref: str | None, outputs: list[dict[str, Any]]
) -> dict[str, Any]:
    counterexample_ref = _counterexample_ref(pad, ev_ref, outputs)
    return {
        "schema": SCHEMA_EDGE_V1,
        "edge_type": "refutes",
        "from_ref": counterexample_ref,
        "to_ref": hyp_ref,
        "context_ref": context_ref,
        "evidence_refs": [ev_ref],
    }


def _counterexample_ref(pad: _PadLike, ev_ref: str, outputs: list[dict[str, Any]]) -> str:
    if not outputs:
        return ev_ref
    first = outputs[0]
    artifact = {
        "schema": SCHEMA_ARTIFACT_V1,
        "name": str(first["name"]),
        "kind": "counterexample",
        "media_type": "application/octet-stream",
        "blob_ref": str(first["ref"]),
    }
    return pad.put_object(artifact).obj_ref


def _decide_verdict(
    *, mode: RunMode, any_pass: bool, any_fail: bool, any_inconclusive: bool, has_evidence: bool
) -> Verdict:
    if not has_evidence:
        return Verdict.INCONCLUSIVE
    if mode is RunMode.REFUTE:
        if any_pass:
            return Verdict.PASS
        return Verdict.INCONCLUSIVE if any_inconclusive else Verdict.FAIL
    if any_fail:
        return Verdict.FAIL
    if any_pass:
        return Verdict.PASS
    return Verdict.INCONCLUSIVE


class CheckEngine:
    """Orchestrates prove/refute recipe runs and evidence/edge emission."""

    def __init__(self, pad: _PadLike) -> None:
        self._pad = pad

    def run_hypothesis(self, hyp_ref: str, *, context_ref: str | None, mode: str) -> RunResult:
        run_mode = RunMode(mode)
        hypothesis = self._pad.get_object(hyp_ref)
        require(
            isinstance(hypothesis, Mapping) and hypothesis.get("schema") == SCHEMA_HYPOTHESIS_V1,
            "ref is not a hypothesis",
        )
        if context_ref is not None:
            require(is_ref(context_ref), "invalid context ref")

        recipe_refs = list(hypothesis.get("check_recipe_refs", []) or [])
        require(recipe_refs, "hypothesis has no check recipes")

        evidence_refs: list[str] = []
        edge_refs: list[str] = []
        status_flags = {"pass": False, "fail": False, "inconclusive": False}
        for recipe_ref in self._matching_recipes(recipe_refs, run_mode):
            outcome = self._run_one_recipe(recipe_ref, run_mode, hyp_ref, context_ref)
            evidence_refs.append(outcome.evidence_ref)
            edge_refs.extend(outcome.edge_refs)
            status_flags[outcome.category] = True

        verdict = _decide_verdict(
            mode=run_mode,
            any_pass=status_flags["pass"],
            any_fail=status_flags["fail"],
            any_inconclusive=status_flags["inconclusive"],
            has_evidence=bool(evidence_refs),
        )
        return RunResult(
            ok=verdict is Verdict.PASS,
            verdict=verdict.value,
            evidence_refs=evidence_refs,
            edge_refs=edge_refs,
        )

    def _run_one_recipe(
        self, recipe: tuple[str, Mapping[str, Any]], mode: RunMode, hyp_ref: str, context_ref: str | None
    ) -> "_RecipeOutcome":
        result = run_recipe(cas=self._pad.cas, recipe=recipe[1], bindings={}, repo_root=None)
        evidence = _build_evidence_object(
            result=result, recipe_ref=recipe[0], hyp_ref=hyp_ref, context_ref=context_ref
        )
        evidence_ref = self._pad.put_object(evidence).obj_ref
        edge_refs: list[str] = []
        if result.status == "PASS":
            edge_refs = self._emit_edges(mode, evidence_ref, hyp_ref, context_ref, result.outputs)
        return _RecipeOutcome(
            evidence_ref=evidence_ref,
            edge_refs=edge_refs,
            category=_status_category(result.status),
        )

    def _matching_recipes(
        self, recipe_refs: list[Any], mode: RunMode
    ) -> list[tuple[str, Mapping[str, Any]]]:
        recipes: list[tuple[str, Mapping[str, Any]]] = []
        for ref in recipe_refs:
            if not is_ref(ref):
                continue
            recipe = self._pad.get_object(str(ref))
            if not (isinstance(recipe, Mapping) and recipe.get("schema") == SCHEMA_RECIPE_V1):
                continue
            if not _recipe_matches_mode(recipe, mode):
                continue
            recipes.append((str(ref), recipe))
        return recipes

    def _emit_edges(
        self, mode: RunMode, evidence_ref: str, hyp_ref: str, context_ref: str | None, outputs: list[dict[str, Any]]
    ) -> list[str]:
        if mode is RunMode.PROVE:
            edge = _build_supports_edge(ev_ref=evidence_ref, hyp_ref=hyp_ref, context_ref=context_ref)
            return [self._pad.put_object(edge).obj_ref]
        edge = _build_refutes_edge(
            pad=self._pad, ev_ref=evidence_ref, hyp_ref=hyp_ref, context_ref=context_ref, outputs=outputs
        )
        return [self._pad.put_object(edge).obj_ref]
