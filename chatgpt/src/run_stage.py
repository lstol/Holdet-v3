"""Explicit stage pipeline for ChatGPT-side optimization scaffolding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.captaincy.captain_ev import estimate_captain_ev
from src.ingest.odds_intel import load_expert_intel, load_odds_inputs
from src.ingest.snapshot_loader import load_snapshot
from src.intel.source_notes import summarize_intel_inputs
from src.optimizer.team_generator import generate_candidate_teams
from src.probabilities.tier_a import classify_tier_a
from src.reporting.output_writer import write_stage_output
from src.simulation.payoff_rules import build_payoff_rules


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run(repo_root: Path, stage_number: int, config: dict[str, Any]) -> Path:
    snapshot = load_snapshot(repo_root, stage_number)
    payoff_rules = build_payoff_rules()
    odds = load_odds_inputs(config)
    expert_intel = load_expert_intel(config)
    tier_a = classify_tier_a(snapshot, odds, expert_intel)
    candidate_teams = generate_candidate_teams(snapshot, tier_a, payoff_rules)
    captain_ev = estimate_captain_ev(candidate_teams, tier_a)

    payload = {
        "status": "scaffold",
        "assumptions": [
            "Shared snapshot is the authoritative frozen project input.",
            "Odds, expert intel, probabilities, and recommendations are ChatGPT-local outputs.",
            "No Holdet-v2 architecture assumptions are encoded.",
        ],
        "snapshot_stage_metadata": snapshot.get("stage_metadata", {}),
        "payoff_rules_version": payoff_rules["version"],
        "intel_summary": summarize_intel_inputs(odds, expert_intel),
        "tier_a": tier_a,
        "candidate_teams": candidate_teams,
        "captain_ev": captain_ev,
    }
    return write_stage_output(repo_root, stage_number, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ChatGPT-side Holdet stage scaffold.")
    parser.add_argument("--stage", type=int, required=True, help="Stage number for stage_N_snapshot.json")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root. Defaults to Holdet-v3 root from chatgpt/src/.",
    )
    parser.add_argument("--config", type=Path, default=None, help="Optional ChatGPT-local config JSON.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = load_config(args.config)
    output = run(args.repo_root, args.stage, config)
    print(output)
