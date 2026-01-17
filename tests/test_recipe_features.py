from __future__ import annotations

import tempfile
from pathlib import Path


def test_recipe_stdin_regex_not_contains_files_exist_and_artifacts() -> None:
    from popperpad.pad import PopperPad
    from popperpad.schemas import SCHEMA_HYPOTHESIS_V1, SCHEMA_RECIPE_V1

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()

        recipe = pad.put_object(
            {
                "schema": SCHEMA_RECIPE_V1,
                "recipe_id": "stdin_regex",
                "verdict_on_pass": "support",
                "argv": [
                    "${PYTHON}",
                    "-c",
                    "import sys; d=sys.stdin.read().strip(); open('x.txt','w').write('abcdef'); print('got:'+d)",
                ],
                "stdin": {"text": "hi\n"},
                "expect": {
                    "exit_code": 0,
                    "stdout_regex": r"got:hi",
                    "stdout_not_contains": "bye",
                    "files_exist": ["x.txt"],
                },
                "artifacts": {"ce": {"path": "x.txt", "max_bytes": 2, "media_type": "text/plain"}},
            }
        ).obj_ref

        hyp = pad.put_object(
            {
                "schema": SCHEMA_HYPOTHESIS_V1,
                "hypothesis_id": "H_stdin",
                "kind": "tactic",
                "title": "stdin + artifacts",
                "statement": {"lang": "text", "body": "demo"},
                "tags": ["demo"],
                "check_recipe_refs": [recipe],
            }
        ).obj_ref

        rep = pad.run_hypothesis(hyp, context_ref=None, mode="prove")
        assert rep.verdict == "PASS"
        assert rep.evidence_refs

        ev = pad.get_object(rep.evidence_refs[0])
        outs = list(ev.get("outputs", []))
        assert any(o.get("name") == "ce" for o in outs)
        o0 = [o for o in outs if o.get("name") == "ce"][0]
        assert o0.get("truncated") is True
        assert pad.get_blob(o0["ref"]) == b"ab"

        pad.doctor(strict=True)


def test_doctor_catches_missing_refs() -> None:
    from popperpad.pad import PopperPad
    from popperpad.schemas import SCHEMA_EDGE_V1

    with tempfile.TemporaryDirectory() as td:
        pad = PopperPad(root=Path(td) / "pad")
        pad.init()

        missing = "sha256:" + ("0" * 64)
        pad.put_object(
            {
                "schema": SCHEMA_EDGE_V1,
                "edge_type": "supersedes",
                "from_ref": missing,
                "to_ref": missing,
                "context_ref": None,
                "evidence_refs": [],
            }
        )

        try:
            pad.doctor(strict=True)
        except ValueError:
            pass
        else:
            raise AssertionError("doctor(strict=True) should fail on missing refs")

