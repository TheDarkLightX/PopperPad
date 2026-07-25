"""Bounded single-slot falsification-market profile loader.

Loads the immutable profile data from the checked-in JSON file and constructs
a generic ``DataAdapterProfile`` with the market-specific data in the
``semantic_profile`` payload. Also loads the source manifest and constructs
the ``AdapterBinding`` from JSON metadata files.

No hash constants are hardcoded — all hashes are computed at runtime from
the loaded JSON files. This avoids the chicken-and-egg problem where a
hardcoded manifest hash in the loader would change the loader's own hash,
invalidating the manifest.

At load time, the following invariants are verified:
  manifest.profile_hash == loaded profile hash
  binding.profile_hash == loaded profile hash
  binding.source_manifest_hash == loaded manifest hash

If any invariant fails, the loader raises — fail-closed behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    BINDING_SCHEMA,
    PROFILE_SCHEMA,
    SOURCE_MANIFEST_SCHEMA,
    AdapterBinding,
    DataAdapterProfile,
    SourceFileBinding,
    SourceManifest,
)
from ...core.values import FrozenDict, freeze_json


_PROFILE_JSON_PATH = Path(__file__).parent / "market_single_slot_v1.json"
_SOURCE_MANIFEST_PATH = Path(__file__).resolve().parents[4] / "formal" / "manifests" / "market_single_slot_v1.sources.json"


def load_profile() -> DataAdapterProfile:
    """Load and construct the single-slot market adapter profile from JSON."""

    raw = json.loads(_PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    semantic = freeze_json(raw)
    assert isinstance(semantic, FrozenDict)
    return DataAdapterProfile(
        schema=PROFILE_SCHEMA,
        profile_id="popperpad.falsification-market.single-slot.v1",
        profile_version="1",
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        abstraction_id="popperpad.falsification-market.single-slot.v1",
        codec_version="popperpad-json-int-v2",
        semantic_profile=semantic,
        explicit_nonclaims=(
            "arbitrary_market_cardinality",
            "chain_or_token_refinement",
            "production_datastore_linearizability",
            "unbounded_liveness_or_fairness",
            "verifier_semantic_correctness",
        ),
    )


def load_source_manifest(profile: DataAdapterProfile | None = None) -> SourceManifest:
    """Load the source manifest from the checked-in JSON file.

    Verifies that manifest.profile_hash matches the loaded profile hash.
    """

    if profile is None:
        profile = load_profile()
    raw = json.loads(_SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    files = tuple(
        SourceFileBinding(path=f["path"], sha256=f["sha256"])
        for f in raw["files"]
    )
    manifest = SourceManifest(
        schema=SOURCE_MANIFEST_SCHEMA,
        repository=raw["repository"],
        commit=raw["commit"],
        files=files,
        profile_hash=raw["profile_hash"],
        codec_version=raw["codec_version"],
    )
    # Verify manifest.profile_hash matches the loaded profile hash
    if manifest.profile_hash != profile.hash():
        raise ValueError(
            f"source manifest profile_hash {manifest.profile_hash} "
            f"does not match loaded profile hash {profile.hash()}"
        )
    return manifest


def load_binding(
    profile: DataAdapterProfile | None = None,
    manifest: SourceManifest | None = None,
) -> AdapterBinding:
    """Construct the adapter binding from the profile and source manifest.

    Verifies that binding.profile_hash matches the loaded profile hash and
    binding.source_manifest_hash matches the loaded manifest hash.

    Hashes are computed at runtime — no hardcoded constants.
    """

    if profile is None:
        profile = load_profile()
    if manifest is None:
        manifest = load_source_manifest(profile)
    # Verify manifest.profile_hash matches the loaded profile hash
    if manifest.profile_hash != profile.hash():
        raise ValueError(
            f"source manifest profile_hash {manifest.profile_hash} "
            f"does not match loaded profile hash {profile.hash()}"
        )
    binding = AdapterBinding(
        schema=BINDING_SCHEMA,
        profile_hash=profile.hash(),
        source_manifest_hash=manifest.hash(),
        model_ir_hash=None,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        adapter_implementation_id="popperpad.refinement.market_adapter",
    )
    # Verify binding consistency
    if binding.profile_hash != profile.hash():
        raise ValueError("binding profile_hash does not match loaded profile hash")
    if binding.source_manifest_hash != manifest.hash():
        raise ValueError("binding source_manifest_hash does not match loaded manifest hash")
    return binding
