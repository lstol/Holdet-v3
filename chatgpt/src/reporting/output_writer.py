"""Write ChatGPT stage outputs under chatgpt/output/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def output_path(repo_root: Path, stage_number: int) -> Path:
    return repo_root / "chatgpt" / "output" / f"stage_{stage_number}_chatgpt.json"


def write_stage_output(repo_root: Path, stage_number: int, payload: dict[str, Any]) -> Path:
    path = output_path(repo_root, stage_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched_payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage_number": stage_number,
        **payload,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(enriched_payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path

