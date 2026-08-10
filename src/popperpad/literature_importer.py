"""Receipt-bound adapter from a frozen fleet export into PopperPad."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any

from .cli import main as popperpad_main
from .discovery.literature import MAX_EXPORT_BYTES

RECEIPT_SCHEMA = "codex-fleet-literature-import-receipt/v1"
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
SHA_RE = re.compile(r"sha256:[0-9a-f]{64}")


def sha_ref(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def write_receipt(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def make_receipt(
    *,
    importer_id: str,
    import_id: str,
    provider: str,
    artifact_sha256: str,
    status: str,
    external_refs: list[str],
    detail: str,
) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "importer_id": importer_id,
        "import_id": import_id,
        "provider": provider,
        "artifact_sha256": artifact_sha256,
        "status": status,
        "authority": "triage_only",
        "external_refs": external_refs,
        "detail": detail,
    }


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pad", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--provider", choices=("citracer", "mosaic"), required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--import-id", required=True)
    parser.add_argument("--importer-id", required=True)
    args = parser.parse_args(argv)
    for label, value in (("import-id", args.import_id), ("importer-id", args.importer_id)):
        if not ID_RE.fullmatch(value):
            parser.error(f"--{label} is invalid")
    if not SHA_RE.fullmatch(args.artifact_sha256):
        parser.error("--artifact-sha256 must be a sha256 reference")

    try:
        if args.artifact.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("export exceeds 32 MiB")
        before = sha_ref(args.artifact.read_bytes())
        if before != args.artifact_sha256:
            raise ValueError("artifact digest mismatch")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = popperpad_main(
                [
                    "--pad", str(args.pad),
                    "literature-import",
                    "--provider", args.provider,
                    "--input", str(args.artifact),
                ]
            )
        result = json.loads(output.getvalue())
        after = sha_ref(args.artifact.read_bytes())
        if code != 0 or result.get("ok") is not True:
            raise ValueError("PopperPad rejected the import")
        if before != after:
            raise ValueError("artifact changed during import")
        refs = [
            result["commit_root"],
            result["batch_ref"],
            result["raw_export_ref"],
            *result.get("candidate_refs", []),
            *result.get("relation_refs", []),
        ]
        if any(not isinstance(ref, str) or not SHA_RE.fullmatch(ref) for ref in refs):
            raise ValueError("PopperPad returned an invalid reference")
        value = make_receipt(
            importer_id=args.importer_id,
            import_id=args.import_id,
            provider=args.provider,
            artifact_sha256=args.artifact_sha256,
            status="PASS",
            external_refs=refs,
            detail=(
                f"Committed {len(result.get('candidate_refs', []))} candidates and "
                f"{len(result.get('relation_refs', []))} citation relations as triage-only objects."
            ),
        )
        exit_code = 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        value = make_receipt(
            importer_id=args.importer_id,
            import_id=args.import_id,
            provider=args.provider,
            artifact_sha256=args.artifact_sha256,
            status="FAIL",
            external_refs=[],
            detail=f"{type(exc).__name__}: import rejected",
        )
        exit_code = 2
    write_receipt(args.receipt, value)
    print(json.dumps(value, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
