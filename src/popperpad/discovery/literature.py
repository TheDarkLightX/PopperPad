from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

LITERATURE_CANDIDATE_SCHEMA_V1 = "research-discovery/literature-candidate/v1"
LITERATURE_RELATION_SCHEMA_V1 = "research-discovery/literature-relation/v1"
LITERATURE_BATCH_SCHEMA_V1 = "research-discovery/literature-batch/v1"
LITERATURE_FAILURE_SCHEMA_V1 = "research-discovery/literature-failure/v1"
DISCOVERY_AUTHORITY = "triage_only"
SUPPORTED_PROVIDERS = frozenset({"citracer", "mosaic"})
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_CANDIDATES = 10_000
MAX_RELATIONS = 100_000

_ARXIV_VERSION_RE = re.compile(r"v[1-9][0-9]*$", re.IGNORECASE)
_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY_RE = re.compile(r"^(citracer|mosaic):[0-9a-f]{64}$")
LITERATURE_NON_CLAIMS = (
    "Search ranking and citation parsing are discovery signals, not peer review.",
    "No literature-import object is truth evidence or claim support.",
    "Primary-source review and independent checks remain required.",
)
LITERATURE_FAILURE_NON_CLAIM = "No discovery candidate or truth evidence was produced."


class LiteratureAdapterError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True)
class LiteratureBatch:
    provider: str
    candidates: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    raw_export: bytes
    raw_export_ref: str
    snapshot_ref: str
    source_path: str


def _sha256_ref(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"$decimal": format(value, "f")}
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(child) for child in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise LiteratureAdapterError("MALFORMED_EXPORT", f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise LiteratureAdapterError("MALFORMED_EXPORT", f"non-finite JSON number: {value}")


def _parse_json(raw: bytes) -> Mapping[str, Any]:
    if len(raw) > MAX_EXPORT_BYTES:
        raise LiteratureAdapterError("EXPORT_TOO_LARGE", "export exceeds 32 MiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiteratureAdapterError("MALFORMED_EXPORT", "export is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except LiteratureAdapterError:
        raise
    except (json.JSONDecodeError, InvalidOperation, ValueError) as exc:
        raise LiteratureAdapterError("MALFORMED_EXPORT", "export is not strict JSON") from exc
    if not isinstance(value, Mapping):
        raise LiteratureAdapterError("SCHEMA_DRIFT", "top-level export must be an object")
    return value


def _text(value: Any, field: str, *, maximum: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} is required")
        return None
    if not isinstance(value, str):
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} must be a string or null")
    text = value.strip()
    if required and not text:
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} is required")
    if len(text) > maximum:
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} exceeds {maximum} characters")
    return text or None


def _integer(value: Any, field: str, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} must be an integer or null")
    if not minimum <= value <= maximum:
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} is out of range")
    return value


def _boolean(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} must be a boolean or null")
    return value


def _strings(value: Any, field: str, *, maximum_items: int, maximum_text: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum_items:
        raise LiteratureAdapterError(
            "SCHEMA_DRIFT", f"{field} must be an array of at most {maximum_items} strings"
        )
    result: list[str] = []
    for index, item in enumerate(value):
        text = _text(item, f"{field}[{index}]", maximum=maximum_text, required=True)
        assert text is not None
        result.append(text)
    return result


def _normalize_doi(value: Any) -> str | None:
    text = _text(value, "doi", maximum=512)
    if not text:
        return None
    lowered = text.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):]
            break
    return lowered or None


def _normalize_arxiv(value: Any) -> str | None:
    text = _text(value, "arxiv_id", maximum=128)
    if not text:
        return None
    lowered = text.strip()
    for prefix in ("https://arxiv.org/abs/", "https://arxiv.org/pdf/", "arxiv:"):
        if lowered.lower().startswith(prefix):
            lowered = lowered[len(prefix):]
            break
    if lowered.lower().endswith(".pdf"):
        lowered = lowered[:-4]
    return lowered or None


def _work_key(*, doi: str | None, arxiv_id: str | None, title: str) -> str:
    if doi:
        return f"doi:{doi}"
    if arxiv_id:
        return "arxiv:" + _ARXIV_VERSION_RE.sub("", arxiv_id.lower())
    digest = hashlib.sha256(title.casefold().encode("utf-8")).hexdigest()[:32]
    return f"title:{digest}"


def _source_uri(*, doi: str | None, arxiv_id: str | None, url: str | None) -> str | None:
    if url and url.startswith(("https://", "http://")):
        return url
    if doi:
        return f"https://doi.org/{doi}"
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return None


def _paper(record: Mapping[str, Any], *, provider_id: str) -> tuple[dict[str, Any], str]:
    title = _text(record.get("title"), "title", maximum=10_000, required=True)
    assert title is not None
    doi = _normalize_doi(record.get("doi"))
    arxiv_id = _normalize_arxiv(record.get("arxiv_id"))
    url = _text(record.get("url"), "url", maximum=4_096)
    paper = {
        "provider_id": provider_id,
        "title": title,
        "authors": _strings(record.get("authors"), "authors", maximum_items=1_024, maximum_text=512),
        "year": _integer(record.get("year"), "year", minimum=0, maximum=9_999),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "abstract": _text(record.get("abstract"), "abstract", maximum=200_000),
        "journal": _text(record.get("journal"), "journal", maximum=2_000),
        "citation_count": _integer(
            record.get("citation_count"), "citation_count", minimum=0, maximum=2_147_483_647
        ),
        "url": url,
        "source_uri": _source_uri(doi=doi, arxiv_id=arxiv_id, url=url),
    }
    return paper, _work_key(doi=doi, arxiv_id=arxiv_id, title=title)


def _candidate(
    *,
    provider: str,
    provider_id: str,
    record: Mapping[str, Any],
    context: dict[str, Any],
    snapshot_ref: str,
    input_format: str,
    retrieval_policy_kind: str,
) -> dict[str, Any]:
    paper, work_key = _paper(record, provider_id=provider_id)
    record_ref = _sha256_ref(_canonical_bytes(record))
    candidate_key = f"{provider}:{record_ref.removeprefix('sha256:')}"
    return {
        "schema": LITERATURE_CANDIDATE_SCHEMA_V1,
        "provider": provider,
        "authority": DISCOVERY_AUTHORITY,
        "candidate_key": candidate_key,
        "work_key": work_key,
        "paper": paper,
        "context": context,
        "provenance": {
            "snapshot_ref": snapshot_ref,
            "record_ref": record_ref,
            "input_format": input_format,
            "retrieval_policy_kind": retrieval_policy_kind,
        },
    }


def _normalize_citracer(payload: Mapping[str, Any], snapshot_ref: str) -> tuple[list[dict], list[dict], list[str]]:
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise LiteratureAdapterError("SCHEMA_DRIFT", "citracer export requires nodes and edges arrays")
    if len(nodes) > MAX_CANDIDATES or len(edges) > MAX_RELATIONS:
        raise LiteratureAdapterError("EXPORT_TOO_LARGE", "citracer graph exceeds bounded item limits")

    metadata = payload.get("metadata")
    policy_kind = "unspecified"
    if isinstance(metadata, Mapping):
        policy = metadata.get("retrieval_policy")
        if isinstance(policy, Mapping):
            value = _text(policy.get("kind"), "retrieval_policy.kind", maximum=128)
            if value:
                policy_kind = value

    candidates: list[dict] = []
    work_by_id: dict[str, str] = {}
    for index, raw_node in enumerate(nodes):
        if not isinstance(raw_node, Mapping):
            raise LiteratureAdapterError("SCHEMA_DRIFT", f"nodes[{index}] must be an object")
        provider_id = _text(raw_node.get("id"), f"nodes[{index}].id", maximum=512, required=True)
        assert provider_id is not None
        if provider_id in work_by_id:
            raise LiteratureAdapterError("SCHEMA_DRIFT", f"duplicate citracer node id: {provider_id}")
        context = {
            "status": _text(raw_node.get("status"), "status", maximum=64),
            "depth": _integer(raw_node.get("depth"), "depth", minimum=0, maximum=10_000),
            "publication_date": _text(raw_node.get("publication_date"), "publication_date", maximum=128),
            "keyword_hits": _strings(
                raw_node.get("keyword_hits"), "keyword_hits", maximum_items=10_000, maximum_text=20_000
            ),
            "is_new": _boolean(raw_node.get("is_new"), "is_new"),
        }
        candidate = _candidate(
            provider="citracer",
            provider_id=provider_id,
            record=raw_node,
            context=context,
            snapshot_ref=snapshot_ref,
            input_format="citracer-json/v1",
            retrieval_policy_kind=policy_kind,
        )
        work_by_id[provider_id] = candidate["work_key"]
        candidates.append(candidate)

    relations: list[dict] = []
    relation_keys: set[str] = set()
    for index, raw_edge in enumerate(edges):
        if not isinstance(raw_edge, Mapping):
            raise LiteratureAdapterError("SCHEMA_DRIFT", f"edges[{index}] must be an object")
        source_id = _text(raw_edge.get("source"), "edge.source", maximum=512, required=True)
        target_id = _text(raw_edge.get("target"), "edge.target", maximum=512, required=True)
        assert source_id is not None and target_id is not None
        if source_id not in work_by_id or target_id not in work_by_id:
            raise LiteratureAdapterError("SCHEMA_DRIFT", "citracer edge references an unknown node")
        edge_type = _text(raw_edge.get("type"), "edge.type", maximum=64, required=True)
        assert edge_type is not None
        semantic = {
            "source_work_key": work_by_id[source_id],
            "target_work_key": work_by_id[target_id],
            "relation_type": "cites",
            "parser_edge_type": edge_type,
            "depth": _integer(raw_edge.get("depth"), "edge.depth", minimum=0, maximum=10_000),
            "context": _text(raw_edge.get("context"), "edge.context", maximum=100_000),
            "snapshot_ref": snapshot_ref,
        }
        relation_ref = _sha256_ref(_canonical_bytes(semantic))
        relation_key = "citracer:" + relation_ref.removeprefix("sha256:")
        if relation_key in relation_keys:
            continue
        relation_keys.add(relation_key)
        relations.append(
            {
                "schema": LITERATURE_RELATION_SCHEMA_V1,
                "provider": "citracer",
                "authority": DISCOVERY_AUTHORITY,
                "relation_key": relation_key,
                **semantic,
            }
        )
    return candidates, relations, []


def _decimal_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} must be numeric or null")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} must be numeric or null") from exc
    if not number.is_finite():
        raise LiteratureAdapterError("SCHEMA_DRIFT", f"{field} must be finite")
    return format(number, "f")


def _normalize_mosaic(payload: Mapping[str, Any], snapshot_ref: str) -> tuple[list[dict], list[dict], list[str]]:
    if payload.get("status") != "ok":
        raise LiteratureAdapterError("REMOTE_UNKNOWN", "MOSAIC export status is not ok")
    papers = payload.get("papers")
    if not isinstance(papers, list) or len(papers) > MAX_CANDIDATES:
        raise LiteratureAdapterError("SCHEMA_DRIFT", "MOSAIC export requires a bounded papers array")
    warnings = _strings(payload.get("errors"), "errors", maximum_items=1_000, maximum_text=10_000)
    query = _text(payload.get("query"), "query", maximum=10_000)

    candidates: list[dict] = []
    seen: set[str] = set()
    for index, raw_paper in enumerate(papers):
        if not isinstance(raw_paper, Mapping):
            raise LiteratureAdapterError("SCHEMA_DRIFT", f"papers[{index}] must be an object")
        provider_id = _text(raw_paper.get("uid"), f"papers[{index}].uid", maximum=512)
        if not provider_id:
            provider_id = f"row:{index}"
        context = {
            "query": query,
            "source": _text(raw_paper.get("source"), "source", maximum=512),
            "is_open_access": _boolean(raw_paper.get("is_open_access"), "is_open_access"),
            "pdf_url": _text(raw_paper.get("pdf_url"), "pdf_url", maximum=4_096),
            "relevance_decimal": _decimal_text(raw_paper.get("relevance_score"), "relevance_score"),
        }
        candidate = _candidate(
            provider="mosaic",
            provider_id=provider_id,
            record=raw_paper,
            context=context,
            snapshot_ref=snapshot_ref,
            input_format="mosaic-search-json/v1",
            retrieval_policy_kind="provider_reported",
        )
        if candidate["candidate_key"] in seen:
            continue
        seen.add(candidate["candidate_key"])
        candidates.append(candidate)
    return candidates, [], warnings


def normalize_literature_export(
    raw: bytes,
    *,
    provider: str,
    source_path: str = "",
) -> LiteratureBatch:
    provider_name = str(provider or "").strip().lower()
    if provider_name not in SUPPORTED_PROVIDERS:
        raise LiteratureAdapterError("INVALID_REQUEST", f"unsupported provider: {provider_name}")
    payload = _parse_json(raw)
    snapshot_ref = _sha256_ref(raw)
    if provider_name == "citracer":
        candidates, relations, warnings = _normalize_citracer(payload, snapshot_ref)
    else:
        candidates, relations, warnings = _normalize_mosaic(payload, snapshot_ref)
    return LiteratureBatch(
        provider=provider_name,
        candidates=tuple(candidates),
        relations=tuple(relations),
        warnings=tuple(warnings),
        raw_export=bytes(raw),
        raw_export_ref=snapshot_ref,
        snapshot_ref=snapshot_ref,
        source_path=Path(source_path).name if source_path else "",
    )


def candidate_receipt_ref(candidate: Mapping[str, Any]) -> str:
    validate_literature_candidate(candidate)
    return _sha256_ref(_canonical_bytes(candidate))


def build_batch_object(
    batch: LiteratureBatch,
    *,
    candidate_refs: Sequence[str],
    relation_refs: Sequence[str],
) -> dict[str, Any]:
    candidates = [str(ref) for ref in candidate_refs]
    relations = [str(ref) for ref in relation_refs]
    if len(candidates) != len(batch.candidates) or any(not _REF_RE.fullmatch(ref) for ref in candidates):
        raise ValueError("candidate_refs must bind every candidate with sha256 refs")
    if len(relations) != len(batch.relations) or any(not _REF_RE.fullmatch(ref) for ref in relations):
        raise ValueError("relation_refs must bind every relation with sha256 refs")
    return {
        "schema": LITERATURE_BATCH_SCHEMA_V1,
        "provider": batch.provider,
        "authority": DISCOVERY_AUTHORITY,
        "snapshot_ref": batch.snapshot_ref,
        "raw_export_ref": batch.raw_export_ref,
        "source_name": batch.source_path,
        "candidate_refs": candidates,
        "relation_refs": relations,
        "warnings": list(batch.warnings),
        "non_claims": list(LITERATURE_NON_CLAIMS),
    }


def build_failure_object(
    *,
    provider: str,
    source_name: str,
    code: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "schema": LITERATURE_FAILURE_SCHEMA_V1,
        "provider": str(provider or "").strip().lower(),
        "authority": DISCOVERY_AUTHORITY,
        "source_name": Path(source_name).name,
        "status": "UNKNOWN",
        "error": {"code": str(code), "detail": str(detail)},
        "non_claim": LITERATURE_FAILURE_NON_CLAIM,
    }


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields are not canonical")


def _require_ref(value: Any, label: str) -> str:
    text = str(value or "")
    if not _REF_RE.fullmatch(text):
        raise ValueError(f"{label} must be a sha256 ref")
    return text


def validate_literature_candidate(candidate: Mapping[str, Any]) -> None:
    if candidate.get("schema") != LITERATURE_CANDIDATE_SCHEMA_V1:
        raise ValueError("unsupported literature candidate schema")
    provider = candidate.get("provider")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("unsupported literature candidate provider")
    if candidate.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("literature candidate must be triage_only")
    _exact_keys(
        candidate,
        {"schema", "provider", "authority", "candidate_key", "work_key", "paper", "context", "provenance"},
        "literature candidate",
    )
    if not _KEY_RE.fullmatch(str(candidate.get("candidate_key", ""))):
        raise ValueError("literature candidate key is invalid")
    work_key = candidate.get("work_key")
    if not isinstance(work_key, str) or not work_key or len(work_key) > 600:
        raise ValueError("literature work key is invalid")
    paper = candidate.get("paper")
    context = candidate.get("context")
    provenance = candidate.get("provenance")
    if not all(isinstance(item, Mapping) for item in (paper, context, provenance)):
        raise ValueError("literature candidate sections must be objects")
    _exact_keys(
        paper,
        {
            "provider_id", "title", "authors", "year", "doi", "arxiv_id", "abstract",
            "journal", "citation_count", "url", "source_uri",
        },
        "literature paper",
    )
    _text(paper.get("provider_id"), "paper.provider_id", maximum=512, required=True)
    _text(paper.get("title"), "paper.title", maximum=10_000, required=True)
    _strings(paper.get("authors"), "paper.authors", maximum_items=1_024, maximum_text=512)
    _integer(paper.get("year"), "paper.year", minimum=0, maximum=9_999)
    _integer(paper.get("citation_count"), "paper.citation_count", minimum=0, maximum=2_147_483_647)
    for key, maximum in (("doi", 512), ("arxiv_id", 128), ("abstract", 200_000), ("journal", 2_000), ("url", 4_096), ("source_uri", 4_096)):
        _text(paper.get(key), f"paper.{key}", maximum=maximum)
    if _work_key(
        doi=_normalize_doi(paper.get("doi")),
        arxiv_id=_normalize_arxiv(paper.get("arxiv_id")),
        title=str(paper["title"]),
    ) != work_key:
        raise ValueError("literature work key does not match paper identity")

    expected_context = (
        {"status", "depth", "publication_date", "keyword_hits", "is_new"}
        if provider == "citracer"
        else {"query", "source", "is_open_access", "pdf_url", "relevance_decimal"}
    )
    _exact_keys(context, expected_context, "literature context")
    if provider == "citracer":
        _text(context.get("status"), "context.status", maximum=64)
        _integer(context.get("depth"), "context.depth", minimum=0, maximum=10_000)
        _text(context.get("publication_date"), "context.publication_date", maximum=128)
        _strings(context.get("keyword_hits"), "context.keyword_hits", maximum_items=10_000, maximum_text=20_000)
        _boolean(context.get("is_new"), "context.is_new")
    else:
        _text(context.get("query"), "context.query", maximum=10_000)
        _text(context.get("source"), "context.source", maximum=512)
        _boolean(context.get("is_open_access"), "context.is_open_access")
        _text(context.get("pdf_url"), "context.pdf_url", maximum=4_096)
        relevance = context.get("relevance_decimal")
        if relevance is not None and _decimal_text(relevance, "context.relevance_decimal") != relevance:
            raise ValueError("context.relevance_decimal is not canonical")

    _exact_keys(
        provenance,
        {"snapshot_ref", "record_ref", "input_format", "retrieval_policy_kind"},
        "literature provenance",
    )
    _require_ref(provenance.get("snapshot_ref"), "provenance.snapshot_ref")
    _require_ref(provenance.get("record_ref"), "provenance.record_ref")
    _text(provenance.get("input_format"), "provenance.input_format", maximum=128, required=True)
    _text(
        provenance.get("retrieval_policy_kind"),
        "provenance.retrieval_policy_kind",
        maximum=128,
        required=True,
    )
    _canonical_bytes(candidate)


def validate_literature_relation(relation: Mapping[str, Any]) -> None:
    if relation.get("schema") != LITERATURE_RELATION_SCHEMA_V1:
        raise ValueError("unsupported literature relation schema")
    if relation.get("provider") != "citracer" or relation.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("literature relation must be citracer triage_only data")
    _exact_keys(
        relation,
        {
            "schema", "provider", "authority", "relation_key", "source_work_key",
            "target_work_key", "relation_type", "parser_edge_type", "depth", "context",
            "snapshot_ref",
        },
        "literature relation",
    )
    if not _KEY_RE.fullmatch(str(relation.get("relation_key", ""))):
        raise ValueError("literature relation key is invalid")
    for key, maximum in (("source_work_key", 600), ("target_work_key", 600), ("parser_edge_type", 64)):
        _text(relation.get(key), f"relation.{key}", maximum=maximum, required=True)
    if relation.get("relation_type") != "cites":
        raise ValueError("unsupported literature relation type")
    _integer(relation.get("depth"), "relation.depth", minimum=0, maximum=10_000)
    _text(relation.get("context"), "relation.context", maximum=100_000)
    _require_ref(relation.get("snapshot_ref"), "relation.snapshot_ref")
    _canonical_bytes(relation)


def validate_literature_batch(batch: Mapping[str, Any]) -> None:
    if batch.get("schema") != LITERATURE_BATCH_SCHEMA_V1:
        raise ValueError("unsupported literature batch schema")
    if batch.get("provider") not in SUPPORTED_PROVIDERS or batch.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("literature batch must be supported triage_only data")
    _exact_keys(
        batch,
        {
            "schema", "provider", "authority", "snapshot_ref", "raw_export_ref",
            "source_name", "candidate_refs", "relation_refs", "warnings", "non_claims",
        },
        "literature batch",
    )
    snapshot = _require_ref(batch.get("snapshot_ref"), "batch.snapshot_ref")
    if _require_ref(batch.get("raw_export_ref"), "batch.raw_export_ref") != snapshot:
        raise ValueError("literature raw export and snapshot refs differ")
    _text(batch.get("source_name"), "batch.source_name", maximum=512)
    for key, maximum in (("candidate_refs", MAX_CANDIDATES), ("relation_refs", MAX_RELATIONS)):
        refs = batch.get(key)
        if not isinstance(refs, list) or len(refs) > maximum or len(set(refs)) != len(refs):
            raise ValueError(f"literature {key} is invalid")
        for ref in refs:
            _require_ref(ref, key)
    _strings(batch.get("warnings"), "batch.warnings", maximum_items=1_000, maximum_text=10_000)
    if tuple(batch.get("non_claims", ())) != LITERATURE_NON_CLAIMS:
        raise ValueError("literature batch non_claims are invalid")
    _canonical_bytes(batch)


def validate_literature_failure(failure: Mapping[str, Any]) -> None:
    if failure.get("schema") != LITERATURE_FAILURE_SCHEMA_V1:
        raise ValueError("unsupported literature failure schema")
    if failure.get("provider") not in SUPPORTED_PROVIDERS or failure.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("literature failure must be supported triage_only data")
    _exact_keys(
        failure,
        {"schema", "provider", "authority", "source_name", "status", "error", "non_claim"},
        "literature failure",
    )
    _text(failure.get("source_name"), "failure.source_name", maximum=512)
    if failure.get("status") != "UNKNOWN" or failure.get("non_claim") != LITERATURE_FAILURE_NON_CLAIM:
        raise ValueError("literature failure status or non_claim is invalid")
    error = failure.get("error")
    if not isinstance(error, Mapping):
        raise ValueError("literature failure error is missing")
    _exact_keys(error, {"code", "detail"}, "literature failure error")
    _text(error.get("code"), "error.code", maximum=128, required=True)
    _text(error.get("detail"), "error.detail", maximum=2_000, required=True)
    _canonical_bytes(failure)


__all__ = [
    "DISCOVERY_AUTHORITY",
    "LITERATURE_BATCH_SCHEMA_V1",
    "LITERATURE_CANDIDATE_SCHEMA_V1",
    "LITERATURE_FAILURE_SCHEMA_V1",
    "LITERATURE_RELATION_SCHEMA_V1",
    "MAX_EXPORT_BYTES",
    "LiteratureAdapterError",
    "LiteratureBatch",
    "build_batch_object",
    "build_failure_object",
    "candidate_receipt_ref",
    "normalize_literature_export",
    "validate_literature_batch",
    "validate_literature_candidate",
    "validate_literature_failure",
    "validate_literature_relation",
]
