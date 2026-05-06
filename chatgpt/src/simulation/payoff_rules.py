"""Deterministic Holdet payoff-rule encoder."""

from __future__ import annotations

from typing import Any


def build_payoff_rules() -> dict[str, Any]:
    """Encode the authoritative static payoff rules."""
    return {
        "version": "holdet_giro_2026_payoff_v1",
        "team": {
            "starting_budget": 50_000_000,
            "team_size": 8,
            "max_same_real_world_team": 2,
            "captains": 1,
        },
        "financial": {
            "transfer_buy_fee_rate": 0.01,
            "stage_1_transfers_free": True,
            "bank_interest_rate_per_round": 0.005,
        },
        "stage_finish_values": {
            1: 200_000,
            2: 150_000,
            3: 130_000,
            4: 120_000,
            5: 110_000,
            6: 100_000,
            7: 95_000,
            8: 90_000,
            9: 85_000,
            10: 80_000,
            11: 70_000,
            12: 55_000,
            13: 40_000,
            14: 30_000,
            15: 15_000,
        },
        "gc_values": {
            1: 100_000,
            2: 90_000,
            3: 80_000,
            4: 70_000,
            5: 60_000,
            6: 50_000,
            7: 40_000,
            8: 30_000,
            9: 20_000,
            10: 10_000,
        },
        "jersey_bonus": {
            "gc_leader": 25_000,
            "points_leader": 25_000,
            "kom_leader": 25_000,
            "young_rider_leader": 15_000,
            "most_aggressive": 50_000,
        },
        "points": {
            "sprint_point_value": 3_000,
            "kom_point_value": 3_000,
        },
        "late_arrival": {
            "penalty_per_full_minute": -3_000,
            "penalty_cap": -90_000,
        },
        "status_penalties": {
            "dnf_once": -50_000,
            "dns_per_remaining_stage": -100_000,
            "disqualified_once": -50_000,
        },
        "team_bonus": {
            1: 60_000,
            2: 30_000,
            3: 20_000,
        },
        "captain": {
            "positive_growth_deposited_to_bank": True,
            "negative_growth_amplified": False,
        },
        "stage_depth_bonus": {
            0: 0,
            1: 4_000,
            2: 8_000,
            3: 15_000,
            4: 35_000,
            5: 65_000,
            6: 120_000,
            7: 220_000,
            8: 400_000,
        },
        "ttt": {
            "placement_values": {
                1: 200_000,
                2: 150_000,
                3: 100_000,
                4: 50_000,
                5: 25_000,
            },
            "replaces_stage_finish": True,
            "replaces_team_bonus": True,
            "late_arrival_applies": False,
            "stage_depth_bonus_applies": False,
        },
    }


def stage_finish_value(position: int, rules: dict[str, Any] | None = None) -> int:
    payoff_rules = rules or build_payoff_rules()
    return payoff_rules["stage_finish_values"].get(position, 0)


def transfer_buy_fee(price: int | float, rules: dict[str, Any] | None = None) -> float:
    payoff_rules = rules or build_payoff_rules()
    return price * payoff_rules["financial"]["transfer_buy_fee_rate"]

