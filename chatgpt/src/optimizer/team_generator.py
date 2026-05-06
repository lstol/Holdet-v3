"""Candidate-team generator stub."""

from __future__ import annotations

from typing import Any


def generate_candidate_teams(
    snapshot: dict[str, Any],
    tier_a: dict[str, Any],
    payoff_rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return structurally explicit placeholder teams.

    The real generator should optimize the upcoming stage payoff first, then
    expose forward transfer pressure separately.
    """
    current_team = snapshot.get("team_composition", [])
    return [
        {
            "label": "Current team baseline",
            "riders": current_team,
            "captain": None,
            "status": "stub",
            "stage_ev": None,
            "right_tail_metrics": {},
            "forward_transfer_pressure": {
                "expected_structurally_wrong_riders": None,
                "expected_transfer_count": None,
                "expected_buy_fee": None,
                "dns_catastrophe_exposure": None,
            },
            "assumptions": [
                "Candidate generation is not active until probabilities and stage snapshot arrive.",
                "Team size, budget, max two per real-world team, and buy fee rules are encoded inputs.",
            ],
            "payoff_contract_version": payoff_rules["version"],
        }
    ]

