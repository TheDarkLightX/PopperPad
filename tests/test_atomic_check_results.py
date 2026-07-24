from __future__ import annotations

from pathlib import Path

from popperpad.core.check import RunIntent
from popperpad.core.evidence import (
    CapturedOutput,
    CheckExecution,
    ExecutionStatus,
    PlannedCheckObjects,
    plan_check_objects,
)
from popperpad.core.values import FrozenDict
from popperpad.pad import PopperPad
from popperpad.schemas import SCHEMA_HYPOTHESIS_V1, SCHEMA_RECIPE_V1


def _recipe(pad: PopperPad, *, recipe_id: str, verdict: str, script: str, expect: dict) -> str:
    return pad.put_object(
        {
            "schema": SCHEMA_RECIPE_V1,
            "recipe_id": recipe_id,
            "verdict_on_pass": verdict,
            "argv": ["${PYTHON}", "-c", script],
            "expect": expect,
            "capture_paths": ["ce.txt"] if verdict == "refute" else [],
        }
    ).obj_ref


def _hypothesis(pad: PopperPad, recipe_refs: list[str]) -> str:
    return pad.put_object(
        {
            "schema": SCHEMA_HYPOTHESIS_V1,
            "hypothesis_id": "H",
            "title": "Atomic check result",
            "statement": {"lang": "text", "body": "P"},
            "check_recipe_refs": recipe_refs,
            "tags": [],
        }
    ).obj_ref


def test_support_evidence_and_edge_publish_in_one_commit(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    recipe_ref = _recipe(
        pad,
        recipe_id="support",
        verdict="support",
        script="print('ok')",
        expect={"exit_code": 0, "stdout_contains": "ok"},
    )
    hypothesis_ref = _hypothesis(pad, [recipe_ref])
    before = pad.log.stats()["event_count"]

    result = pad.run_hypothesis(hypothesis_ref, context_ref=None, mode="prove")

    assert result.ok
    assert len(result.evidence_refs) == 1
    assert len(result.edge_refs) == 1
    assert result.commit_root.startswith("sha256:")
    assert pad.log.stats()["event_count"] == before + 1
    latest = list(pad.log.iter_raw_records())[-1]
    assert latest["op"] == "commit_bundle"
    assert len(latest["objects"]) == 2
    assert len(latest["blobs"]) == 1
    assert pad.status(hypothesis_ref, context_ref=None).state == "supported"
    pad.doctor(strict=True)


def test_duplicate_recipe_refs_execute_and_publish_once(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    recipe_ref = _recipe(
        pad,
        recipe_id="deduplicated-support",
        verdict="support",
        script="print('ok')",
        expect={"exit_code": 0, "stdout_contains": "ok"},
    )
    hypothesis_ref = _hypothesis(pad, [recipe_ref, recipe_ref])
    before = pad.log.stats()["event_count"]

    result = pad.run_hypothesis(hypothesis_ref, context_ref=None, mode="prove")

    assert result.ok
    assert len(result.evidence_refs) == 1
    assert len(result.edge_refs) == 1
    assert pad.log.stats()["event_count"] == before + 1
    pad.doctor(strict=True)


def test_refutation_evidence_artifact_edge_and_blobs_publish_together(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    recipe_ref = _recipe(
        pad,
        recipe_id="refute",
        verdict="refute",
        script="open('ce.txt','w').write('x=17'); print('found')",
        expect={"exit_code": 0, "stdout_contains": "found"},
    )
    hypothesis_ref = _hypothesis(pad, [recipe_ref])
    before = pad.log.stats()["event_count"]

    result = pad.run_hypothesis(hypothesis_ref, context_ref=None, mode="refute")

    assert result.ok
    assert len(result.evidence_refs) == 1
    assert len(result.edge_refs) == 1
    assert pad.log.stats()["event_count"] == before + 1
    latest = list(pad.log.iter_raw_records())[-1]
    assert len(latest["objects"]) == 3  # evidence + counterexample artifact + edge
    assert len(latest["blobs"]) == 2  # stdout + counterexample bytes
    assert pad.status(hypothesis_ref, context_ref=None).state == "falsified"
    pad.doctor(strict=True)


def test_failed_check_commits_evidence_but_no_truth_edge(tmp_path: Path) -> None:
    pad = PopperPad(root=tmp_path / "pad")
    pad.init()
    recipe_ref = _recipe(
        pad,
        recipe_id="failure",
        verdict="support",
        script="print('not-ok')",
        expect={"exit_code": 0, "stdout_contains": "expected-token"},
    )
    hypothesis_ref = _hypothesis(pad, [recipe_ref])
    before = pad.log.stats()["event_count"]

    result = pad.run_hypothesis(hypothesis_ref, context_ref=None, mode="prove")

    assert result.verdict == "FAIL"
    assert len(result.evidence_refs) == 1
    assert result.edge_refs == ()
    assert pad.log.stats()["event_count"] == before + 1
    latest = list(pad.log.iter_raw_records())[-1]
    assert len(latest["objects"]) == 1
    assert pad.status(hypothesis_ref, context_ref=None).state == "unknown"
    pad.doctor(strict=True)


def test_evidence_plan_is_deterministic_from_complete_explicit_inputs() -> None:
    hypothesis_ref = "sha256:" + "a" * 64
    recipe_ref = "sha256:" + "b" * 64
    output_ref = "sha256:" + "c" * 64
    execution = CheckExecution(
        intent=RunIntent.REFUTE,
        recipe_ref=recipe_ref,
        hypothesis_ref=hypothesis_ref,
        context_ref=None,
        created_at="2026-07-24T00:00:00Z",
        status=ExecutionStatus.PASS,
        reason="pass",
        exit_code=0,
        stdout_ref="",
        stderr_ref="",
        outputs=(
            CapturedOutput(
                name="witness",
                ref=output_ref,
                byte_size=4,
                truncated=False,
                path="witness.txt",
                media_type="text/plain",
            ),
        ),
        toolchain=FrozenDict(),
        duration_ms=10,
        argv=("checker",),
        stdout_truncated=False,
        stderr_truncated=False,
    )
    first = plan_check_objects(execution)
    second = plan_check_objects(execution)
    assert isinstance(first, PlannedCheckObjects)
    assert first == second
    assert first.artifact_ref is not None
    assert first.edge_ref is not None
