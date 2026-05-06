"""Captain EV stub focused on right-tail positive growth."""

from __future__ import annotations

from typing import Any


def estimate_captain_ev(candidate_teams: list[dict[str, Any]], tier_a: dict[str, Any]) -> list[dict[str, Any]]:
    """Return placeholder captain EV records.

    Final implementation should compute E[max(delta_value, 0)] from simulated
    rider outcome distributions, not simple mean EV.
    """
    riders = tier_a.get("riders", [])
    if not riders:
        return [
            {
                "status": "stub",
                "recommended_captain": None,
                "right_tail_positive_growth_ev": None,
                "assumptions": [
                    "Captain recommendation requires simulated rider distributions.",
                    "Captain negative days are not amplified.",
                ],
            }
        ]

    return [
        {
            "status": "stub",
            "recommended_captain": riders[0],
            "right_tail_positive_growth_ev": None,
            "candidate_team_count": len(candidate_teams),
        }
    ]

