from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .pad import PopperPad
from .validate import validate_object


def _read_json(path: str) -> Any:
    if path == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _print(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="popperpad")
    p.add_argument("--pad", default="popperpad_data", help="Pad directory (default: popperpad_data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_init = sub.add_parser("init", help="Initialize a pad directory")

    s_add = sub.add_parser("add", help="Add a JSON object to CAS + log")
    s_add.add_argument("--json", required=True, help="Path to object JSON (or '-' for stdin)")

    s_prove = sub.add_parser("prove", help="Run support recipes for a hypothesis (emit evidence + supports edges)")
    s_prove.add_argument("hypothesis_ref", help="Hypothesis ref (sha256:<64hex>)")
    s_prove.add_argument("--context", default=None, help="Optional context ref (sha256:<64hex>)")

    s_refute = sub.add_parser("refute", help="Run refuter recipes for a hypothesis (emit evidence + refutes edges)")
    s_refute.add_argument("hypothesis_ref", help="Hypothesis ref (sha256:<64hex>)")
    s_refute.add_argument("--context", default=None, help="Optional context ref (sha256:<64hex>)")

    s_status = sub.add_parser("status", help="Compute derived status for a hypothesis")
    s_status.add_argument("hypothesis_ref", help="Hypothesis ref (sha256:<64hex>)")
    s_status.add_argument("--context", default=None, help="Optional context ref (sha256:<64hex>)")

    s_doc = sub.add_parser("doctor", help="Consistency checks (hash chain + object validation)")
    s_doc.add_argument("--no-strict", action="store_true", help="Exit 0 even if issues are found")

    s_ck = sub.add_parser("checkpoint", help="Write a checkpoint object (log head + event count)")

    s_q = sub.add_parser("query", help="List objects by schema (best-effort, scans log)")
    s_q.add_argument("--schema", default="", help="Object schema to list (e.g. popperpad/hypothesis/v1)")
    s_q.add_argument("--limit", type=int, default=50)

    s_tp = sub.add_parser("transfer-paths", help="Find semantic-edge paths between two refs")
    s_tp.add_argument("--from", dest="from_ref", required=True, help="Start ref (sha256:<64hex>)")
    s_tp.add_argument("--to", dest="to_ref", required=True, help="End ref (sha256:<64hex>)")
    s_tp.add_argument("--max-depth", type=int, default=4)
    s_tp.add_argument("--require-validated", action="store_true", help="Only traverse validated semantic edges")

    ns = p.parse_args(argv)

    pad = PopperPad(root=Path(ns.pad))
    if ns.cmd == "init":
        pad.init()
        _print({"ok": True, "pad": str(Path(ns.pad).resolve())})
        return 0

    pad.init()

    if ns.cmd == "add":
        obj = _read_json(str(ns.json))
        validate_object(obj)
        rep = pad.put_object(obj)
        _print({"ok": True, "obj_ref": rep.obj_ref, "record_hash": rep.record_hash})
        return 0

    if ns.cmd == "prove":
        rep = pad.run_hypothesis(str(ns.hypothesis_ref), context_ref=ns.context, mode="prove")
        _print({"ok": rep.ok, "verdict": rep.verdict, "evidence_refs": rep.evidence_refs, "edge_refs": rep.edge_refs})
        return 0 if rep.ok else 1

    if ns.cmd == "refute":
        rep = pad.run_hypothesis(str(ns.hypothesis_ref), context_ref=ns.context, mode="refute")
        _print({"ok": rep.ok, "verdict": rep.verdict, "evidence_refs": rep.evidence_refs, "edge_refs": rep.edge_refs})
        return 0 if rep.ok else 1

    if ns.cmd == "status":
        rep = pad.status(str(ns.hypothesis_ref), context_ref=ns.context)
        _print({"ok": True, "state": rep.state, "supports": rep.supports, "refutes": rep.refutes})
        return 0

    if ns.cmd == "doctor":
        rep = pad.doctor(strict=False)
        _print({"ok": rep.ok, "result": rep.__dict__})
        return 0 if rep.ok or bool(ns.no_strict) else 1

    if ns.cmd == "checkpoint":
        rep = pad.checkpoint()
        _print({"ok": True, "checkpoint_ref": rep.obj_ref, "record_hash": rep.record_hash})
        return 0

    if ns.cmd == "query":
        schema = str(ns.schema).strip()
        limit = int(ns.limit)
        out: list[dict[str, Any]] = []
        for rec in pad.log.iter_records():
            if rec.get("op") != "add_object":
                continue
            if schema and rec.get("obj_schema") != schema:
                continue
            ref = rec.get("obj_ref")
            if not isinstance(ref, str):
                continue
            try:
                obj = pad.get_object(ref)
            except Exception:
                continue
            item = {"ref": ref, "schema": rec.get("obj_schema", "")}
            if isinstance(obj, dict):
                # Common UX fields.
                for k in ("title", "hypothesis_id", "domain_id", "context_key", "recipe_id", "edge_type"):
                    if k in obj:
                        item[k] = obj.get(k)
            out.append(item)
            if limit and len(out) >= limit:
                break
        _print({"ok": True, "objects": out})
        return 0

    if ns.cmd == "transfer-paths":
        paths = pad.transfer_paths(
            from_ref=str(ns.from_ref),
            to_ref=str(ns.to_ref),
            max_depth=int(ns.max_depth),
            require_validated=bool(ns.require_validated),
        )
        _print({"ok": True, "paths": paths})
        return 0

    raise RuntimeError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())

