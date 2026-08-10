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
from .literature import (
    LITERATURE_BATCH_SCHEMA_V1,
    LITERATURE_CANDIDATE_SCHEMA_V1,
    LITERATURE_FAILURE_SCHEMA_V1,
    LITERATURE_RELATION_SCHEMA_V1,
    LiteratureAdapterError,
    LiteratureBatch,
    normalize_literature_export,
)
from .literature import (
    build_batch_object as build_literature_batch_object,
)
from .literature import (
    build_failure_object as build_literature_failure_object,
)

__all__ = [
    "DISCOVERY_AUTHORITY",
    "DISCOVERY_BATCH_SCHEMA_V1",
    "DISCOVERY_CANDIDATE_SCHEMA_V1",
    "DISCOVERY_FAILURE_SCHEMA_V1",
    "LITERATURE_BATCH_SCHEMA_V1",
    "LITERATURE_CANDIDATE_SCHEMA_V1",
    "LITERATURE_FAILURE_SCHEMA_V1",
    "LITERATURE_RELATION_SCHEMA_V1",
    "KurateAdapterError",
    "KurateBatch",
    "LiteratureAdapterError",
    "LiteratureBatch",
    "build_batch_object",
    "build_failure_object",
    "build_literature_batch_object",
    "build_literature_failure_object",
    "fetch_kurate_candidates",
    "normalize_literature_export",
]
