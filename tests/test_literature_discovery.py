from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from popperpad.cli import main
from popperpad.discovery.literature import (
    LiteratureAdapterError,
    normalize_literature_export,
)
from popperpad.pad import PopperPad
from popperpad.refs import ValidationError
from popperpad.schemas import (
    SCHEMA_LITERATURE_BATCH_V1,
    SCHEMA_LITERATURE_CANDIDATE_V1,
    SCHEMA_LITERATURE_FAILURE_V1,
    SCHEMA_LITERATURE_RELATION_V1,
)


def _citracer_payload() -> dict:
    return {
        "metadata": {"retrieval_policy": {"kind": "lawful_open_access_only"}},
        "nodes": [
            {
                "id": "doi:10.1234/root",
                "title": "Root paper",
                "authors": ["A. Author"],
                "year": 2025,
                "doi": "10.1234/root",
                "status": "root",
                "depth": 0,
                "keyword_hits": ["projection operator"],
            },
            {
                "id": "arxiv:2608.00001v2",
                "title": "Cited paper",
                "authors": ["B. Author"],
                "year": 2026,
                "arxiv_id": "2608.00001v2",
                "status": "analyzed",
                "depth": 1,
                "keyword_hits": [],
            },
        ],
        "edges": [
            {
                "source": "doi:10.1234/root",
                "target": "arxiv:2608.00001v2",
                "type": "primary",
                "depth": 1,
                "context": "Root cites the result.",
            }
        ],
    }


def _mosaic_payload() -> dict:
    return {
        "status": "ok",
        "query": "projection operator",
        "count": 1,
        "papers": [
            {
                "uid": "doi:10.5678/example",
                "title": "A MOSAIC result",
                "authors": ["C. Author"],
                "year": 2024,
                "doi": "10.5678/Example",
                "source": "OpenAlex",
                "is_open_access": True,
                "relevance_score": 0.8125,
            }
        ],
        "errors": ["One optional source timed out"],
    }


def test_normalizers_preserve_policy_relations_and_negative_knowledge() -> None:
    citracer = normalize_literature_export(
        json.dumps(_citracer_payload()).encode(),
        provider="citracer",
    )
    assert len(citracer.candidates) == 2
    assert len(citracer.relations) == 1
    assert citracer.candidates[0]["provenance"]["retrieval_policy_kind"] == "lawful_open_access_only"
    assert citracer.candidates[0]["context"]["is_new"] is None
    assert citracer.relations[0]["target_work_key"] == "arxiv:2608.00001"

    mosaic = normalize_literature_export(
        json.dumps(_mosaic_payload()).encode(),
        provider="mosaic",
    )
    assert mosaic.candidates[0]["context"]["relevance_decimal"] == "0.8125"
    assert mosaic.warnings == ("One optional source timed out",)


def test_shared_candidate_contract_matches_research_kernel_golden_digest() -> None:
    raw = json.dumps(
        {
            "status": "ok",
            "query": "projection",
            "count": 1,
            "papers": [{
                "uid": "doi:10.1234/x",
                "title": "Shared fixture",
                "authors": ["A"],
                "year": 2026,
                "doi": "10.1234/X",
                "source": "OpenAlex",
                "is_open_access": True,
                "relevance_score": 0.75,
            }],
            "errors": [],
        },
        separators=(",", ":"),
    ).encode()
    candidate = normalize_literature_export(raw, provider="mosaic").candidates[0]
    semantic = json.dumps(
        candidate,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    assert hashlib.sha256(semantic).hexdigest() == (
        "98eb90f01d292968f95ffb6228d14544312bdcbaa3fa1ea57e279425da26a0af"
    )


def test_cli_commits_exact_citracer_batch_atomically(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pad_root = tmp_path / "pad"
    export = tmp_path / "trace.json"
    raw = json.dumps(_citracer_payload(), separators=(",", ":")).encode()
    export.write_bytes(raw)

    assert main([
        "literature-import",
        "--pad", str(pad_root),
        "--provider", "citracer",
        "--input", str(export),
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert len(output["candidate_refs"]) == 2
    assert len(output["relation_refs"]) == 1

    pad = PopperPad(root=pad_root)
    candidate = pad.get_object(output["candidate_refs"][0])
    relation = pad.get_object(output["relation_refs"][0])
    batch = pad.get_object(output["batch_ref"])
    assert candidate["schema"] == SCHEMA_LITERATURE_CANDIDATE_V1
    assert relation["schema"] == SCHEMA_LITERATURE_RELATION_V1
    assert batch["schema"] == SCHEMA_LITERATURE_BATCH_V1
    assert pad.get_blob(output["raw_export_ref"]) == raw
    assert pad.doctor(strict=True).ok

    with pytest.raises(ValidationError, match="not a hypothesis"):
        pad.status(output["candidate_refs"][0], context_ref=None)


def test_cli_preserves_mosaic_partial_failure_in_batch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pad_root = tmp_path / "pad"
    export = tmp_path / "search.json"
    export.write_text(json.dumps(_mosaic_payload()), encoding="utf-8")

    assert main([
        "--pad", str(pad_root),
        "literature-import",
        "--provider", "mosaic",
        "--input", str(export),
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    batch = PopperPad(root=pad_root).get_object(output["batch_ref"])
    assert batch["warnings"] == ["One optional source timed out"]


def test_schema_drift_commits_only_unknown_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _citracer_payload()
    payload["edges"][0]["target"] = "doi:10.9999/missing"
    export = tmp_path / "broken.json"
    export.write_text(json.dumps(payload), encoding="utf-8")
    pad_root = tmp_path / "pad"

    assert main([
        "literature-import",
        "--pad", str(pad_root),
        "--provider", "citracer",
        "--input", str(export),
    ]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "UNKNOWN"
    pad = PopperPad(root=pad_root)
    failure = pad.get_object(output["failure_ref"])
    assert failure["schema"] == SCHEMA_LITERATURE_FAILURE_V1
    assert list(pad.log.iter_raw_records())
    assert pad.doctor(strict=True).ok


def test_duplicate_json_keys_are_rejected() -> None:
    with pytest.raises(LiteratureAdapterError, match="duplicate JSON key"):
        normalize_literature_export(
            b'{"status":"ok","papers":[],"papers":[],"errors":[]}',
            provider="mosaic",
        )


def test_unreadable_input_commits_unknown_without_local_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "private-layout" / "missing.json"
    pad_root = tmp_path / "pad"

    assert main([
        "literature-import",
        "--pad", str(pad_root),
        "--provider", "mosaic",
        "--input", str(missing),
    ]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "UNKNOWN"
    assert output["error"]["code"] == "READ_FAILED"
    assert str(tmp_path) not in json.dumps(output)

    failure = PopperPad(root=pad_root).get_object(output["failure_ref"])
    assert failure["source_name"] == "missing.json"
    assert str(tmp_path) not in json.dumps(failure)
