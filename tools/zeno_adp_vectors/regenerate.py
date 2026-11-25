"""Rebuild vectors/zeno_adp_0_8_0.json from Zeno-ADP 0.8.0.

    python3 tools/zeno_adp_vectors/regenerate.py [--zeno-adp-path PATH] [--check]

Runs this directory's Rust program twice: once for its seeded random plan charts, and once
on the charts that core.experiment_plan builds for twelve seeded experiment requests.
--zeno-adp-path builds against a local checkout of the v0.8.0 tag instead of fetching it.
--check compares with the committed file.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = ROOT / "vectors" / "zeno_adp_0_8_0.json"
sys.path.insert(0, str(ROOT / "src"))

from popperpad.core.experiment_plan import (
    CandidateCheck,
    ExperimentRequest,
    experiment_chart,
)


def requests() -> list[ExperimentRequest]:
    rnd = random.Random(2026)
    out = []
    for case in range(12):
        hyps = tuple(f"sha256:{i:064x}" for i in range(1 + case % 3))
        checks = []
        for n in range(1 + case % 4):
            checks.append(CandidateCheck(hypothesis_ref=rnd.choice(hyps), recipe_ref=f"sha256:{100 + n:064x}",
                                         verdict_on_pass=rnd.choice(("support", "refute")), cost=rnd.randint(1, 3)))
        out.append(ExperimentRequest(hypotheses=hyps, checks=tuple(checks), pending_cost=2 + case % 3,
                                     regret_budget=case % 3))
    return out


def experiment_charts() -> str:
    lines = []
    for request in requests():
        chart, _ = experiment_chart(request)
        out = [chart.worlds, chart.root, len(chart.cells)]
        for steps in chart.cells:
            out.append(len(steps))
            for step in steps:
                out += [step.credit, -1 if step.child is None else step.child, *step.costs]
        out += [request.regret_budget] * chart.worlds
        lines.append(" ".join(map(str, out)))
    return "\n".join(lines) + "\n"


def cargo(args: list[str], path: str | None, stdin: str | None = None) -> str:
    command = ["cargo", "run", "--quiet", "--release", "--manifest-path", str(HERE / "Cargo.toml")]
    if path:
        command += ["--config", f'patch."https://github.com/TheDarkLightX/Zeno-ADP".zeno-adp.path="{path}"']
    command += ["--", *args] if args else []
    return subprocess.run(command, input=stdin, capture_output=True, text=True, check=True).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zeno-adp-path")
    parser.add_argument("--check", action="store_true")
    a = parser.parse_args()
    random_cases = json.loads(cargo([], a.zeno_adp_path))
    vectors = {"schema": random_cases["schema"], "zeno_adp": random_cases["zeno_adp"],
               "robust_prefix": random_cases["robust_prefix"],
               "experiment_charts": json.loads(cargo(["--stdin"], a.zeno_adp_path, experiment_charts())),
               "generator": "tools/zeno_adp_vectors (Zeno-ADP 0.8.0, tag v0.8.0, commit b4003a1)"}
    text = json.dumps(vectors, separators=(",", ":"))
    if a.check:
        same = TARGET.read_text(encoding="utf-8") == text
        print("vectors match" if same else "vectors differ")
        return 0 if same else 1
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
