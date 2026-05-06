"""Record local intel-source assumptions without writing to shared/."""

from __future__ import annotations

from typing import Any


def summarize_intel_inputs(odds: dict[str, Any], expert_intel: dict[str, Any]) -> dict[str, Any]:
    """Produce a compact, auditable summary for output files."""
    return {
        "odds_status": odds.get("status", "unknown"),
        "expert_intel_status": expert_intel.get("status", "unknown"),
        "assumptions": [
            *odds.get("assumptions", []),
            *expert_intel.get("assumptions", []),
        ],
    }

