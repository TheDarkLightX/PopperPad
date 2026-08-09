"""Discovery adapters emit triage-only objects, never truth evidence."""

from .kurate import (
    DISCOVERY_AUTHORITY,
    DISCOVERY_BATCH_SCHEMA_V1,
    DISCOVERY_CANDIDATE_SCHEMA_V1,
    DISCOVERY_FAILURE_SCHEMA_V1,
    KurateAdapterError,
    KurateBatch,
    build_batch_object,
    build_failure_object,
    fetch_kurate_candidates,
)

__all__ = [
    "DISCOVERY_AUTHORITY",
    "DISCOVERY_BATCH_SCHEMA_V1",
    "DISCOVERY_CANDIDATE_SCHEMA_V1",
    "DISCOVERY_FAILURE_SCHEMA_V1",
    "KurateAdapterError",
    "KurateBatch",
    "build_batch_object",
    "build_failure_object",
    "fetch_kurate_candidates",
]
