from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ..schemas import (
    SCHEMA_DISCOVERY_BATCH_V1,
    SCHEMA_DISCOVERY_CANDIDATE_V1,
    SCHEMA_DISCOVERY_FAILURE_V1,
)

DISCOVERY_CANDIDATE_SCHEMA_V1 = SCHEMA_DISCOVERY_CANDIDATE_V1
DISCOVERY_BATCH_SCHEMA_V1 = SCHEMA_DISCOVERY_BATCH_V1
DISCOVERY_FAILURE_SCHEMA_V1 = SCHEMA_DISCOVERY_FAILURE_V1
DISCOVERY_AUTHORITY = "triage_only"
KURATE_PROVIDER = "kurate"
KURATE_BASE_URL = "https://kurate.org"
KURATE_MAX_LIMIT = 40
KURATE_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

KURATE_METRICS = (
    "score",
    "significance",
    "rigor",
    "novelty",
    "clarity",
    "difficulty",
    "surprisingness",
    "reproducibility",
    "translational_potential",
    "evidence_strength",
    "generalisability",
    "interdisciplinarity",
    "refutation_value",
    "replication_value",
    "resource_intensity",
    "foundationality",
)
KURATE_SORT_KEYS = frozenset((*KURATE_METRICS, "published"))
KURATE_SORT_DIRECTIONS = frozenset(("asc", "desc"))
DISCOVERY_NON_CLAIMS = (
    "Kurate assessments are discovery signals, not peer review.",
    "Discovery candidates do not support or refute PopperPad hypotheses.",
    "Primary-source review and independent checks remain required.",
)
DISCOVERY_FAILURE_NON_CLAIM = "No discovery candidate or truth evidence was produced."

_CATEGORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_DATE_RANGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ARXIV_ID_RE = re.compile(r"^[A-Za-z0-9._/-]{3,64}$")
_VERSION_SUFFIX_RE = re.compile(r"v[1-9][0-9]*$")
_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class KurateAdapterError(ValueError):
    """Typed, public-safe failure at the Kurate network boundary."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True)
class KurateBatch:
    request_uri: str
    query: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]
    raw_response: bytes
    raw_response_ref: str
    snapshot_ref: str


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
            raise KurateAdapterError("MALFORMED_RESPONSE", f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise KurateAdapterError("MALFORMED_RESPONSE", f"non-finite JSON number: {value}")


def _parse_json(raw: bytes) -> Mapping[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KurateAdapterError("MALFORMED_RESPONSE", "response is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except KurateAdapterError:
        raise
    except (json.JSONDecodeError, InvalidOperation, ValueError) as exc:
        raise KurateAdapterError("MALFORMED_RESPONSE", "response is not strict JSON") from exc
    if not isinstance(value, Mapping):
        raise KurateAdapterError("SCHEMA_DRIFT", "top-level response must be an object")
    return value


def _bounded_text(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KurateAdapterError("SCHEMA_DRIFT", f"{field} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise KurateAdapterError("SCHEMA_DRIFT", f"{field} exceeds {maximum} characters")
    return text


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: Iterable[str],
    label: str,
) -> None:
    expected = set(required)
    actual = {str(key) for key in value}
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        detail: list[str] = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise ValueError(f"{label} fields are invalid: {'; '.join(detail)}")


def _require_canonical_text(value: Any, field: str, *, maximum: int) -> str:
    text = _bounded_text(value, field, maximum=maximum)
    if text != value:
        raise ValueError(f"{field} must not contain leading or trailing whitespace")
    return text


def _validate_kurate_uri(value: Any, *, path: str, allow_query: bool) -> str:
    uri = _require_canonical_text(value, "Kurate URI", maximum=4096)
    parsed = urllib.parse.urlsplit(uri)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "kurate.org"
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.path != path
        or (not allow_query and parsed.query)
        or (allow_query and not parsed.query)
    ):
        raise ValueError("Kurate URI is outside the fixed adapter boundary")
    return uri


def _metric_milli(value: Any, metric: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise KurateAdapterError("SCHEMA_DRIFT", f"rating {metric} must be numeric or null")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise KurateAdapterError("SCHEMA_DRIFT", f"rating {metric} must be numeric or null") from exc
    if not number.is_finite() or number < 0 or number > 10:
        raise KurateAdapterError("SCHEMA_DRIFT", f"rating {metric} must be between 0 and 10")
    scaled = number * 1000
    if scaled != scaled.to_integral_value():
        raise KurateAdapterError("SCHEMA_DRIFT", f"rating {metric} has excessive precision")
    return int(scaled)


def _query_parameters(
    *,
    search: str,
    categories: Iterable[str],
    date_range: str,
    sort_key: str,
    sort_dir: str,
    limit: int,
    offset: int,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    search_text = str(search or "").strip()
    if len(search_text) > 256:
        raise KurateAdapterError("INVALID_REQUEST", "search exceeds 256 characters")
    category_values = sorted({str(item).strip() for item in categories if str(item).strip()})
    if len(category_values) > 16:
        raise KurateAdapterError("INVALID_REQUEST", "at most 16 categories may be requested")
    if any(not _CATEGORY_RE.fullmatch(item) for item in category_values):
        raise KurateAdapterError("INVALID_REQUEST", "category contains unsafe characters")
    date_value = str(date_range or "all").strip() or "all"
    if not _DATE_RANGE_RE.fullmatch(date_value):
        raise KurateAdapterError("INVALID_REQUEST", "date_range contains unsafe characters")
    sort_value = str(sort_key or "score").strip()
    if sort_value not in KURATE_SORT_KEYS:
        raise KurateAdapterError("INVALID_REQUEST", f"unsupported sort_key: {sort_value}")
    direction = str(sort_dir or "desc").strip().lower()
    if direction not in KURATE_SORT_DIRECTIONS:
        raise KurateAdapterError("INVALID_REQUEST", f"unsupported sort_dir: {direction}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= KURATE_MAX_LIMIT:
        raise KurateAdapterError("INVALID_REQUEST", f"limit must be between 1 and {KURATE_MAX_LIMIT}")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1_000_000:
        raise KurateAdapterError("INVALID_REQUEST", "offset must be between 0 and 1000000")
    params = [
        ("dataset", "live"),
        ("sort_key", sort_value),
        ("sort_dir", direction),
        ("offset", str(offset)),
        ("limit", str(limit)),
        ("include_categories", "false"),
        ("include_histograms", "false"),
    ]
    if date_value != "all":
        params.append(("date_range", date_value))
    if category_values:
        params.append(("cats", ",".join(category_values)))
    if search_text:
        params.append(("search", search_text))
    query = {
        "search": search_text,
        "categories": category_values,
        "date_range": date_value,
        "sort_key": sort_value,
        "sort_dir": direction,
        "limit": limit,
        "offset": offset,
    }
    return params, query


def _read_response(response: Any) -> bytes:
    status = getattr(response, "status", 200)
    if not isinstance(status, int) or status < 200 or status >= 300:
        raise KurateAdapterError("REMOTE_HTTP_ERROR", f"Kurate returned HTTP {status}")
    raw = response.read(KURATE_MAX_RESPONSE_BYTES + 1)
    if not isinstance(raw, bytes):
        raise KurateAdapterError("MALFORMED_RESPONSE", "response body must be bytes")
    if len(raw) > KURATE_MAX_RESPONSE_BYTES:
        raise KurateAdapterError("RESPONSE_TOO_LARGE", "Kurate response exceeded 4 MiB")
    return raw


def _fetch_bytes(
    request_uri: str,
    *,
    timeout_seconds: int,
    opener: Callable[..., Any] | None,
    user_agent: str,
) -> bytes:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
        raise KurateAdapterError("INVALID_REQUEST", "timeout_seconds must be between 1 and 60")
    request = urllib.request.Request(
        request_uri,
        headers={"Accept": "application/json", "User-Agent": user_agent},
        method="GET",
    )
    open_fn = opener or urllib.request.urlopen
    try:
        response = open_fn(request, timeout=timeout_seconds)
        with response:
            return _read_response(response)
    except KurateAdapterError:
        raise
    except urllib.error.HTTPError as exc:
        raise KurateAdapterError("REMOTE_HTTP_ERROR", f"Kurate returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise KurateAdapterError("REMOTE_UNAVAILABLE", "Kurate could not be reached") from exc


def _normalize_row(
    row: Any,
    *,
    request_uri: str,
    snapshot_ref: str,
    sort_key: str,
    sort_dir: str,
    position: int,
    base_url: str,
) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise KurateAdapterError("SCHEMA_DRIFT", "paper row must be an object")
    paper_id = _bounded_text(row.get("paper_id"), "paper_id", maximum=128)
    arxiv_id = _bounded_text(row.get("arxiv_id"), "arxiv_id", maximum=64)
    if not _ARXIV_ID_RE.fullmatch(arxiv_id):
        raise KurateAdapterError("SCHEMA_DRIFT", "arxiv_id contains unsafe characters")
    arxiv_base = _VERSION_SUFFIX_RE.sub("", arxiv_id)
    title = _bounded_text(row.get("title"), "title", maximum=10_000)
    published = _bounded_text(row.get("published"), "published", maximum=128)
    authors_raw = row.get("authors")
    categories_raw = row.get("categories")
    if not isinstance(authors_raw, list) or len(authors_raw) > 1024:
        raise KurateAdapterError("SCHEMA_DRIFT", "authors must be a bounded list")
    if not isinstance(categories_raw, list) or len(categories_raw) > 64:
        raise KurateAdapterError("SCHEMA_DRIFT", "categories must be a bounded list")
    authors = [_bounded_text(item, "author", maximum=512) for item in authors_raw]
    categories = [_bounded_text(item, "category", maximum=64) for item in categories_raw]
    if any(not _CATEGORY_RE.fullmatch(item) for item in categories):
        raise KurateAdapterError("SCHEMA_DRIFT", "paper category contains unsafe characters")
    primary_category = _bounded_text(row.get("category"), "category", maximum=64)
    if not _CATEGORY_RE.fullmatch(primary_category):
        raise KurateAdapterError("SCHEMA_DRIFT", "primary category contains unsafe characters")
    ratings_raw = row.get("ratings")
    if not isinstance(ratings_raw, Mapping):
        raise KurateAdapterError("SCHEMA_DRIFT", "ratings must be an object")
    unknown_metrics = sorted({str(key) for key in ratings_raw} - set(KURATE_METRICS))
    if unknown_metrics:
        raise KurateAdapterError("SCHEMA_DRIFT", f"unknown rating fields: {', '.join(unknown_metrics)}")
    metrics_milli = {metric: _metric_milli(ratings_raw.get(metric), metric) for metric in KURATE_METRICS}
    return {
        "schema": DISCOVERY_CANDIDATE_SCHEMA_V1,
        "provider": KURATE_PROVIDER,
        "authority": DISCOVERY_AUTHORITY,
        "candidate_key": f"kurate:{paper_id}:{arxiv_id}",
        "work_key": f"arxiv:{arxiv_base}",
        "paper": {
            "provider_id": paper_id,
            "arxiv_id": arxiv_id,
            "arxiv_id_base": arxiv_base,
            "title": title,
            "authors": authors,
            "primary_category": primary_category,
            "categories": categories,
            "published": published,
        },
        "assessment": {
            "metrics_milli": metrics_milli,
            "scale": {"minimum": 0, "maximum": 10_000, "unit": "milli_point"},
        },
        "provenance": {
            "paper_uri": f"{base_url}/paper/{urllib.parse.quote(paper_id, safe='')}",
            "api_uri": request_uri,
            "snapshot_ref": snapshot_ref,
        },
        "selection": {"sort_key": sort_key, "sort_dir": sort_dir, "position": position},
    }


def normalize_kurate_response(
    raw: bytes,
    *,
    request_uri: str,
    query: Mapping[str, Any],
    base_url: str = KURATE_BASE_URL,
) -> KurateBatch:
    payload = _parse_json(raw)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise KurateAdapterError("SCHEMA_DRIFT", "response rows must be a list")
    if len(rows) > int(query["limit"]):
        raise KurateAdapterError("SCHEMA_DRIFT", "response contains more rows than requested")
    semantic_snapshot = {"dataset": payload.get("dataset"), "total": payload.get("total"), "rows": rows}
    try:
        snapshot_ref = _sha256_ref(_canonical_bytes(semantic_snapshot))
    except (TypeError, ValueError) as exc:
        raise KurateAdapterError("MALFORMED_RESPONSE", "response contains non-canonical values") from exc
    candidates = tuple(
        _normalize_row(
            row,
            request_uri=request_uri,
            snapshot_ref=snapshot_ref,
            sort_key=str(query["sort_key"]),
            sort_dir=str(query["sort_dir"]),
            position=int(query["offset"]) + index,
            base_url=base_url,
        )
        for index, row in enumerate(rows)
    )
    candidate_keys = [str(candidate["candidate_key"]) for candidate in candidates]
    if len(set(candidate_keys)) != len(candidate_keys):
        raise KurateAdapterError("SCHEMA_DRIFT", "response contains duplicate paper candidates")
    return KurateBatch(
        request_uri=request_uri,
        query=dict(query),
        candidates=candidates,
        raw_response=bytes(raw),
        raw_response_ref=_sha256_ref(raw),
        snapshot_ref=snapshot_ref,
    )


def fetch_kurate_candidates(
    *,
    search: str = "",
    categories: Iterable[str] = (),
    date_range: str = "all",
    sort_key: str = "score",
    sort_dir: str = "desc",
    limit: int = 10,
    offset: int = 0,
    timeout_seconds: int = 20,
    opener: Callable[..., Any] | None = None,
    base_url: str = KURATE_BASE_URL,
    user_agent: str = "PopperPadKurateAdapter/1.0",
) -> KurateBatch:
    normalized_base = str(base_url or "").rstrip("/")
    parsed_base = urllib.parse.urlsplit(normalized_base)
    if parsed_base.scheme != "https" or parsed_base.netloc != "kurate.org" or parsed_base.username or parsed_base.password:
        raise KurateAdapterError("INVALID_REQUEST", "base_url must be https://kurate.org")
    params, query = _query_parameters(
        search=search,
        categories=categories,
        date_range=date_range,
        sort_key=sort_key,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    request_uri = f"{normalized_base}/api/papers-list?{urllib.parse.urlencode(params)}"
    raw = _fetch_bytes(request_uri, timeout_seconds=timeout_seconds, opener=opener, user_agent=user_agent)
    return normalize_kurate_response(raw, request_uri=request_uri, query=query, base_url=normalized_base)


def build_batch_object(batch: KurateBatch, *, candidate_refs: Sequence[str]) -> dict[str, Any]:
    refs = [str(ref) for ref in candidate_refs]
    if len(refs) != len(batch.candidates) or any(not _REF_RE.fullmatch(ref) for ref in refs):
        raise ValueError("candidate_refs must bind every candidate with sha256 refs")
    return {
        "schema": DISCOVERY_BATCH_SCHEMA_V1,
        "provider": KURATE_PROVIDER,
        "authority": DISCOVERY_AUTHORITY,
        "request": dict(batch.query),
        "request_uri": batch.request_uri,
        "snapshot_ref": batch.snapshot_ref,
        "raw_response_ref": batch.raw_response_ref,
        "candidate_refs": refs,
        "non_claims": list(DISCOVERY_NON_CLAIMS),
    }


def build_failure_object(*, request: Mapping[str, Any], code: str, detail: str) -> dict[str, Any]:
    return {
        "schema": DISCOVERY_FAILURE_SCHEMA_V1,
        "provider": KURATE_PROVIDER,
        "authority": DISCOVERY_AUTHORITY,
        "request": dict(request),
        "status": "UNKNOWN",
        "error": {"code": str(code), "detail": str(detail)},
        "non_claim": DISCOVERY_FAILURE_NON_CLAIM,
    }


def validate_discovery_candidate(candidate: Mapping[str, Any]) -> None:
    if candidate.get("schema") != DISCOVERY_CANDIDATE_SCHEMA_V1:
        raise ValueError("unsupported discovery candidate schema")
    if candidate.get("provider") != KURATE_PROVIDER or candidate.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("discovery candidate must be Kurate triage_only data")
    _require_exact_keys(
        candidate,
        required=(
            "schema",
            "provider",
            "authority",
            "candidate_key",
            "work_key",
            "paper",
            "assessment",
            "provenance",
            "selection",
        ),
        label="discovery candidate",
    )
    paper = candidate.get("paper")
    assessment = candidate.get("assessment")
    provenance = candidate.get("provenance")
    selection = candidate.get("selection")
    if not all(isinstance(item, Mapping) for item in (paper, assessment, provenance, selection)):
        raise ValueError("discovery candidate sections must be objects")
    _require_exact_keys(
        paper,
        required=(
            "provider_id",
            "arxiv_id",
            "arxiv_id_base",
            "title",
            "authors",
            "primary_category",
            "categories",
            "published",
        ),
        label="discovery candidate paper",
    )
    paper_id = _require_canonical_text(paper.get("provider_id"), "paper.provider_id", maximum=128)
    arxiv_id = _require_canonical_text(paper.get("arxiv_id"), "paper.arxiv_id", maximum=64)
    if not _ARXIV_ID_RE.fullmatch(arxiv_id):
        raise ValueError("paper.arxiv_id is invalid")
    arxiv_base = _VERSION_SUFFIX_RE.sub("", arxiv_id)
    if paper.get("arxiv_id_base") != arxiv_base:
        raise ValueError("paper.arxiv_id_base does not match paper.arxiv_id")
    _require_canonical_text(paper.get("title"), "paper.title", maximum=10_000)
    _require_canonical_text(paper.get("published"), "paper.published", maximum=128)
    authors = paper.get("authors")
    categories = paper.get("categories")
    if not isinstance(authors, list) or len(authors) > 1024:
        raise ValueError("paper.authors must be a bounded list")
    if not isinstance(categories, list) or len(categories) > 64:
        raise ValueError("paper.categories must be a bounded list")
    for author in authors:
        _require_canonical_text(author, "paper.author", maximum=512)
    for category in categories:
        category_text = _require_canonical_text(category, "paper.category", maximum=64)
        if not _CATEGORY_RE.fullmatch(category_text):
            raise ValueError("paper.category is invalid")
    primary = _require_canonical_text(
        paper.get("primary_category"), "paper.primary_category", maximum=64
    )
    if not _CATEGORY_RE.fullmatch(primary):
        raise ValueError("paper.primary_category is invalid")
    if candidate.get("candidate_key") != f"kurate:{paper_id}:{arxiv_id}":
        raise ValueError("candidate_key does not match the paper identity")
    if candidate.get("work_key") != f"arxiv:{arxiv_base}":
        raise ValueError("work_key does not match the paper identity")

    _require_exact_keys(assessment, required=("metrics_milli", "scale"), label="assessment")
    metrics = assessment.get("metrics_milli")
    if not isinstance(metrics, Mapping) or set(metrics) != set(KURATE_METRICS):
        raise ValueError("discovery candidate metrics are incomplete")
    for key, value in metrics.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000):
            raise ValueError(f"discovery candidate metric {key} is invalid")
    scale = assessment.get("scale")
    if scale != {"minimum": 0, "maximum": 10_000, "unit": "milli_point"}:
        raise ValueError("discovery candidate scale is invalid")

    _require_exact_keys(
        provenance,
        required=("paper_uri", "api_uri", "snapshot_ref"),
        label="provenance",
    )
    expected_paper_path = "/paper/" + urllib.parse.quote(paper_id, safe="")
    _validate_kurate_uri(provenance.get("paper_uri"), path=expected_paper_path, allow_query=False)
    _validate_kurate_uri(provenance.get("api_uri"), path="/api/papers-list", allow_query=True)
    if not _REF_RE.fullmatch(str(provenance.get("snapshot_ref", ""))):
        raise ValueError("discovery candidate snapshot_ref is invalid")

    _require_exact_keys(selection, required=("sort_key", "sort_dir", "position"), label="selection")
    if selection.get("sort_key") not in KURATE_SORT_KEYS:
        raise ValueError("discovery candidate sort_key is invalid")
    if selection.get("sort_dir") not in KURATE_SORT_DIRECTIONS:
        raise ValueError("discovery candidate sort_dir is invalid")
    position = selection.get("position")
    if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= 1_000_040:
        raise ValueError("discovery candidate position is invalid")
    _canonical_bytes(candidate)


def validate_discovery_batch(batch: Mapping[str, Any]) -> None:
    if batch.get("schema") != DISCOVERY_BATCH_SCHEMA_V1:
        raise ValueError("unsupported discovery batch schema")
    if batch.get("provider") != KURATE_PROVIDER or batch.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("discovery batch must be Kurate triage_only data")
    _require_exact_keys(
        batch,
        required=(
            "schema",
            "provider",
            "authority",
            "request",
            "request_uri",
            "snapshot_ref",
            "raw_response_ref",
            "candidate_refs",
            "non_claims",
        ),
        label="discovery batch",
    )
    if not _REF_RE.fullmatch(str(batch.get("snapshot_ref", ""))):
        raise ValueError("discovery batch snapshot_ref is invalid")
    if not _REF_RE.fullmatch(str(batch.get("raw_response_ref", ""))):
        raise ValueError("discovery batch raw_response_ref is invalid")
    refs = batch.get("candidate_refs")
    if (
        not isinstance(refs, list)
        or len(refs) > KURATE_MAX_LIMIT
        or len({str(ref) for ref in refs}) != len(refs)
        or any(not _REF_RE.fullmatch(str(ref)) for ref in refs)
    ):
        raise ValueError("discovery batch candidate_refs are invalid")
    request = batch.get("request")
    if not isinstance(request, Mapping) or not isinstance(batch.get("non_claims"), list):
        raise ValueError("discovery batch request and non_claims are required")
    _require_exact_keys(
        request,
        required=("search", "categories", "date_range", "sort_key", "sort_dir", "limit", "offset"),
        label="discovery request",
    )
    params, normalized_query = _query_parameters(
        search=request.get("search", ""),
        categories=request.get("categories", ()),
        date_range=request.get("date_range", "all"),
        sort_key=request.get("sort_key", "score"),
        sort_dir=request.get("sort_dir", "desc"),
        limit=request.get("limit", 0),
        offset=request.get("offset", -1),
    )
    if dict(request) != normalized_query:
        raise ValueError("discovery request is not canonical")
    expected_uri = f"{KURATE_BASE_URL}/api/papers-list?{urllib.parse.urlencode(params)}"
    if batch.get("request_uri") != expected_uri:
        raise ValueError("discovery batch request_uri does not match its request")
    if len(refs) > int(request["limit"]):
        raise ValueError("discovery batch has more candidates than requested")
    if tuple(batch.get("non_claims", ())) != DISCOVERY_NON_CLAIMS:
        raise ValueError("discovery batch non_claims are invalid")
    _canonical_bytes(batch)


def validate_discovery_failure(failure: Mapping[str, Any]) -> None:
    if failure.get("schema") != DISCOVERY_FAILURE_SCHEMA_V1:
        raise ValueError("unsupported discovery failure schema")
    if failure.get("provider") != KURATE_PROVIDER or failure.get("authority") != DISCOVERY_AUTHORITY:
        raise ValueError("discovery failure must be Kurate triage_only data")
    _require_exact_keys(
        failure,
        required=("schema", "provider", "authority", "request", "status", "error", "non_claim"),
        label="discovery failure",
    )
    if failure.get("status") != "UNKNOWN":
        raise ValueError("discovery failure status must be UNKNOWN")
    request = failure.get("request")
    if not isinstance(request, Mapping) or not isinstance(failure.get("error"), Mapping):
        raise ValueError("discovery failure request and error are required")
    _require_exact_keys(
        request,
        required=("search", "categories", "date_range", "sort_key", "sort_dir", "limit", "offset"),
        label="failed discovery request",
    )
    search = request.get("search")
    categories = request.get("categories")
    if not isinstance(search, str) or len(search) > 2048:
        raise ValueError("failed discovery request search is invalid")
    if (
        not isinstance(categories, list)
        or len(categories) > 64
        or any(not isinstance(item, str) or len(item) > 256 for item in categories)
    ):
        raise ValueError("failed discovery request categories are invalid")
    for key in ("date_range", "sort_key", "sort_dir"):
        value = request.get(key)
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError(f"failed discovery request {key} is invalid")
    for key in ("limit", "offset"):
        value = request.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not -(2**31) <= value < 2**31:
            raise ValueError(f"failed discovery request {key} is invalid")
    _require_exact_keys(failure["error"], required=("code", "detail"), label="discovery failure error")
    _bounded_text(failure["error"].get("code"), "error.code", maximum=128)
    _bounded_text(failure["error"].get("detail"), "error.detail", maximum=1024)
    if failure.get("non_claim") != DISCOVERY_FAILURE_NON_CLAIM:
        raise ValueError("discovery failure non_claim is invalid")
    _canonical_bytes(failure)


__all__ = [
    "DISCOVERY_AUTHORITY",
    "DISCOVERY_BATCH_SCHEMA_V1",
    "DISCOVERY_CANDIDATE_SCHEMA_V1",
    "DISCOVERY_FAILURE_SCHEMA_V1",
    "DISCOVERY_NON_CLAIMS",
    "KURATE_METRICS",
    "KurateAdapterError",
    "KurateBatch",
    "build_batch_object",
    "build_failure_object",
    "fetch_kurate_candidates",
    "normalize_kurate_response",
    "validate_discovery_batch",
    "validate_discovery_candidate",
    "validate_discovery_failure",
]
