#!/usr/bin/env python3
"""Run authentic, isolated PopperPad CLI workflows for media capture."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CLI = REPO / ".venv" / "bin" / "popperpad"
WORK_ROOT = Path("/tmp/popperpad-media-kit")
PROMPT = "popperpad %"


def run(
    scene_root: Path,
    args: list[str],
    *,
    show: bool,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [str(CLI), *args]
    if show:
        print(f"{PROMPT} {shlex.join(['popperpad', *args])}")
    env = os.environ.copy()
    env.update({"NO_COLOR": "1", "TERM": "dumb", "PYTHONHASHSEED": "0"})
    result = subprocess.run(
        command,
        cwd=scene_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if show and result.stdout:
        print(result.stdout.rstrip())
    if check and result.returncode != 0:
        if not show and result.stdout:
            print(result.stdout.rstrip())
        raise SystemExit(result.returncode)
    return result


def write_object(scene_root: Path, filename: str, obj: dict[str, Any]) -> Path:
    objects = scene_root / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    path = objects / filename
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return path


def add_object(
    scene_root: Path,
    filename: str,
    obj: dict[str, Any],
    *,
    show: bool,
) -> str:
    write_object(scene_root, filename, obj)
    result = run(
        scene_root,
        ["--pad", "./pad", "add", "--json", f"./objects/{filename}"],
        show=show,
    )
    return str(json.loads(result.stdout)["obj_ref"])


def fresh_scene(name: str, *, show_init: bool = False) -> Path:
    root = WORK_ROOT / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    run(root, ["--pad", "./pad", "init"], show=show_init)
    return root


def domain_object(domain_id: str, name: str, tags: list[str]) -> dict[str, Any]:
    return {
        "schema": "popperpad/domain/v1",
        "domain_id": domain_id,
        "name": name,
        "tags": tags,
    }


def support_recipe_object() -> dict[str, Any]:
    script = """set -euo pipefail
printf '%s\n' '-0.2' '0.1' '0.3' > readings.txt
awk '($1 < -0.5 || $1 > 0.5) { exit 1 } END { print "within-bound" }' readings.txt
"""
    return {
        "schema": "popperpad/recipe/v1",
        "recipe_id": "sensor-drift-support-v1",
        "verdict_on_pass": "support",
        "requires": ["bash", "awk"],
        "argv": ["bash", "-lc", script],
        "expect": {
            "exit_code": 0,
            "stdout_contains": "within-bound",
            "files_exist": ["readings.txt"],
        },
        "capture_paths": ["readings.txt"],
        "timeout_ms": 5000,
    }


def refute_recipe_object() -> dict[str, Any]:
    script = """set -euo pipefail
printf '%s\n' '0.8' > stress.txt
awk '($1 < -0.5 || $1 > 0.5) {
  print "{\\"reading_c\\":" $1 ",\\"limit_c\\":0.5}" > "counterexample.json"
  found=1
}
END {
  if (found) print "counterexample-found"
  else exit 1
}' stress.txt
"""
    return {
        "schema": "popperpad/recipe/v1",
        "recipe_id": "sensor-drift-refuter-v1",
        "verdict_on_pass": "refute",
        "requires": ["bash", "awk"],
        "argv": ["bash", "-lc", script],
        "expect": {
            "exit_code": 0,
            "stdout_contains": "counterexample-found",
            "files_exist": ["counterexample.json"],
        },
        "artifacts": {
            "counterexample": {
                "path": "counterexample.json",
                "max_bytes": 4096,
                "media_type": "application/json",
            }
        },
        "timeout_ms": 5000,
    }


def seed_hypothesis(scene_name: str) -> tuple[Path, str, str]:
    root = fresh_scene(scene_name)
    domain_ref = add_object(
        root,
        "domain.json",
        domain_object(
            "sensor-calibration",
            "Environmental Sensor Calibration",
            ["measurement", "falsification"],
        ),
        show=False,
    )
    context_ref = add_object(
        root,
        "context.json",
        {
            "schema": "popperpad/context/v1",
            "context_key": "synthetic-bench-v1",
            "domain_ref": domain_ref,
        },
        show=False,
    )
    support_ref = add_object(
        root,
        "support-recipe.json",
        support_recipe_object(),
        show=False,
    )
    refute_ref = add_object(
        root,
        "refute-recipe.json",
        refute_recipe_object(),
        show=False,
    )
    hypothesis_ref = add_object(
        root,
        "hypothesis.json",
        {
            "schema": "popperpad/hypothesis/v1",
            "hypothesis_id": "sensor-drift-bound",
            "kind": "empirical",
            "title": "Sensor drift remains within ±0.5 °C",
            "statement": {
                "lang": "text",
                "body": "Every calibration reading remains within ±0.5 °C of reference.",
            },
            "domain_ref": domain_ref,
            "context_ref": context_ref,
            "tags": ["calibration", "counterexample-search"],
            "check_recipe_refs": [support_ref, refute_ref],
        },
        show=False,
    )
    return root, hypothesis_ref, context_ref


def scene_ledger() -> None:
    root = fresh_scene("ledger", show_init=True)
    domain_ref = add_object(
        root,
        "domain.json",
        domain_object(
            "sensor-calibration",
            "Environmental Sensor Calibration",
            ["measurement", "falsification"],
        ),
        show=True,
    )
    recipe_ref = add_object(
        root,
        "support-recipe.json",
        support_recipe_object(),
        show=True,
    )
    add_object(
        root,
        "hypothesis.json",
        {
            "schema": "popperpad/hypothesis/v1",
            "hypothesis_id": "sensor-drift-bound",
            "kind": "empirical",
            "title": "Sensor drift remains within ±0.5 °C",
            "statement": {
                "lang": "text",
                "body": "Every calibration reading remains within ±0.5 °C of reference.",
            },
            "domain_ref": domain_ref,
            "tags": ["calibration", "counterexample-search"],
            "check_recipe_refs": [recipe_ref],
        },
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "query",
            "--schema",
            "popperpad/hypothesis/v1",
            "--limit",
            "5",
        ],
        show=True,
    )


def scene_support() -> None:
    root, hypothesis_ref, context_ref = seed_hypothesis("support")
    run(
        root,
        [
            "--pad",
            "./pad",
            "status",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "prove",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "status",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )


def scene_refute() -> None:
    root, hypothesis_ref, context_ref = seed_hypothesis("refute")
    run(
        root,
        [
            "--pad",
            "./pad",
            "refute",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "status",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "query",
            "--schema",
            "popperpad/artifact/v1",
            "--limit",
            "5",
        ],
        show=True,
    )


def scene_dispute() -> None:
    root, hypothesis_ref, context_ref = seed_hypothesis("dispute")
    run(
        root,
        [
            "--pad",
            "./pad",
            "prove",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "refute",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "status",
            hypothesis_ref,
            "--context",
            context_ref,
        ],
        show=True,
    )


def scene_transfer() -> None:
    root = fresh_scene("transfer")
    source_ref = add_object(
        root,
        "source-domain.json",
        domain_object("graph-minimization", "Graph Minimization", ["graphs"]),
        show=False,
    )
    target_ref = add_object(
        root,
        "target-domain.json",
        domain_object(
            "workflow-reduction",
            "Workflow State Reduction",
            ["state-machines"],
        ),
        show=False,
    )
    add_object(
        root,
        "semantic-edge.json",
        {
            "schema": "popperpad/edge/v1",
            "edge_type": "semantic",
            "from_ref": source_ref,
            "to_ref": target_ref,
            "tag": "≅",
            "obligations": [],
            "evidence_refs": [],
        },
        show=True,
    )
    run(
        root,
        [
            "--pad",
            "./pad",
            "transfer-paths",
            "--from",
            source_ref,
            "--to",
            target_ref,
            "--max-depth",
            "2",
            "--require-validated",
        ],
        show=True,
    )


def scene_integrity() -> None:
    root = fresh_scene("integrity")
    notes = root / "observations.txt"
    notes.write_text(
        "calibration-set=v1\nsamples=3\nresult=within-bound\n",
        encoding="utf-8",
    )
    blob_result = run(
        root,
        [
            "--pad",
            "./pad",
            "blob-put",
            "--path",
            "./observations.txt",
            "--media-type",
            "text/plain",
        ],
        show=True,
    )
    blob_ref = str(json.loads(blob_result.stdout)["blob_ref"])
    run(
        root,
        [
            "--pad",
            "./pad",
            "blob-get",
            blob_ref,
            "--out",
            "./replayed-observations.txt",
        ],
        show=True,
    )
    run(root, ["--pad", "./pad", "checkpoint"], show=True)
    run(root, ["--pad", "./pad", "doctor"], show=True)


SCENES = {
    "ledger": scene_ledger,
    "support": scene_support,
    "refute": scene_refute,
    "dispute": scene_dispute,
    "transfer": scene_transfer,
    "integrity": scene_integrity,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture authentic PopperPad CLI workflows."
    )
    parser.add_argument(
        "scene",
        choices=[*SCENES, "all"],
        default="all",
        nargs="?",
    )
    args = parser.parse_args()
    if not CLI.exists():
        raise SystemExit("install PopperPad in .venv first: pip install -e .[dev]")
    selected = SCENES.values() if args.scene == "all" else (SCENES[args.scene],)
    for index, scene in enumerate(selected):
        if index:
            print()
        scene()


if __name__ == "__main__":
    main()
