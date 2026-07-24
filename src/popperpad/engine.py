from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .core.check import AggregateVerdict, CheckSummary, RunIntent, decide_check_summary, recipe_applies
from .core.evidence import (
    CapturedOutput,
    CheckExecution,
    ExecutionStatus,
    PlannedCheckObjects,
    object_ref,
    plan_check_objects,
)
from .core.result import Reject
from .core.values import thaw_json
from .log import utc_now_iso
from .refs import ValidationError, is_ref, require
from .runner import RunRecipeResult, run_recipe
from .schemas import SCHEMA_HYPOTHESIS_V1, SCHEMA_RECIPE_V1


@dataclass(frozen=True, slots=True)
class RunResult:
    ok: bool
    verdict: str  # PASS|FAIL|INCONCLUSIVE
    evidence_refs: tuple[str, ...]
    edge_refs: tuple[str, ...]
    commit_root: str = ""
    record_hash: str = ""


@dataclass(frozen=True, slots=True)
class _RecipeOutcome:
    planned: PlannedCheckObjects
    category: str  # pass|fail|inconclusive
    blobs: tuple[tuple[str, bytes, str], ...]


def _status_category(status: str) -> str:
    if status == "PASS":
        return "pass"
    if status == "FAIL":
        return "fail"
    return "inconclusive"


class _PadLike(Protocol):
    def get_object(self, ref: str) -> Any: ...
    def get_blob(self, ref: str) -> bytes: ...
    def commit_values(
        self,
        *,
        objects: tuple[Mapping[str, Any], ...],
        blobs: tuple[tuple[bytes, str], ...],
        created_at: str | None = None,
        policy_version: str = "popperpad-policy/v1",
        core_version: str = "popperpad-core/v1",
    ) -> Any: ...

    @property
    def cas(self) -> Any: ...


def _recipe_matches_intent(recipe: Mapping[str, Any], intent: RunIntent) -> bool:
    return recipe_applies(str(recipe.get("verdict_on_pass", "support")), intent)


def _captured_outputs(result: RunRecipeResult) -> tuple[CapturedOutput, ...]:
    outputs: list[CapturedOutput] = []
    for index, frozen in enumerate(result.outputs):
        plain = thaw_json(frozen)
        if not isinstance(plain, Mapping):
            raise ValidationError(f"captured output {index} is not an object")
        try:
            outputs.append(
                CapturedOutput(
                    name=str(plain["name"]),
                    ref=str(plain["ref"]),
                    byte_size=int(plain.get("bytes", 0)),
                    truncated=bool(plain.get("truncated", False)),
                    path=str(plain.get("path", plain["name"])),
                    media_type=str(plain.get("media_type", "application/octet-stream")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"invalid captured output {index}: {exc}") from exc
    return tuple(outputs)


def _execution_from_result(
    *,
    result: RunRecipeResult,
    intent: RunIntent,
    recipe_ref: str,
    hypothesis_ref: str,
    context_ref: str | None,
    created_at: str,
) -> CheckExecution:
    return CheckExecution(
        intent=intent,
        recipe_ref=recipe_ref,
        hypothesis_ref=hypothesis_ref,
        context_ref=context_ref,
        created_at=created_at,
        status=ExecutionStatus(result.status),
        reason=result.reason,
        exit_code=result.exit_code,
        stdout_ref=result.stdout_ref,
        stderr_ref=result.stderr_ref,
        outputs=_captured_outputs(result),
        toolchain=result.toolchain,
        duration_ms=result.duration_ms,
        argv=result.argv,
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
    )


def _planned_plain_objects(planned: PlannedCheckObjects) -> tuple[Mapping[str, Any], ...]:
    objects: list[Mapping[str, Any]] = []
    for value in planned.objects:
        plain = thaw_json(value)
        if not isinstance(plain, Mapping):
            raise ValidationError("planned check object is not a mapping")
        objects.append(plain)
    return tuple(objects)


class CheckEngine:
    """Imperative interpreter for pure recipe, evidence, and commit decisions."""

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

        outcomes: list[_RecipeOutcome] = []
        for recipe in self._matching_recipes(recipe_refs, intent):
            outcomes.append(self._run_one_recipe(recipe, intent, hyp_ref, context_ref))

        categories = tuple(outcome.category for outcome in outcomes)
        verdict = decide_check_summary(CheckSummary(intent=intent, categories=categories))
        if not outcomes:
            return RunResult(
                ok=False,
                verdict=verdict.value,
                evidence_refs=(),
                edge_refs=(),
            )

        object_values_by_ref: dict[str, Mapping[str, Any]] = {}
        evidence_refs: list[str] = []
        edge_refs: list[str] = []
        unique_blobs: dict[str, tuple[bytes, str]] = {}
        for outcome in outcomes:
            plain_objects = _planned_plain_objects(outcome.planned)
            for frozen, plain in zip(outcome.planned.objects, plain_objects):
                ref = object_ref(frozen)
                existing = object_values_by_ref.get(ref)
                require(existing is None or existing == plain, "planned object ref collision")
                object_values_by_ref.setdefault(ref, plain)
            evidence_refs.append(outcome.planned.evidence_ref)
            if outcome.planned.edge_ref is not None:
                edge_refs.append(outcome.planned.edge_ref)
            for ref, payload, media_type in outcome.blobs:
                unique_blobs.setdefault(ref, (payload, media_type))

        committed = self._pad.commit_values(
            objects=tuple(object_values_by_ref.values()),
            blobs=tuple(unique_blobs.values()),
            created_at=utc_now_iso(),
            policy_version="popperpad-check-policy/v1",
            core_version="popperpad-core/v1",
        )
        expected_object_refs = tuple(object_values_by_ref)
        require(committed.object_refs == expected_object_refs, "committed check refs differ from pure plan")

        return RunResult(
            ok=verdict == AggregateVerdict.PASS,
            verdict=verdict.value,
            evidence_refs=tuple(evidence_refs),
            edge_refs=tuple(edge_refs),
            commit_root=committed.commit_root,
            record_hash=committed.record_hash,
        )

    def _run_one_recipe(
        self,
        recipe: tuple[str, Mapping[str, Any]],
        intent: RunIntent,
        hypothesis_ref: str,
        context_ref: str | None,
    ) -> _RecipeOutcome:
        result = run_recipe(cas=self._pad.cas, recipe=recipe[1], bindings={}, repo_root=None)
        execution = _execution_from_result(
            result=result,
            intent=intent,
            recipe_ref=recipe[0],
            hypothesis_ref=hypothesis_ref,
            context_ref=context_ref,
            created_at=utc_now_iso(),
        )
        planned = plan_check_objects(execution)
        if isinstance(planned, Reject):
            raise ValidationError(f"{planned.code}: {thaw_json(planned.details)}")
        return _RecipeOutcome(
            planned=planned,
            category=_status_category(result.status),
            blobs=self._result_blobs(result, execution.outputs),
        )

    def _result_blobs(
        self, result: RunRecipeResult, outputs: tuple[CapturedOutput, ...]
    ) -> tuple[tuple[str, bytes, str], ...]:
        blobs: list[tuple[str, bytes, str]] = []
        if result.stdout_ref:
            blobs.append((result.stdout_ref, self._pad.get_blob(result.stdout_ref), "text/plain; charset=utf-8"))
        if result.stderr_ref:
            blobs.append((result.stderr_ref, self._pad.get_blob(result.stderr_ref), "text/plain; charset=utf-8"))
        for output in outputs:
            blobs.append((output.ref, self._pad.get_blob(output.ref), output.media_type))
        return tuple(blobs)

    def _matching_recipes(
        self, recipe_refs: tuple[Any, ...], intent: RunIntent
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        recipes: list[tuple[str, Mapping[str, Any]]] = []
        seen_refs: set[str] = set()
        for ref in recipe_refs:
            if not is_ref(ref):
                continue
            recipe_ref = str(ref)
            if recipe_ref in seen_refs:
                continue
            seen_refs.add(recipe_ref)
            recipe = self._pad.get_object(recipe_ref)
            if not (isinstance(recipe, Mapping) and recipe.get("schema") == SCHEMA_RECIPE_V1):
                continue
            if not _recipe_matches_intent(recipe, intent):
                continue
            recipes.append((recipe_ref, recipe))
        return tuple(recipes)
