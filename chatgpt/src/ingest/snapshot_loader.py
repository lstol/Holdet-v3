"""Load frozen Holdet stage snapshots from shared read-only inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_SNAPSHOT_KEYS = {
    "holdet_ids",
    "current_prices",
    "is_out",
    "post_stage_results",
    "jersey_holders",
    "gc_standings",
    "team_composition",
    "bank_balance",
    "stage_metadata",
}


def snapshot_path(repo_root: Path, stage_number: int) -> Path:
    """Return the canonical shared snapshot path for a stage."""
    return repo_root / "shared" / "data" / "snapshots" / f"stage_{stage_number}_snapshot.json"


def load_snapshot(repo_root: Path, stage_number: int) -> dict[str, Any]:
    """Load and lightly validate a frozen shared stage snapshot."""
    path = snapshot_path(repo_root, stage_number)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing snapshot for stage {stage_number}: {path}. "
            "Expected shared/data/snapshots/stage_N_snapshot.json."
        )

    with path.open("r", encoding="utf-8") as handle:
        snapshot = json.load(handle)

    missing = sorted(REQUIRED_SNAPSHOT_KEYS - set(snapshot))
    if missing:
        raise ValueError(f"Snapshot {path} is missing required keys: {missing}")

    return snapshot

