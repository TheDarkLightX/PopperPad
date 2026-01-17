from __future__ import annotations

import tempfile
from pathlib import Path


def test_cas_and_log_and_doctor() -> None:
    from popperpad.pad import PopperPad

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()
        rep = pad.put_blob(b"hello", media_type="text/plain")
        assert pad.get_blob(rep.obj_ref) == b"hello"
        pad.doctor(strict=True)


def test_prove_refute_status_and_transfer_paths() -> None:
    from popperpad.pad import PopperPad
    from popperpad.schemas import SCHEMA_DOMAIN_V1, SCHEMA_EDGE_V1, SCHEMA_HYPOTHESIS_V1, SCHEMA_RECIPE_V1

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()

        # Two domains + an equivalence edge for transfer-paths.
        dom_a = pad.put_object({"schema": SCHEMA_DOMAIN_V1, "domain_id": "A", "name": "Domain A", "tags": []}).obj_ref
        dom_b = pad.put_object({"schema": SCHEMA_DOMAIN_V1, "domain_id": "B", "name": "Domain B", "tags": []}).obj_ref
        edge = pad.put_object(
            {
                "schema": SCHEMA_EDGE_V1,
                "edge_type": "semantic",
                "from_ref": dom_a,
                "to_ref": dom_b,
                "tag": "≅",
                "obligations": [],
                "evidence_refs": [],
            }
        ).obj_ref
        paths = pad.transfer_paths(from_ref=dom_a, to_ref=dom_b, max_depth=2)
        assert any(p["path"] == [edge] for p in paths)

        # Recipes.
        support_recipe = pad.put_object(
            {
                "schema": SCHEMA_RECIPE_V1,
                "recipe_id": "py_ok",
                "verdict_on_pass": "support",
                "argv": ["${PYTHON}", "-c", "print('ok')"],
                "expect": {"exit_code": 0, "stdout_contains": "ok"},
            }
        ).obj_ref
        refute_recipe = pad.put_object(
            {
                "schema": SCHEMA_RECIPE_V1,
                "recipe_id": "py_ce",
                "verdict_on_pass": "refute",
                "argv": ["${PYTHON}", "-c", "open('ce.txt','w').write('ce'); print('found')"],
                "expect": {"exit_code": 0, "stdout_contains": "found"},
                "capture_paths": ["ce.txt"],
            }
        ).obj_ref

        hyp = pad.put_object(
            {
                "schema": SCHEMA_HYPOTHESIS_V1,
                "hypothesis_id": "H1",
                "kind": "tactic",
                "title": "Test hypothesis",
                "statement": {"lang": "text", "body": "x"},
                "domain_ref": dom_a,
                "tags": ["demo"],
                "check_recipe_refs": [support_recipe, refute_recipe],
            }
        ).obj_ref

        # Prove -> supported.
        rep = pad.run_hypothesis(hyp, context_ref=None, mode="prove")
        assert rep.verdict == "PASS"
        st = pad.status(hyp, context_ref=None)
        assert st.state == "supported"

        # Refute -> disputed.
        rep2 = pad.run_hypothesis(hyp, context_ref=None, mode="refute")
        assert rep2.verdict == "PASS"
        st2 = pad.status(hyp, context_ref=None)
        assert st2.state == "disputed"

        pad.doctor(strict=True)
