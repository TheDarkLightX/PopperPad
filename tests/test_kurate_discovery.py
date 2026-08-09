from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import popperpad.cli as cli_module
from popperpad.cli import main
from popperpad.discovery.kurate import (
    KURATE_METRICS,
    KurateAdapterError,
    build_batch_object,
    fetch_kurate_candidates,
    normalize_kurate_response,
)
from popperpad.pad import PopperPad
from popperpad.refs import ValidationError
from popperpad.schemas import (
    SCHEMA_DISCOVERY_BATCH_V1,
    SCHEMA_DISCOVERY_CANDIDATE_V1,
    SCHEMA_DISCOVERY_FAILURE_V1,
)
from popperpad.validate import validate_object


def _row(
    *,
    paper_id: str = "6404916f-e61d-4fb7-bc59-eb518ab326e5",
    score: float = 8.5,
    novelty: float | None = 7.5,
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "title": "A bounded discovery result",
        "category": "cs.AI",
        "categories": ["cs.AI", "cs.LG"],
        "authors": ["Ada Researcher"],
        "published": "2026-08-09T00:00:00Z",
        "arxiv_id": "2608.01234v1",
        "ratings": {
            "score": score,
            "significance": 8,
            "rigor": 9,
            "novelty": novelty,
            "clarity": 8.5,
        },
    }


def _raw(rows: list[dict[str, Any]] | None = None) -> bytes:
    selected = [_row()] if rows is None else rows
    return json.dumps(
        {"dataset": "live", "total": len(selected), "timing_ms": 3.14159, "rows": selected},
        separators=(",", ":"),
    ).encode("utf-8")


def _query(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "search": "bounded",
        "categories": ["cs.AI"],
        "date_range": "30d",
        "sort_key": "novelty",
        "sort_dir": "desc",
        "limit": 10,
        "offset": 0,
    }
    value.update(overrides)
    return value


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, _limit: int) -> bytes:
        return self.payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_float(child) for child in value)
    return False


def _batch() -> Any:
    return normalize_kurate_response(
        _raw(),
        request_uri=(
            "https://kurate.org/api/papers-list?dataset=live&sort_key=novelty&sort_dir=desc"
            "&offset=0&limit=10&include_categories=false&include_histograms=false"
            "&date_range=30d&cats=cs.AI&search=bounded"
        ),
        query=_query(),
    )


def test_fetch_is_bounded_and_normalizes_scores_without_floats() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Any, *, timeout: int) -> _Response:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["accept"] = request.headers["Accept"]
        return _Response(_raw())

    batch = fetch_kurate_candidates(
        search="projection operator",
        categories=["math.AG", "cs.AI"],
        date_range="30d",
        sort_key="novelty",
        sort_dir="desc",
        limit=5,
        offset=2,
        timeout_seconds=7,
        opener=opener,
    )

    assert seen["timeout"] == 7
    assert seen["accept"] == "application/json"
    assert "search=projection+operator" in seen["url"]
    assert "cats=cs.AI%2Cmath.AG" in seen["url"]
    candidate = batch.candidates[0]
    assert candidate["schema"] == SCHEMA_DISCOVERY_CANDIDATE_V1
    assert candidate["authority"] == "triage_only"
    assert candidate["paper"]["arxiv_id_base"] == "2608.01234"
    assert candidate["assessment"]["metrics_milli"]["score"] == 8500
    assert candidate["assessment"]["metrics_milli"]["novelty"] == 7500
    assert set(candidate["assessment"]["metrics_milli"]) == set(KURATE_METRICS)
    assert candidate["assessment"]["metrics_milli"]["refutation_value"] is None
    assert candidate["selection"]["position"] == 2
    assert not _contains_float(candidate)
    validate_object(candidate)


def test_shared_candidate_contract_matches_research_kernel_golden_digest() -> None:
    row = {
        "paper_id": "p-1",
        "title": "Shared fixture",
        "category": "math.LO",
        "categories": ["math.LO"],
        "authors": ["A"],
        "published": "2026-08-09",
        "arxiv_id": "2608.00001v2",
        "ratings": {"score": 8.125, "novelty": None},
    }
    candidate = normalize_kurate_response(
        _raw([row]),
        request_uri=(
            "https://kurate.org/api/papers-list?dataset=live&sort_key=score&sort_dir=desc"
            "&offset=0&limit=1&include_categories=false&include_histograms=false"
        ),
        query=_query(
            search="",
            categories=[],
            date_range="all",
            sort_key="score",
            limit=1,
        ),
    ).candidates[0]
    semantic_bytes = json.dumps(
        candidate,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert hashlib.sha256(semantic_bytes).hexdigest() == (
        "c05efe9b6a9bf8a8782d398051b3bf321d88e249df5a140e0a7fce1df2c8b896"
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"limit": 41}, "limit"),
        ({"sort_key": "unknown"}, "sort_key"),
        ({"categories": ["cs.AI&admin=true"]}, "category"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"base_url": "https://example.com"}, "base_url"),
    ),
)
def test_invalid_request_fails_before_network(kwargs: dict[str, Any], message: str) -> None:
    def opener(*_args: object, **_kwargs: object) -> _Response:
        raise AssertionError("network must not be reached")

    with pytest.raises(KurateAdapterError, match=message):
        fetch_kurate_candidates(opener=opener, **kwargs)


def test_schema_drift_duplicate_keys_metrics_and_candidates_are_quarantined() -> None:
    duplicate_key = b'{"rows":[],"rows":[],"dataset":"live","total":0}'
    with pytest.raises(KurateAdapterError, match="duplicate JSON key"):
        normalize_kurate_response(
            duplicate_key,
            request_uri="https://kurate.org/api/papers-list?limit=1",
            query=_query(limit=1),
        )

    unknown = _row()
    unknown["ratings"]["future_metric"] = 8
    with pytest.raises(KurateAdapterError, match="unknown rating fields"):
        normalize_kurate_response(
            _raw([unknown]),
            request_uri="https://kurate.org/api/papers-list?limit=10",
            query=_query(),
        )

    with pytest.raises(KurateAdapterError, match="between 0 and 10"):
        normalize_kurate_response(
            _raw([_row(score=11)]),
            request_uri="https://kurate.org/api/papers-list?limit=10",
            query=_query(),
        )

    with pytest.raises(KurateAdapterError, match="duplicate paper candidates"):
        normalize_kurate_response(
            _raw([_row(), _row()]),
            request_uri="https://kurate.org/api/papers-list?limit=10",
            query=_query(),
        )


def test_candidate_and_batch_receipts_are_strictly_validated() -> None:
    batch = _batch()
    candidate = batch.candidates[0]
    candidate_ref = "sha256:" + "a" * 64
    batch_object = build_batch_object(batch, candidate_refs=(candidate_ref,))

    validate_object(candidate)
    validate_object(batch_object)
    assert batch_object["schema"] == SCHEMA_DISCOVERY_BATCH_V1

    altered = dict(candidate)
    altered["evidence_refs"] = []
    with pytest.raises(ValidationError, match="unknown evidence_refs"):
        validate_object(altered)

    asserted = dict(batch_object)
    asserted["non_claims"] = ["These scores prove the paper is correct."]
    with pytest.raises(ValidationError, match="non_claims"):
        validate_object(asserted)


def test_cli_commits_candidates_batch_and_raw_response_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    batch = _batch()
    monkeypatch.setattr(cli_module, "fetch_kurate_candidates", lambda **_kwargs: batch)
    root = tmp_path / "pad"

    assert main(["--pad", str(root), "kurate-discover", "--search", "bounded"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["provider"] == "kurate"
    assert output["authority"] == "triage_only"
    assert len(output["candidate_refs"]) == 1

    pad = PopperPad(root=root)
    raw_records = list(pad.log.iter_raw_records())
    logical_records = list(pad.log.iter_records())
    assert len(raw_records) == 1
    assert [record["op"] for record in logical_records] == [
        "add_object",
        "add_object",
        "add_blob",
    ]
    candidate = pad.get_object(output["candidate_refs"][0])
    batch_object = pad.get_object(output["batch_ref"])
    assert candidate["schema"] == SCHEMA_DISCOVERY_CANDIDATE_V1
    assert batch_object["candidate_refs"] == output["candidate_refs"]
    assert pad.get_blob(output["raw_response_ref"]) == batch.raw_response
    assert pad.doctor(strict=True).ok

    with pytest.raises(ValidationError, match="not a hypothesis"):
        pad.status(output["candidate_refs"][0], context_ref=None)


def test_cli_records_remote_failure_as_unknown_negative_knowledge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(**_kwargs: Any) -> Any:
        raise KurateAdapterError("REMOTE_UNAVAILABLE", "Kurate could not be reached")

    monkeypatch.setattr(cli_module, "fetch_kurate_candidates", fail)
    root = tmp_path / "pad"

    assert main(["kurate-discover", "--pad", str(root), "--limit", "1"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["status"] == "UNKNOWN"

    pad = PopperPad(root=root)
    records = list(pad.log.iter_records())
    assert len(records) == 1
    failure = pad.get_object(output["failure_ref"])
    assert failure["schema"] == SCHEMA_DISCOVERY_FAILURE_V1
    assert failure["status"] == "UNKNOWN"
    assert failure["non_claim"] == "No discovery candidate or truth evidence was produced."
    assert pad.doctor(strict=True).ok
