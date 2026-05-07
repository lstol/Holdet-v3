"""Export the Giro 2026 rider universe to the local dashboard artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.ingest.rider_loader import (
    RACE_ID,
    compare_snapshot_holdet_ids,
    load_rider_universe,
    write_dashboard_rider_artifact,
)


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run(repo_root: Path, race_id: str = RACE_ID) -> dict[str, Any]:
    universe = load_rider_universe(repo_root, race_id)
    artifact_path = write_dashboard_rider_artifact(repo_root, universe)
    snapshot_path = repo_root / "shared" / "data" / "snapshots" / "stage_1_holdet.json"
    snapshot = _load_optional_json(snapshot_path)
    snapshot_comparison = compare_snapshot_holdet_ids(universe, snapshot) if snapshot else None
    return {
        "artifact_path": str(artifact_path),
        "summary": universe.summary,
        "validation": universe.validation,
        "snapshot_comparison": snapshot_comparison,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Giro 2026 riders for the ChatGPT dashboard.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root. Defaults to Holdet-v3 root from chatgpt/src/ingest/.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(json.dumps(run(args.repo_root), indent=2, sort_keys=True))

