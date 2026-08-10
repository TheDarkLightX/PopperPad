from __future__ import annotations

import hashlib
import json
from pathlib import Path

from popperpad.literature_importer import RECEIPT_SCHEMA, run
from popperpad.pad import PopperPad


def mosaic_export() -> bytes:
    return json.dumps(
        {
            "status": "ok",
            "query": "checked abstraction",
            "count": 1,
            "papers": [
                {
                    "uid": "doi:10.1234/adapter",
                    "title": "Checked abstraction",
                    "authors": ["A. Author"],
                    "year": 2026,
                    "doi": "10.1234/adapter",
                    "source": "OpenAlex",
                    "is_open_access": True,
                    "relevance_score": 0.9,
                }
            ],
            "errors": [],
        },
        separators=(",", ":"),
    ).encode()


def args(tmp_path: Path, artifact: Path, digest: str) -> list[str]:
    return [
        "--pad", str(tmp_path / "pad"),
        "--artifact", str(artifact),
        "--artifact-sha256", digest,
        "--provider", "mosaic",
        "--receipt", str(tmp_path / "receipt.json"),
        "--import-id", "mosaic-broad",
        "--importer-id", "popperpad",
    ]


def test_importer_binds_export_and_commits_triage_objects(tmp_path: Path) -> None:
    artifact = tmp_path / "export.json"
    raw = mosaic_export()
    artifact.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()

    assert run(args(tmp_path, artifact, digest)) == 0
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["status"] == "PASS"
    assert receipt["authority"] == "triage_only"
    assert receipt["artifact_sha256"] == digest
    assert receipt["external_refs"]
    assert PopperPad(root=tmp_path / "pad").doctor(strict=True).ok


def test_importer_rejects_digest_mismatch_without_pad_records(tmp_path: Path) -> None:
    artifact = tmp_path / "export.json"
    artifact.write_bytes(mosaic_export())

    assert run(args(tmp_path, artifact, "sha256:" + "0" * 64)) == 2
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["external_refs"] == []
    assert not (tmp_path / "pad").exists()
