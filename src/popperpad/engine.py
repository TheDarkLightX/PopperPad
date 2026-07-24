from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .core.check import (
    AggregateVerdict,
    CheckSummary,
    RunIntent,
    decide_check_summary,
    recipe_applies,
)
from .core.values import thaw_json
from .log import utc_now_iso
from .refs import is_ref, require
from .runner import RunRecipeResult, run_recipe
from .schemas import (
    SCHEMA_ARTIFACT_V1,
    SCHEMA_EDGE_V1,
    SCHEMA_EVIDENCE_V1,
    SCHEMA_HYPOTHESIS_V1,
    SCHEMA_RECIPE_V1,
)


@dataclass(frozen=True, slots=True)
class RunResult:
    ok: bool
    verdict: str  # PASS|FAIL|INCONCLUSIVE
    evidence_refs: tuple[str, ...]
    edge_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RecipeOutcome:
    evidence_ref: str
    edge_refs: tuple[str, ...]
    category: str  # pass|fail|inconclusive


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


def _recipe_matches_intent(recipe: Mapping[str, Any], intent: RunIntent) -> bool:
    return recipe_applies(str(recipe.get("verdict_on_pass", "support")), intent)


def _plain_outputs(result: RunRecipeResult) -> tuple[dict[str, Any], ...]:
    return tuple(thaw_json(output) for output in result.outputs)


def _build_evidence_object(
    *, result: RunRecipeResult, recipe_ref: str, hyp_ref: str, context_ref: str | None
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
        "toolchain": thaw_json(result.toolchain),
        "duration_ms": result.duration_ms,
        "argv": list(result.argv),
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "outputs": list(_plain_outputs(result)),
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
    *,
    pad: _PadLike,
    ev_ref: str,
    hyp_ref: str,
    context_ref: str | None,
    outputs: tuple[dict[str, Any], ...],
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


def _counterexample_ref(pad: _PadLike, ev_ref: str, outputs: tuple[dict[str, Any], ...]) -> str:
    if not outputs:
        return ev_ref
    first = outputs[0]
    artifact = {
        "schema": SCHEMA_ARTIFACT_V1,
        "name": str(first["name"]),
        "kind": "counterexample",
        "media_type": str(first.get("media_type", "application/octet-stream")),
        "blob_ref": str(first["ref"]),
    }
    return pad.put_object(artifact).obj_ref


class CheckEngine:
    """Imperative interpreter for immutable recipe and evidence decisions."""

    def __init__(self, pad: _PadLike) -> None:
        self._pad = pad

    def run_hypothesis(self, hyp_ref: str, *, context_ref: str | None, mode: str) -> RunResult:
        intent = RunIntent(mode)
        hypothesis = self._pad.get_object(hyp_ref)
        require(
            isinstance(hypothesis, Mapping) and hypothesis.get("schema") == SCHEMA_HYPOTHESIS_V1,
            "ref is not a hypothesis",
        )
        if context_ref is not None:
            require(is_ref(context_ref), "invalid context ref")

        recipe_refs = tuple(hypothesis.get("check_recipe_refs", ()) or ())
        require(recipe_refs, "hypothesis has no check recipes")

        evidence_refs: list[str] = []
        edge_refs: list[str] = []
        categories: list[str] = []
        for recipe_ref in self._matching_recipes(recipe_refs, intent):
            outcome = self._run_one_recipe(recipe_ref, intent, hyp_ref, context_ref)
            evidence_refs.append(outcome.evidence_ref)
            edge_refs.extend(outcome.edge_refs)
            categories.append(outcome.category)

        verdict = decide_check_summary(CheckSummary(intent=intent, categories=tuple(categories)))
        return RunResult(
            ok=verdict == AggregateVerdict.PASS,
            verdict=verdict.value,
            evidence_refs=tuple(evidence_refs),
            edge_refs=tuple(edge_refs),
        )

    def _run_one_recipe(
        self,
        recipe: tuple[str, Mapping[str, Any]],
        intent: RunIntent,
        hyp_ref: str,
        context_ref: str | None,
    ) -> _RecipeOutcome:
        result = run_recipe(cas=self._pad.cas, recipe=recipe[1], bindings={}, repo_root=None)
        evidence = _build_evidence_object(
            result=result, recipe_ref=recipe[0], hyp_ref=hyp_ref, context_ref=context_ref
        )
        evidence_ref = self._pad.put_object(evidence).obj_ref
        edge_refs: tuple[str, ...] = ()
        if result.status == "PASS":
            edge_refs = self._emit_edges(
                intent,
                evidence_ref,
                hyp_ref,
                context_ref,
                _plain_outputs(result),
            )
        return _RecipeOutcome(
            evidence_ref=evidence_ref,
            edge_refs=edge_refs,
            category=_status_category(result.status),
        )

    def _matching_recipes(
        self, recipe_refs: tuple[Any, ...], intent: RunIntent
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        recipes: list[tuple[str, Mapping[str, Any]]] = []
        for ref in recipe_refs:
            if not is_ref(ref):
                continue
            recipe = self._pad.get_object(str(ref))
            if not (isinstance(recipe, Mapping) and recipe.get("schema") == SCHEMA_RECIPE_V1):
                continue
            if not _recipe_matches_intent(recipe, intent):
                continue
            recipes.append((str(ref), recipe))
        return tuple(recipes)

    def _emit_edges(
        self,
        intent: RunIntent,
        evidence_ref: str,
        hyp_ref: str,
        context_ref: str | None,
        outputs: tuple[dict[str, Any], ...],
    ) -> tuple[str, ...]:
        if intent == RunIntent.PROVE:
            edge = _build_supports_edge(ev_ref=evidence_ref, hyp_ref=hyp_ref, context_ref=context_ref)
            return (self._pad.put_object(edge).obj_ref,)
        edge = _build_refutes_edge(
            pad=self._pad,
            ev_ref=evidence_ref,
            hyp_ref=hyp_ref,
            context_ref=context_ref,
            outputs=outputs,
        )
        return (self._pad.put_object(edge).obj_ref,)
