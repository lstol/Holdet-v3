"""Explicit Giro 2026 rider-universe loader for ChatGPT-owned workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any


RACE_ID = "giro_2026"
RIDER_FILE_NAME = "riders.json"


@dataclass(frozen=True)
class RiderUniverse:
    race_id: str
    source_path: Path
    riders: list[dict[str, Any]]
    summary: dict[str, Any]
    validation: dict[str, Any]
    detected_schema: dict[str, Any]


def rider_universe_path(repo_root: Path, race_id: str = RACE_ID) -> Path:
    """Return the authoritative shared rider universe path for Giro 2026."""
    if race_id != RACE_ID:
        raise ValueError(f"Unsupported race_id {race_id!r}; this loader is intentionally Giro-only.")
    return repo_root / "shared" / "data" / "riders" / race_id / RIDER_FILE_NAME


def load_rider_universe(repo_root: Path, race_id: str = RACE_ID) -> RiderUniverse:
    """Load, normalize, validate, and summarize the Giro 2026 rider universe."""
    path = rider_universe_path(repo_root, race_id)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_riders = _extract_raw_riders(payload, path)
    riders = [_normalize_rider(raw) for raw in raw_riders]
    validation = validate_riders(riders)
    summary = summarize_riders(riders)
    detected_schema = {
        "top_level_type": type(payload).__name__,
        "top_level_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        "rider_container": "riders",
        "raw_rider_count": len(raw_riders),
        "sample_rider_keys": sorted(raw_riders[0].keys()) if raw_riders else [],
        "id_field": "holdet_id",
        "name_field": "name",
        "team_field": "team",
        "price_field": "price",
        "team_code_field": "team_code if present; otherwise null",
    }

    return RiderUniverse(
        race_id=race_id,
        source_path=path,
        riders=riders,
        summary=summary,
        validation=validation,
        detected_schema=detected_schema,
    )


def validate_riders(riders: list[dict[str, Any]]) -> dict[str, Any]:
    """Return validation findings without mutating rider records."""
    seen: dict[int, int] = {}
    missing_ids: list[int] = []
    duplicate_ids: list[int] = []
    missing_names: list[int] = []
    invalid_prices: list[int] = []

    for index, rider in enumerate(riders):
        holdet_id = rider.get("holdet_id")
        if holdet_id is None:
            missing_ids.append(index)
        elif holdet_id in seen:
            duplicate_ids.append(holdet_id)
        else:
            seen[holdet_id] = index

        if not rider.get("name"):
            missing_names.append(index)

        price = rider.get("price")
        if not isinstance(price, int) or price <= 0:
            invalid_prices.append(index)

    errors = {
        "duplicate_ids": sorted(set(duplicate_ids)),
        "missing_id_rows": missing_ids,
        "missing_name_rows": missing_names,
        "invalid_price_rows": invalid_prices,
    }
    return {
        **errors,
        "is_valid": not any(errors.values()),
    }


def summarize_riders(riders: list[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic summary stats for the normalized rider universe."""
    prices = sorted(rider["price"] for rider in riders if isinstance(rider.get("price"), int))
    teams = sorted({rider["team"] for rider in riders if rider.get("team")})
    return {
        "rider_count": len(riders),
        "team_count": len(teams),
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "median_price": int(median(prices)) if prices else None,
    }


def compare_snapshot_holdet_ids(
    rider_universe: RiderUniverse | list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare snapshot Holdet IDs against the normalized rider universe."""
    riders = rider_universe.riders if isinstance(rider_universe, RiderUniverse) else rider_universe
    universe_ids = {rider["holdet_id"] for rider in riders if rider.get("holdet_id") is not None}
    snapshot_ids = _snapshot_holdet_ids(snapshot)
    missing_from_snapshot = sorted(universe_ids - snapshot_ids)
    missing_from_universe = sorted(snapshot_ids - universe_ids)
    return {
        "universe_count": len(universe_ids),
        "snapshot_count": len(snapshot_ids),
        "missing_from_snapshot": missing_from_snapshot,
        "missing_from_universe": missing_from_universe,
        "is_match": not missing_from_snapshot and not missing_from_universe,
    }


def to_dashboard_payload(universe: RiderUniverse) -> dict[str, Any]:
    """Return the local dashboard data artifact payload."""
    return {
        "race_id": universe.race_id,
        "source": str(universe.source_path),
        "summary": universe.summary,
        "validation": universe.validation,
        "detected_schema": universe.detected_schema,
        "riders": universe.riders,
    }


def write_dashboard_rider_artifact(repo_root: Path, universe: RiderUniverse) -> Path:
    """Write a ChatGPT-owned dashboard data artifact; never writes to shared/."""
    output_path = repo_root / "chatgpt" / "dashboard" / "data" / "riders_giro_2026.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(to_dashboard_payload(universe), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return output_path


def _extract_raw_riders(payload: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("riders"), list):
        raise ValueError(f"Expected {path} to contain a dict with a riders list.")
    return payload["riders"]


def _normalize_rider(raw: dict[str, Any]) -> dict[str, Any]:
    holdet_id = raw.get("holdet_id")
    price = raw.get("price", raw.get("startPrice"))
    return {
        "holdet_id": int(holdet_id) if holdet_id is not None else None,
        "name": str(raw.get("name", "")).strip(),
        "team": str(raw.get("team", "")).strip(),
        "team_code": raw.get("team_code") or raw.get("teamCode"),
        "price": int(price) if isinstance(price, int) or (isinstance(price, str) and price.isdigit()) else price,
    }


def _snapshot_holdet_ids(snapshot: dict[str, Any]) -> set[int]:
    if isinstance(snapshot.get("holdet_ids"), dict):
        return {int(value) for value in snapshot["holdet_ids"].values() if value is not None}
    if isinstance(snapshot.get("holdet_ids"), list):
        return {int(value) for value in snapshot["holdet_ids"] if value is not None}
    if isinstance(snapshot.get("riders"), list):
        return {
            int(rider["holdet_id"])
            for rider in snapshot["riders"]
            if isinstance(rider, dict) and rider.get("holdet_id") is not None
        }
    return set()

