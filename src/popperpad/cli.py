from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from .gamification import aggregate_score_events
from .pad import PopperPad
from .refs import is_ref
from .schemas import SCHEMA_GAMIFICATION_SCORE_EVENT_V1
from .tui import print_dashboard, run_tui
from .validate import validate_object


def _read_json(path: str) -> Any:
    if path == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_bytes(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    return Path(path).read_bytes()


def _write_bytes(path: str, data: bytes) -> None:
    if path == "-":
        sys.stdout.buffer.write(data)
        return
    Path(path).write_bytes(data)


def _print(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, indent=2) + "\n")


class Command:
    """A CLI subcommand: its argument wiring and its handler."""

    def __init__(self, name: str, help_: str, configure: Callable[[argparse.ArgumentParser], None], run: Callable[[PopperPad, argparse.Namespace], int]):
        self.name = name
        self.help = help_
        self.configure = configure
        self.run = run


def _cmd_init(pad: PopperPad, ns: argparse.Namespace) -> int:
    _print({"ok": True, "pad": str(Path(ns.pad).resolve())})
    return 0


def _cmd_add(pad: PopperPad, ns: argparse.Namespace) -> int:
    obj = _read_json(str(ns.json))
    validate_object(obj)
    rep = pad.put_object(obj)
    _print({"ok": True, "obj_ref": rep.obj_ref, "record_hash": rep.record_hash})
    return 0


def _cmd_blob_put(pad: PopperPad, ns: argparse.Namespace) -> int:
    data = _read_bytes(str(ns.path))
    rep = pad.put_blob(data, media_type=str(ns.media_type))
    _print({
        "ok": True,
        "blob_ref": rep.obj_ref,
        "record_hash": rep.record_hash,
        "bytes": len(data),
        "media_type": str(ns.media_type),
    })
    return 0


def _cmd_blob_get(pad: PopperPad, ns: argparse.Namespace) -> int:
    data = pad.get_blob(str(ns.blob_ref))
    _write_bytes(str(ns.out), data)
    if str(ns.out) != "-":
        _print({"ok": True, "blob_ref": str(ns.blob_ref), "bytes": len(data), "out": str(Path(ns.out).resolve())})
    return 0


def _cmd_prove(pad: PopperPad, ns: argparse.Namespace) -> int:
    rep = pad.run_hypothesis(str(ns.hypothesis_ref), context_ref=ns.context, mode="prove")
    _print({"ok": rep.ok, "verdict": rep.verdict, "evidence_refs": rep.evidence_refs, "edge_refs": rep.edge_refs})
    return 0 if rep.ok else 1


def _cmd_refute(pad: PopperPad, ns: argparse.Namespace) -> int:
    rep = pad.run_hypothesis(str(ns.hypothesis_ref), context_ref=ns.context, mode="refute")
    _print({"ok": rep.ok, "verdict": rep.verdict, "evidence_refs": rep.evidence_refs, "edge_refs": rep.edge_refs})
    return 0 if rep.ok else 1


def _cmd_status(pad: PopperPad, ns: argparse.Namespace) -> int:
    rep = pad.status(str(ns.hypothesis_ref), context_ref=ns.context)
    _print({"ok": True, "state": rep.state, "supports": rep.supports, "refutes": rep.refutes})
    return 0


def _cmd_doctor(pad: PopperPad, ns: argparse.Namespace) -> int:
    rep = pad.doctor(strict=False)
    _print({"ok": rep.ok, "result": rep.__dict__})
    return 0 if rep.ok or bool(ns.no_strict) else 1


def _cmd_checkpoint(pad: PopperPad, ns: argparse.Namespace) -> int:
    rep = pad.checkpoint()
    _print({"ok": True, "checkpoint_ref": rep.obj_ref, "record_hash": rep.record_hash})
    return 0


def _cmd_query(pad: PopperPad, ns: argparse.Namespace) -> int:
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
        out.append(_query_item(pad, ref, rec))
        if limit and len(out) >= limit:
            break
    _print({"ok": True, "objects": out})
    return 0


def _query_item(pad: PopperPad, ref: str, rec: Mapping[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"ref": ref, "schema": rec.get("obj_schema", "")}
    try:
        obj = pad.get_object(ref)
    except Exception:
        return item
    if isinstance(obj, dict):
        for key in ("title", "hypothesis_id", "domain_id", "context_key", "recipe_id", "edge_type"):
            if key in obj:
                item[key] = obj.get(key)
    return item


def _cmd_transfer_paths(pad: PopperPad, ns: argparse.Namespace) -> int:
    paths = pad.transfer_paths(
        from_ref=str(ns.from_ref),
        to_ref=str(ns.to_ref),
        max_depth=int(ns.max_depth),
        require_validated=bool(ns.require_validated),
    )
    _print({"ok": True, "paths": paths})
    return 0


def _cmd_gamification_leaderboard(pad: PopperPad, ns: argparse.Namespace) -> int:
    events = [obj for _ref, obj in pad._iter_objects_by_schema(SCHEMA_GAMIFICATION_SCORE_EVENT_V1)]
    event_kinds = set(ns.event_kind) if ns.event_kind else None
    rows = aggregate_score_events(
        events,
        point_kind=ns.point_kind,
        domain_ref=ns.domain,
        event_kinds=event_kinds,
        strict=False,
    )
    limit = int(ns.limit)
    if limit > 0:
        rows = rows[:limit]
    _print({"ok": True, "leaderboard": rows})
    return 0


def _configure_init(p: argparse.ArgumentParser) -> None:
    pass


def _configure_add(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", required=True, help="Path to object JSON (or '-' for stdin)")


def _configure_blob_put(p: argparse.ArgumentParser) -> None:
    p.add_argument("--path", required=True, help="Path to bytes (or '-' for stdin)")
    p.add_argument("--media-type", default="application/octet-stream")


def _configure_blob_get(p: argparse.ArgumentParser) -> None:
    p.add_argument("blob_ref", help="Blob ref (sha256:<64hex>)")
    p.add_argument("--out", required=True, help="Output path (or '-' for stdout)")


def _configure_prove(p: argparse.ArgumentParser) -> None:
    p.add_argument("hypothesis_ref", help="Hypothesis ref (sha256:<64hex>)")
    p.add_argument("--context", default=None, help="Optional context ref (sha256:<64hex>)")


def _configure_refute(p: argparse.ArgumentParser) -> None:
    p.add_argument("hypothesis_ref", help="Hypothesis ref (sha256:<64hex>)")
    p.add_argument("--context", default=None, help="Optional context ref (sha256:<64hex>)")


def _configure_status(p: argparse.ArgumentParser) -> None:
    p.add_argument("hypothesis_ref", help="Hypothesis ref (sha256:<64hex>)")
    p.add_argument("--context", default=None, help="Optional context ref (sha256:<64hex>)")


def _configure_doctor(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-strict", action="store_true", help="Exit 0 even if issues are found")


def _configure_checkpoint(p: argparse.ArgumentParser) -> None:
    pass


def _configure_query(p: argparse.ArgumentParser) -> None:
    p.add_argument("--schema", default="", help="Object schema to list (e.g. popperpad/hypothesis/v1)")
    p.add_argument("--limit", type=int, default=50)


def _configure_transfer_paths(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from", dest="from_ref", required=True, help="Start ref (sha256:<64hex>)")
    p.add_argument("--to", dest="to_ref", required=True, help="End ref (sha256:<64hex>)")
    p.add_argument("--max-depth", type=int, default=4)
    p.add_argument("--require-validated", action="store_true", help="Only traverse validated semantic edges")


def _configure_gamification_leaderboard(p: argparse.ArgumentParser) -> None:
    p.add_argument("--point-kind", default=None, help="Optional point kind filter, e.g. xp")
    p.add_argument("--domain", default=None, help="Optional domain ref filter")
    p.add_argument("--event-kind", action="append", default=None, help="Optional event kind filter; repeatable")
    p.add_argument("--limit", type=int, default=20)


def _cmd_dashboard(pad: PopperPad, ns: argparse.Namespace) -> int:
    print_dashboard(str(ns.pad))
    return 0


def _cmd_tui(pad: PopperPad, ns: argparse.Namespace) -> int:
    run_tui(str(ns.pad))
    return 0


def _configure_dashboard(p: argparse.ArgumentParser) -> None:
    pass


def _configure_tui(p: argparse.ArgumentParser) -> None:
    pass


COMMANDS: list[Command] = [
    Command("init", "Initialize a pad directory", _configure_init, _cmd_init),
    Command("add", "Add a JSON object to CAS + log", _configure_add, _cmd_add),
    Command("blob-put", "Add a blob (bytes) to CAS + log", _configure_blob_put, _cmd_blob_put),
    Command("blob-get", "Fetch a blob from CAS", _configure_blob_get, _cmd_blob_get),
    Command("prove", "Run support recipes for a hypothesis (emit evidence + supports edges)", _configure_prove, _cmd_prove),
    Command("refute", "Run refuter recipes for a hypothesis (emit evidence + refutes edges)", _configure_refute, _cmd_refute),
    Command("status", "Compute derived status for a hypothesis", _configure_status, _cmd_status),
    Command("doctor", "Consistency checks (hash chain + object validation)", _configure_doctor, _cmd_doctor),
    Command("checkpoint", "Write a checkpoint object (log head + event count)", _configure_checkpoint, _cmd_checkpoint),
    Command("query", "List objects by schema (best-effort, scans log)", _configure_query, _cmd_query),
    Command("transfer-paths", "Find semantic-edge paths between two refs", _configure_transfer_paths, _cmd_transfer_paths),
    Command("gamification-leaderboard", "Derive a leaderboard from score events", _configure_gamification_leaderboard, _cmd_gamification_leaderboard),
    Command("dashboard", "Print a rich dashboard summary", _configure_dashboard, _cmd_dashboard),
    Command("tui", "Launch the interactive textual TUI", _configure_tui, _cmd_tui),
]


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, Command]]:
    parser = argparse.ArgumentParser(prog="popperpad")
    parser.add_argument("--pad", default="popperpad_data", help="Pad directory (default: popperpad_data)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    registry: dict[str, Command] = {}
    for command in COMMANDS:
        registry[command.name] = command
        sub_parser = sub.add_parser(command.name, help=command.help, description=command.help)
        sub_parser.add_argument(
            "--pad",
            default=argparse.SUPPRESS,
            help="Pad directory (default: popperpad_data)",
        )
        command.configure(sub_parser)
    return parser, registry


def main(argv: list[str] | None = None) -> int:
    parser, registry = _build_parser()
    ns = parser.parse_args(argv)
    command = registry[ns.cmd]
    pad = PopperPad(root=Path(ns.pad))
    pad.init()
    return command.run(pad, ns)


if __name__ == "__main__":
    raise SystemExit(main())
