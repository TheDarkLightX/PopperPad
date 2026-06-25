from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from .schemas import SCHEMA_GAMIFICATION_SCORE_EVENT_V1
from .validate import validate_object


def aggregate_score_events(
    events: Iterable[Mapping[str, Any]],
    *,
    point_kind: str | None = None,
    domain_ref: str | None = None,
    event_kinds: set[str] | None = None,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """
    Derive a deterministic leaderboard from append-only score events.

    Invalid events raise by default. In non-strict mode, invalid or non-score
    objects are skipped so a public index can keep rendering while surfacing
    validation failures elsewhere.
    """
    totals: dict[tuple[str, str, str | None], int] = defaultdict(int)
    counts: dict[tuple[str, str, str | None], int] = defaultdict(int)

    for event in events:
        if event.get("schema") != SCHEMA_GAMIFICATION_SCORE_EVENT_V1:
            if strict:
                raise ValueError("expected score event")
            continue

        try:
            validate_object(event)
        except ValueError:
            if strict:
                raise
            continue

        if point_kind is not None and event.get("point_kind") != point_kind:
            continue
        if domain_ref is not None and event.get("domain_ref") != domain_ref:
            continue
        if event_kinds is not None and event.get("event_kind") not in event_kinds:
            continue

        key = (str(event["agent_ref"]), str(event["point_kind"]), event.get("domain_ref"))
        totals[key] += int(event["point_delta"])
        counts[key] += 1

    rows = [
        {
            "agent_ref": agent_ref,
            "point_kind": kind,
            "domain_ref": domain,
            "points": points,
            "event_count": counts[(agent_ref, kind, domain)],
        }
        for (agent_ref, kind, domain), points in totals.items()
    ]
    rows.sort(key=lambda r: (-int(r["points"]), str(r["agent_ref"]), str(r["point_kind"]), str(r.get("domain_ref"))))
    return rows
