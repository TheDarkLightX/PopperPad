from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from popperpad.cli import main
from popperpad.core.experiment_plan import (
    CandidateCheck,
    ExperimentRequest,
    experiment_chart,
    plan_experiments,
)
from popperpad.core.result import Reject
from popperpad.core.robust_prefix import regret

H1, H2 = "sha256:" + "a" * 64, "sha256:" + "b" * 64


def check(hyp: str, n: int, verdict: str, cost: int) -> CandidateCheck:
    return CandidateCheck(hypothesis_ref=hyp, recipe_ref=f"sha256:{n:064x}", verdict_on_pass=verdict, cost=cost)


def test_a_cheap_falsification_attempt_is_the_robust_first_move() -> None:
    cheap_refute, costly_support = check(H1, 1, "refute", 1), check(H1, 2, "support", 5)
    plan = plan_experiments(ExperimentRequest((H1,), (cheap_refute, costly_support), pending_cost=10, regret_budget=1))
    assert plan.worlds == 2
    # Where the hypothesis holds the refutation fails and costs 1 extra; where it fails, it settles it.
    # Starting with the support check would cost 5 extra where the hypothesis fails.
    assert plan.first_check == cheap_refute and plan.first_check_regret == 1
    assert plan.run_now == ()  # every check fails in some world, so none is optimal everywhere
    assert plan.within_budget == (cheap_refute,)
    assert plan.within_budget_regret == (1, 0)


def test_budgeted_commitment_never_exceeds_the_budget_in_any_world() -> None:
    checks = (check(H1, 1, "refute", 1), check(H1, 2, "support", 2), check(H2, 3, "support", 1), check(H2, 4, "refute", 3))
    for budget in range(4):
        request = ExperimentRequest((H1, H2), checks, pending_cost=4, regret_budget=budget)
        plan = plan_experiments(request)
        assert max(plan.within_budget_regret) <= budget
        chart, _ = experiment_chart(request)
        assert plan.worlds == chart.worlds == 4
        assert len(regret(chart, ())) == 4


@pytest.mark.parametrize(
    ("hypotheses", "checks", "code"),
    [
        ((), (check(H1, 1, "refute", 1),), "EXPERIMENT_HYPOTHESES_OUT_OF_BOUNDS"),
        ((H1,), (), "EXPERIMENT_CHECKS_OUT_OF_BOUNDS"),
        ((H1,), (check(H2, 1, "refute", 1),), "EXPERIMENT_CHECK_FOR_UNKNOWN_HYPOTHESIS"),
        ((H1,), tuple(check(H1, n, "refute", 1) for n in range(9)), "EXPERIMENT_CHECKS_OUT_OF_BOUNDS"),
    ],
)
def test_out_of_bounds_requests_are_rejected(hypotheses, checks, code) -> None:
    result = plan_experiments(ExperimentRequest(hypotheses, checks, pending_cost=3, regret_budget=1))
    assert isinstance(result, Reject) and result.code == code


def test_check_values_validate_their_fields() -> None:
    for kwargs in ({"verdict_on_pass": "maybe"}, {"cost": 0}, {"cost": 1.5}, {"recipe_ref": ""}):
        with pytest.raises((TypeError, ValueError)):
            CandidateCheck(**({"hypothesis_ref": H1, "recipe_ref": "r", "verdict_on_pass": "refute", "cost": 1} | kwargs))


def _pad_with_hypothesis(root: Path):
    from popperpad.pad import PopperPad
    from popperpad.schemas import (
        SCHEMA_DOMAIN_V1,
        SCHEMA_HYPOTHESIS_V1,
        SCHEMA_RECIPE_V1,
    )

    pad = PopperPad(root=root)
    pad.init()
    domain = pad.put_object({"schema": SCHEMA_DOMAIN_V1, "domain_id": "A", "name": "A", "tags": []}).obj_ref
    refute = pad.put_object({"schema": SCHEMA_RECIPE_V1, "recipe_id": "ce", "verdict_on_pass": "refute",
                             "argv": ["${PYTHON}", "-c", "print('found')"], "timeout_ms": 1000,
                             "expect": {"exit_code": 0, "stdout_contains": "found"}}).obj_ref
    support = pad.put_object({"schema": SCHEMA_RECIPE_V1, "recipe_id": "ok", "verdict_on_pass": "support",
                              "argv": ["${PYTHON}", "-c", "print('ok')"], "timeout_ms": 5000,
                              "expect": {"exit_code": 0, "stdout_contains": "ok"}}).obj_ref
    hyp = pad.put_object({"schema": SCHEMA_HYPOTHESIS_V1, "hypothesis_id": "H1", "kind": "tactic", "title": "t",
                          "statement": {"lang": "text", "body": "x"}, "domain_ref": domain, "tags": [],
                          "check_recipe_refs": [support, refute]}).obj_ref
    return pad, hyp, support, refute


def test_pad_plans_unknown_hypotheses_from_recipe_time_budgets() -> None:
    with tempfile.TemporaryDirectory() as td:
        pad, hyp, support, refute = _pad_with_hypothesis(Path(td) / "pad")
        pending, plan = pad.plan_checks([hyp], context_ref=None, pending_cost=10, regret_budget=1)
        assert pending == (hyp,)
        assert {c.recipe_ref: c.cost for c in (plan.first_check, *plan.within_budget)} == {refute: 1}
        provenance = pad.provenance(hyp, context_ref=None)
        assert provenance.state == "unknown"

        assert pad.run_hypothesis(hyp, context_ref=None, mode="prove").verdict == "PASS"
        provenance = pad.provenance(hyp, context_ref=None)
        assert provenance.state == pad.status(hyp, context_ref=None).state == "supported"
        assert provenance.supports.cut("recipe").items == (support,)
        assert pad.plan_checks([hyp], context_ref=None) == ((), None)  # nothing pending


def test_cli_provenance_and_plan_checks(capsys: pytest.CaptureFixture[str]) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pad"
        _pad, hyp, _support, refute = _pad_with_hypothesis(root)
        assert main(["--pad", str(root), "plan-checks", hyp, "--pending-cost", "10", "--cost", f"{refute}=2"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["first_check"]["recipe_ref"] == refute and out["first_check"]["cost"] == 2
        assert out["worlds"] == 2 and out["run_now"] == []
        assert main(["--pad", str(root), "provenance", hyp]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["state"] == "unknown" and out["changes"] == []
        with pytest.raises(SystemExit):
            main(["--pad", str(root), "plan-checks", hyp, "--cost", "not-a-pair"])


@pytest.mark.parametrize("neutral_only", [False, True])
def test_pad_skips_neutral_recipes(tmp_path: Path, neutral_only: bool) -> None:
    from popperpad.schemas import SCHEMA_RECIPE_V1

    pad, hyp, support, refute = _pad_with_hypothesis(tmp_path / "pad")
    neutral = pad.put_object({"schema": SCHEMA_RECIPE_V1, "recipe_id": "diagnostic",
                              "verdict_on_pass": "neutral", "argv": ["unused"],
                              "timeout_ms": 1000, "expect": {"exit_code": 0}}).obj_ref
    obj = dict(pad.get_object(hyp))
    obj["check_recipe_refs"] = [neutral] if neutral_only else [support, neutral, refute]
    hyp = pad.put_object(obj).obj_ref
    pending, plan = pad.plan_checks([hyp], context_ref=None, pending_cost=10)
    assert pending == (hyp,)
    if neutral_only:
        assert isinstance(plan, Reject)
        assert plan.code == "EXPERIMENT_CHECKS_OUT_OF_BOUNDS"
    else:
        assert plan.first_check.recipe_ref == refute
        assert all(c.recipe_ref != neutral for c in (*plan.run_now, *plan.within_budget))
    assert pad.status(hyp, context_ref=None).state == "unknown"
