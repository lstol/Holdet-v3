"""Local ChatGPT odds and expert-intel ingestion stubs."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_odds_inputs(config: dict[str, Any]) -> dict[str, Any]:
    """Return manually supplied odds inputs when available.

    Bookmaker odds are intentionally not read from shared/. Each system gathers
    and freezes its own odds/intel inputs independently.
    """
    odds_path = config.get("odds_input_path")
    if not odds_path:
        return {"status": "stub", "rider_odds": [], "assumptions": ["No odds input configured."]}

    path = Path(odds_path)
    return {
        "status": "not_implemented",
        "path": str(path),
        "rider_odds": [],
        "assumptions": ["Odds file parsing will be added once the input format is chosen."],
    }


def load_expert_intel(config: dict[str, Any]) -> dict[str, Any]:
    """Return manually supplied expert intel when available."""
    intel_path = config.get("expert_intel_path")
    if not intel_path:
        return {"status": "stub", "signals": [], "assumptions": ["No expert intel configured."]}

    path = Path(intel_path)
    return {
        "status": "not_implemented",
        "path": str(path),
        "signals": [],
        "assumptions": ["Expert intel parsing will stay local to chatgpt/."],
    }

