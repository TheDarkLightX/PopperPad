"""Bounded single-slot falsification-market profile loader.

This module loads the immutable profile data from the checked-in JSON file
and constructs a ``MarketAdapterProfile`` value. The profile data is data,
not hard-coded module globals.
"""

from __future__ import annotations

import json
from pathlib import Path

from ...core.adapter_protocol import MarketAdapterProfile
from ...core.values import FrozenDict, freeze_json


_PROFILE_JSON_PATH = Path(__file__).parent / "market_single_slot_v1.json"


def load_profile() -> MarketAdapterProfile:
    """Load and construct the single-slot market adapter profile from JSON."""

    raw = json.loads(_PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    return _build_profile(raw)


def _build_profile(raw: dict) -> MarketAdapterProfile:
    return MarketAdapterProfile(
        schema=raw["schema"],
        profile_id=raw["profile_id"],
        profile_version=raw["profile_version"],
        protocol_version=raw["protocol_version"],
        abstraction_id=raw["abstraction_id"],
        codec_version=raw["codec_version"],
        bounty_terms_json=_freeze(raw["bounty_terms"]),
        market_policy_json=_freeze(raw["market_policy"]),
        identity_aliases=_freeze(raw["identity_aliases"]),
        time_representatives=_freeze(raw["time_representatives"]),
        numeric_bounds=_freeze(raw["numeric_bounds"]),
        cardinality_bounds=_freeze(raw["cardinality_bounds"]),
        allowed_abstract_commands=frozenset(raw["allowed_abstract_commands"]),
        expected_rejection_precedence=tuple(raw["expected_rejection_precedence"]),
        source_manifest_hash=raw["source_manifest_hash"],
        model_ir_hash=raw["model_ir_hash"],
        explicit_nonclaims=tuple(raw["explicit_nonclaims"]),
    )


def _freeze(value: object) -> FrozenDict:
    result = freeze_json(value)
    if not isinstance(result, FrozenDict):
        raise TypeError(f"expected JSON object, got {type(value).__name__}")
    return result
