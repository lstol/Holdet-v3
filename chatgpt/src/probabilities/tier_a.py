"""Tier-A rider classification stub."""

from __future__ import annotations

from typing import Any


def classify_tier_a(snapshot: dict[str, Any], odds: dict[str, Any], expert_intel: dict[str, Any]) -> dict[str, Any]:
    """Return the initial Tier-A classification placeholder.

    Tier A should eventually contain the 20-30 riders with non-trivial stage
    win, podium, top-10, or top-15 relevance for the specific stage scenario.
    """
    return {
        "status": "stub",
        "riders": [],
        "assumptions": [
            "Tier-A classification requires stage-specific odds and expert signals.",
            "No historical priors are used.",
        ],
        "stage_metadata_seen": bool(snapshot.get("stage_metadata")),
        "odds_rows_seen": len(odds.get("rider_odds", [])),
        "expert_signals_seen": len(expert_intel.get("signals", [])),
    }

