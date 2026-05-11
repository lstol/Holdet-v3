"""
claude/engine/optimizer.py
Python Monte Carlo optimizer for Holdet fantasy cycling.

Search: Simulated Annealing — 10 independent chains, biased swap, 3s each.
Scoring: Plackett-Luce Monte Carlo on final candidates (exact CDF).

Hard constraints (enforced throughout):
  - Budget ≤ 50,000,000 kr
  - Exactly 8 riders
  - Max 2 riders from the same real-world team
"""

import datetime
import hashlib
import json
import logging
import math
import os
import re
import random
import time
from collections import Counter, defaultdict

import numpy as np


# ── Diagnostic log (mirrors server.py's _log into claude/logs/server.log) ─
_OPT_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'claude', 'logs', 'server.log'
)


def _log_optimizer(msg: str) -> None:
    """Best-effort append to server.log. Used for S17-21 multi-start
    diagnostics — internal-only, not surfaced to API or dashboard."""
    try:
        os.makedirs(os.path.dirname(_OPT_LOG_FILE), exist_ok=True)
        with open(_OPT_LOG_FILE, 'a') as f:
            f.write(f"[{datetime.datetime.utcnow().isoformat()}] {msg}\n")
    except Exception:
        pass


# ── Determinism ───────────────────────────────────────────────────────────────
#
# S16-3: every RNG site below threads through an explicit seed derived from the
# request payload. Identical inputs → bit-identical outputs. Per-strategy
# sub-seeds (XOR mask) preserve the "four genuinely different SA trajectories"
# property without leaking state across strategies.

def compute_seed(stage, sliders, force_in, force_out, use_race_type_adjustment):
    """Hash the optimizer inputs to a 64-bit int. Stable against list-order
    variation in force_in / force_out (they're sorted before hashing).

    S17-2 Tier A: when the race-type adjustment is off, n1 sliders have no
    effect on the current-stage probabilities consumed by build_probabilities
    (verified by inspection of optimizer.py:348-403 — the entire adjustment
    block is gated by `if use_race_type and sliders:`). Including n1 in the
    seed payload then causes the SA to pick a different local optimum across
    search-equivalent inputs purely via seed perturbation — that's the bug
    surfaced by the S17-2 diagnostic and the three-basin behaviour observed
    in S17-21 Phase 1.5. Drop n1 from the hash in that case; n2/n3 still
    feed build_forward_probabilities so they stay in.
    """
    sliders_for_hash = dict(sliders or {})
    if not use_race_type_adjustment and 'n1' in sliders_for_hash:
        sliders_for_hash = {k: v for k, v in sliders_for_hash.items() if k != 'n1'}
    payload = json.dumps({
        "stage":                    stage,
        "sliders":                  sliders_for_hash,
        "force_in":                 sorted(force_in or []),
        "force_out":                sorted(force_out or []),
        "use_race_type_adjustment": bool(use_race_type_adjustment),
    }, sort_keys=True, default=str)
    return int(hashlib.sha256(payload.encode()).hexdigest()[:16], 16)


# ── Scoring constants ─────────────────────────────────────────────────────────

BUDGET = 50_000_000

FINISH_POINTS = [
    200_000, 150_000, 130_000, 120_000, 110_000, 100_000,
     95_000,  90_000,  85_000,  80_000,  70_000,  55_000,
     40_000,  30_000,  15_000,
]

DEPTH_BONUS = {
    0:       0,
    1:   4_000,
    2:   8_000,
    3:  15_000,
    4:  35_000,
    5:  65_000,
    6: 120_000,
    7: 220_000,
    8: 400_000,
}

# 0-indexed finish position → bonus per fantasy rider from same real-world team
TEAM_BONUS_MAP = {0: 60_000, 1: 30_000, 2: 20_000}

INTEL_MULT = {
    ('up',      'strong'):   1.20,
    ('up',      'moderate'): 1.10,
    ('up',      'weak'):     1.05,
    ('down',    'strong'):   0.75,
    ('down',    'moderate'): 0.85,
    ('down',    'weak'):     0.95,
}

# Sprint points → fantasy kr (each point = 3,000 kr)
POINT_VALUE = 3_000
SPRINT_POINTS_FINAL        = [50, 30, 20, 18, 16, 14, 12, 10, 8, 6, 4, 2]
SPRINT_POINTS_INTERMEDIATE = [20, 12, 8, 6, 4, 2]
SPRINT_KR_FINAL        = [p * POINT_VALUE for p in SPRINT_POINTS_FINAL]
SPRINT_KR_INTERMEDIATE = [p * POINT_VALUE for p in SPRINT_POINTS_INTERMEDIATE]

# Jersey bonus (paid to current holder after each stage)
JERSEY_BONUS = {
    'gc':     25_000,
    'points': 25_000,
    'kom':    25_000,
    'youth':  25_000,
}

# GC bonus paid after each stage based on overall standings position (1-indexed)
GC_BONUS = {
    1: 100_000, 2: 90_000, 3: 80_000, 4: 70_000, 5: 60_000,
    6:  50_000, 7: 40_000, 8: 30_000, 9: 20_000, 10: 10_000,
}

_FP_W1    = FINISH_POINTS[0]
_FP_W23   = (FINISH_POINTS[1] + FINISH_POINTS[2]) / 2
_FP_W4_10 = sum(FINISH_POINTS[3:10]) / 7
_FP_W11_15= sum(FINISH_POINTS[10:15]) / 5

# ── Stage scoring helpers ─────────────────────────────────────────────────────

import json as _json
import os as _os

def load_stage_scoring():
    """Load stage_scoring.json from shared/data/stages/giro_2026/. Returns {} on miss."""
    base = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    path = _os.path.join(base, 'shared', 'data', 'stages', 'giro_2026', 'stage_scoring.json')
    if _os.path.exists(path):
        with open(path) as f:
            return _json.load(f)
    return {}

def get_stage_config(stage_num, scoring):
    """Return the per-stage dict from scoring, or {} if missing."""
    return scoring.get('stages', {}).get(str(stage_num), {})

def sprint_type_to_stage_type(sprint_type):
    """A→'sprint', B→'hilly', C→'mountain'."""
    return {'A': 'sprint', 'B': 'hilly', 'C': 'mountain'}.get(sprint_type, 'sprint')

def compute_sprint_ev(rider_pos, stage_config, scoring):
    """Sprint kr EV for a rider at 1-indexed finish position on this stage."""
    pv   = scoring.get('point_value_kr', POINT_VALUE)
    pts  = stage_config.get('sprint_points', [])
    kr   = pts[rider_pos - 1] * pv if rider_pos <= len(pts) else 0
    n    = stage_config.get('n_intermediate_sprints', 0)
    if n > 0:
        ipts = scoring.get('intermediate_sprint_points', [])
        kr  += (ipts[rider_pos - 1] * pv if rider_pos <= len(ipts) else 0) * n
    return kr

def compute_climb_ev(rider_pos, climbs, scoring):
    """KOM kr EV for a rider at 1-indexed finish position across all stage climbs."""
    pv = scoring.get('point_value_kr', POINT_VALUE)
    kr = 0
    for climb in climbs:
        cat = climb.get('cat')
        if cat == 'cima_coppi':
            cat_key = 'cima_coppi'
        elif climb.get('at_finish') and cat == 1:
            cat_key = 'cat1_finish'
        else:
            cat_key = f'cat{cat}'
        cp  = scoring.get('climb_points', {}).get(cat_key, {})
        pts = cp.get('points', [])
        if rider_pos <= len(pts):
            kr += pts[rider_pos - 1] * pv
    return kr


# ── Utility: team-name normalisation ─────────────────────────────────────────

def _norm_team(name):
    """
    Normalise a real-world team name for constraint counting.

    riders.json has inconsistent names for the same team, e.g.:
      'Tudor Pro Cycling'  vs 'Tudor Pro Cycling Team'
      'Lidl-Trek'          vs 'Lidl - Trek'
      'XDS Astana'         vs 'XDS Astana Team'
      'Netcompany INEOS'   vs 'Netcompany INEOS Cycling Team'

    Strategy: lowercase, replace punctuation separators with space,
    remove the words 'team' and 'cycling', collapse whitespace.
    """
    n = re.sub(r'[^\w\s]', ' ', (name or '').lower())
    n = re.sub(r'\bcycling\b', '', n)
    n = re.sub(r'\bteam\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


# ── Stage-type EV annotation ──────────────────────────────────────────────────

def add_stage_evs(probs, stage_config=None, scoring=None):
    """
    Annotate each rider's probs entry with stage-specific EV fields (in-place).
    Adds: sprint_ev, jersey_ev, gc_ev, kom_ev, total_ev.

    stage_config: dict from stage_scoring.json['stages']['N']
    scoring:      full stage_scoring.json dict (for point_value_kr, climb_points, etc.)
    """
    if stage_config is None:
        stage_config = {}
    if scoring is None:
        scoring = {}

    pv          = scoring.get('point_value_kr', POINT_VALUE)
    sprint_pts  = stage_config.get('sprint_points', SPRINT_POINTS_FINAL)
    sprint_kr   = [p * pv for p in sprint_pts]
    n_inter     = stage_config.get('n_intermediate_sprints', 1)
    inter_pts   = scoring.get('intermediate_sprint_points', SPRINT_POINTS_INTERMEDIATE)
    inter_kr    = [p * pv for p in inter_pts]
    climbs      = stage_config.get('climbs', [])
    sprint_type = stage_config.get('sprint_type', 'A')
    stage_type  = sprint_type_to_stage_type(sprint_type)

    for p in probs.values():
        fp = p.get('finish_probs', [0.0] * 15)
        pw = p.get('win', 0.0)

        # Sprint EV (zero on mountain stages — Type C)
        if stage_type in ('sprint', 'hilly'):
            sprint_ev = sum(fp[i] * sprint_kr[i]
                            for i in range(min(len(fp), len(sprint_kr))))
            sprint_ev += n_inter * sum(fp[i] * inter_kr[i]
                                       for i in range(min(len(fp), len(inter_kr))))
        else:
            sprint_ev = 0.0

        # Jersey EV (points jersey only on Type A sprint stages)
        if sprint_type == 'A':
            jersey_ev = pw * (JERSEY_BONUS['gc'] + JERSEY_BONUS['points'])
        else:
            jersey_ev = pw * JERSEY_BONUS['gc']

        # GC EV
        gc_ev = sum(fp[i] * GC_BONUS.get(i + 1, 0) for i in range(min(len(fp), 10)))

        # KOM EV (approximate: use finish position as proxy for climb position)
        kom_ev = sum(fp[i] * compute_climb_ev(i + 1, climbs, scoring)
                     for i in range(len(fp)) if fp[i] > 0)

        p['sprint_ev'] = sprint_ev
        p['jersey_ev'] = jersey_ev
        p['gc_ev']     = gc_ev
        p['kom_ev']    = kom_ev
        p['total_ev']  = p['finish_ev'] + sprint_ev + jersey_ev + gc_ev + kom_ev


# ── Step 1: Build probabilities ───────────────────────────────────────────────

def build_probabilities(all_riders, odds, intel, sliders=None,
                        stage_config=None, scoring=None,
                        use_race_type=False):
    """
    Returns dict: {rider_name: {win, top3, top10, top15, finish_probs,
                                finish_ev, team_bonus_ev, p2, p3, p_top15,
                                team (normalised), name}}

    1. Start from bookmaker win_pct (already averaged).
    2. Apply intel direction/strength multipliers.
    3. Renormalise so win probs sum to 1.0.
    4. Derive top-3/10/15 from win probability.
    5. Precompute finish_ev and team_bonus_ev for fast SA objective calls.

    Dynamic EPS: non-odds riders collectively get ~20% of probability mass so
    the simulation has realistic variance (peloton riders occasionally infiltrate
    the top 15, giving depth-bonus uncertainty).

    use_race_type: if True and the n1 sliders are non-uniform, multiply each
    rider's win/top3/top10/top15 by a SCENARIO_TO_TERRAIN-derived multiplier
    and renormalise each bucket back to its pre-multiplier sum (preserves
    bookmaker overround). Tickbox-gated; OFF by default — same behaviour as
    pre-F2a.
    """
    # Odds lookup — support market top3/top10 where available
    odds_map      = {}   # name → win prob (fraction)
    top3_map      = {}   # name → market top-3 prob (fraction), if pasted
    top10_map     = {}   # name → market top-10 prob (fraction), if pasted
    for o in odds:
        name = o.get('name')
        if not name:
            continue
        odds_map[name]  = o.get('win_pct', 0) / 100.0
        # Project invariant: zero means missing (S17-29). Cleared/missing
        # top3/top10 falls through to the win-derived fallback below.
        if (o.get('top3_pct') or 0) > 0:
            top3_map[name]  = o['top3_pct']  / 100.0
        if (o.get('top10_pct') or 0) > 0:
            top10_map[name] = o['top10_pct'] / 100.0

    in_odds = set(n for n, p in odds_map.items() if p > 0)

    # Dynamic EPS: EPS = 0.25 * raw_odds_total / n_non_odds → renorms to ~20%
    raw_odds_total = sum(odds_map.values())
    n_non_odds     = max(len(all_riders) - len(in_odds), 1)
    EPS            = max(1e-5, 0.25 * raw_odds_total / n_non_odds)

    # Intel multipliers
    adj = {}
    if isinstance(intel, dict):
        src = intel.get('intel', intel)
        if isinstance(src, dict):
            for sig in src.get('key_signals', []):
                key  = (sig.get('direction', 'neutral'), sig.get('strength', 'weak'))
                mult = INTEL_MULT.get(key, 1.0)
                if sig.get('rider'):
                    adj[sig['rider']] = mult

    # Raw win probabilities
    raw = {}
    for r in all_riders:
        name = r['name']
        base = odds_map.get(name, 0.0)
        raw[name] = (base * adj.get(name, 1.0)) if base > 0 else EPS

    # Renormalise
    total = sum(raw.values())
    if total > 0:
        for name in raw:
            raw[name] /= total

    # Build per-rider probability entries (pass 1)
    result = {}
    for r in all_riders:
        name = r['name']
        pw   = raw.get(name, EPS)

        if name in in_odds:
            # Prefer market-derived top3/top10 over win-scaled estimates
            top3  = top3_map.get(name,  min(0.95, pw * 3.5))
            top10 = top10_map.get(name, min(0.95, pw * 8.0))
            top15 = min(0.95, top10 + top10 * 0.15)   # ~15% of top-10 riders also land 11-15
        else:
            top3 = 0.02; top10 = 0.04; top15 = 0.05

        # Per-position finish probabilities anchored to the three market levels
        fp    = [0.0] * 15
        fp[0] = pw
        d23   = max(0.0, top3  - pw)  / 2
        d410  = max(0.0, top10 - top3) / 7
        d1115 = max(0.0, top15 - top10) / 5
        for i in range(1, 3):   fp[i] = d23
        for i in range(3, 10):  fp[i] = d410
        for i in range(10, 15): fp[i] = d1115

        finish_ev = (
            pw      * _FP_W1
            + d23*2 * _FP_W23
            + d410*7* _FP_W4_10
            + d1115*5* _FP_W11_15
        )

        result[name] = {
            'win':   pw,   'top3': top3, 'top10': top10, 'top15': top15,
            'finish_probs': fp,
            'p2':    fp[1], 'p3': fp[2], 'p_top15': top15,
            'finish_ev':    finish_ev,
            'team': _norm_team(r.get('team', '')),
            'name': name,
        }

    # ── Race-type odds adjustment (n1 slider, tickbox-gated) ──────────────────
    if use_race_type and sliders:
        s = {k: sliders.get(k, 0) / 100.0
             for k in ('bunch_sprint', 'reduced_sprint', 'breakaway', 'gc')}
        # Uniform sliders → multiplier = 1.0 for all riders → no-op
        if not all(abs(v - 0.25) < 1e-6 for v in s.values()):
            ta_by_name = {r['name']: r.get('terrain_affinity', {}) for r in all_riders}

            def _scenario_score(ta, weights):
                return sum(
                    weights[bucket] * sum(
                        SCENARIO_TO_TERRAIN[bucket][dim] * ta.get(dim, 0)
                        for dim in SCENARIO_TO_TERRAIN[bucket]
                    )
                    for bucket in weights
                )

            uniform = {k: 0.25 for k in s}
            mults = {}
            for name, ta in ta_by_name.items():
                baseline = _scenario_score(ta, uniform)
                if baseline < 1e-6:
                    mults[name] = 1.0
                else:
                    mults[name] = max(0.6, min(1.5, _scenario_score(ta, s) / baseline))

            # Capture pre-multiplier sums per bucket; scale; renormalise
            for key in ('win', 'top3', 'top10', 'top15'):
                pre_sum = sum(p[key] for p in result.values())
                for n, p in result.items():
                    p[key] *= mults.get(n, 1.0)
                post_sum = sum(p[key] for p in result.values())
                if post_sum < 1e-9 or pre_sum < 1e-9:
                    continue
                scale = pre_sum / post_sum
                for p in result.values():
                    p[key] *= scale

            # Recompute per-position finish_probs and finish_ev from rescaled values
            for p in result.values():
                pw, top3, top10, top15 = p['win'], p['top3'], p['top10'], p['top15']
                fp = [0.0] * 15
                fp[0] = pw
                d23   = max(0.0, top3  - pw)  / 2
                d410  = max(0.0, top10 - top3) / 7
                d1115 = max(0.0, top15 - top10) / 5
                for i in range(1, 3):   fp[i] = d23
                for i in range(3, 10):  fp[i] = d410
                for i in range(10, 15): fp[i] = d1115
                p['finish_probs'] = fp
                p['p2']           = fp[1]
                p['p3']           = fp[2]
                p['p_top15']      = top15
                p['finish_ev']    = (
                    pw      * _FP_W1
                    + d23*2 * _FP_W23
                    + d410*7* _FP_W4_10
                    + d1115*5* _FP_W11_15
                )

    add_stage_evs(result, stage_config=stage_config, scoring=scoring)
    return result


# ── Step 2: Analytical team EV (fast — used during SA search) ─────────────────

def compute_team_bonus_ev(fantasy_team, probs):
    """
    Team bonus EV for the actual fantasy team composition.

    Rule: a fantasy rider earns a bonus when their ONE real-world teammate
    in the fantasy team finishes on the podium (P1=60k, P2=30k, P3=20k).
    With the max-2-per-team constraint there is at most one pair per team.
    """
    by_team = defaultdict(list)
    for r in fantasy_team:
        by_team[_norm_team(r.get('team', ''))].append(r)

    total = 0.0
    for riders in by_team.values():
        if len(riders) == 2:
            # Each rider is a trigger for the other's bonus
            for trigger in riders:
                p = probs.get(trigger['name'], {})
                total += p.get('win', 0) * 60_000
                total += p.get('p2',  0) * 30_000
                total += p.get('p3',  0) * 20_000
    return total


def compute_team_ev(team, probs):
    """
    Fast analytical expected value for a team of 8 rider dicts.

    Components:
      1. Stage finish + sprint + jersey + GC EV per rider (all precomputed in total_ev)
      2. Captain bonus ≈ best rider's total_ev (doubling all positive outcomes)
      3. Team bonus EV — pairs only, composition-aware
      4. Depth bonus EV
    """
    total_evs = [probs.get(r['name'], {}).get('total_ev',
                 probs.get(r['name'], {}).get('finish_ev', 0.0)) for r in team]
    total  = sum(total_evs)
    total += max(total_evs) if total_evs else 0.0   # captain bonus
    total += compute_team_bonus_ev(team, probs)
    exp_top15 = sum(probs.get(r['name'], {}).get('top15', 0.0) for r in team)
    total += DEPTH_BONUS.get(min(8, round(exp_top15)), 0)
    return total


# ── Step 3: Constraint checker ────────────────────────────────────────────────

def is_valid(team, budget=BUDGET):
    """Return True iff team satisfies all hard constraints."""
    if len(team) != 8:
        return False
    if sum(r.get('price', 0) for r in team) > budget:
        return False
    tc = defaultdict(int)
    for r in team:
        nt = _norm_team(r.get('team', ''))
        tc[nt] += 1
        if tc[nt] > 2:
            return False
    return True


# ── Step 4: Random valid initial solution ─────────────────────────────────────

def get_valid_random_team(forced, pool, budget, rng=None):
    """
    Return a random valid team by shuffling pool and greedily filling.
    Returns None if no valid team found after many attempts.

    rng: random.Random instance for deterministic shuffles. When None, falls
    back to the global random module (legacy / direct-call path).
    """
    shuffler = rng if rng is not None else random
    for _ in range(5_000):
        shuffled = pool[:]
        shuffler.shuffle(shuffled)

        team = list(forced)
        tc   = defaultdict(int)
        for r in forced:
            tc[_norm_team(r.get('team', ''))] += 1
        rem  = budget - sum(r.get('price', 0) for r in forced)

        for r in shuffled:
            if len(team) >= 8:
                break
            nt = _norm_team(r.get('team', ''))
            if tc[nt] < 2 and r.get('price', 0) <= rem:
                team.append(r)
                tc[nt] += 1
                rem -= r['price']

        if len(team) == 8:
            return team
    return None


# ── Step 5: Simulated Annealing ───────────────────────────────────────────────

def _compute_objective(team, probs, objective):
    """Return the SA objective score for a team.  'ev' → full EV; 'depth' → depth-weighted."""
    if objective == 'depth':
        finish_evs = [probs.get(r['name'], {}).get('finish_ev', 0.0) for r in team]
        exp_top15  = sum(probs.get(r['name'], {}).get('top15', 0.0) for r in team)
        # Triple depth bonus weight; half finish weight — pull SA toward top-15 coverage
        return sum(finish_evs) * 0.5 + DEPTH_BONUS.get(min(8, round(exp_top15)), 0) * 3
    return compute_team_ev(team, probs)


# ── Transfer cost model ───────────────────────────────────────────────────────

TRANSFER_COST_RATE = 0.01   # 1% of buy price
LOOKAHEAD_DISCOUNT = 0.7

rider_ev_cache = {}  # populated per-run in generate_candidate_teams


def compute_transfer_cost(current_team, target_team, probs_next=None):
    """
    Cost to move from current_team to target_team.
    No cap — sprint to mountain can mean 8 transfers.
    GC penalty adds implicit cost for sprinters facing mountain stages.
    """
    current_names = {r['name'] for r in current_team}
    buys = [r for r in target_team if r['name'] not in current_names]
    cost = sum(r.get('price', 0) * TRANSFER_COST_RATE for r in buys)
    if probs_next:
        for r in current_team:
            if probs_next.get(r['name'], {}).get('gc_penalty'):
                cost += 50_000
    return cost


# Slider bucket → which rider.terrain_affinity dimensions it favors.
# The only "scenario hardcoding" — generic across riders.
SCENARIO_TO_TERRAIN = {
    'bunch_sprint':   {'sprint': 1.0},
    'reduced_sprint': {'sprint': 0.5, 'mixed': 0.5},
    'breakaway':      {'mixed': 1.0},
    'gc':             {'climbing': 1.0},
}


def build_forward_probabilities(riders, sliders):
    """
    Approximate probability distribution for a future stage where no odds exist.
    Score each rider by combining slider weights × SCENARIO_TO_TERRAIN ×
    rider.terrain_affinity, then renormalize to win probabilities.
    """
    s = {
        bucket: sliders.get(bucket, 0) / 100.0
        for bucket in ('bunch_sprint', 'reduced_sprint', 'breakaway', 'gc')
    }

    raw = {}
    for r in riders:
        ta = r.get('terrain_affinity', {})
        score = 0.0
        for bucket, weight in s.items():
            if weight == 0:
                continue
            for dim, dim_weight in SCENARIO_TO_TERRAIN[bucket].items():
                score += weight * dim_weight * ta.get(dim, 0)
        raw[r['name']] = max(0.001, score)

    total = sum(raw.values())
    probs = {}
    for r in riders:
        w = raw[r['name']] / total
        p_top3  = min(0.95, w * 3.5)
        p_top10 = min(0.95, w * 8.0)
        p_top15 = min(0.95, w * 12.0)
        fp = [0.0] * 15
        fp[0] = w
        d23   = max(0.0, p_top3 - w) / 2
        d410  = max(0.0, p_top10 - p_top3) / 7
        d1115 = max(0.0, p_top15 - p_top10) / 5
        for i in range(1, 3):   fp[i] = d23
        for i in range(3, 10):  fp[i] = d410
        for i in range(10, 15): fp[i] = d1115
        finish_ev = (
            w * _FP_W1 + d23 * 2 * _FP_W23
            + d410 * 7 * _FP_W4_10 + d1115 * 5 * _FP_W11_15
        )
        probs[r['name']] = {
            'name':         r['name'],
            'team':         _norm_team(r.get('team', '')),
            'win':          w,
            'top3':         p_top3,
            'top10':        p_top10,
            'top15':        p_top15,
            'p2':           fp[1],
            'p3':           fp[2],
            'p_top15':      p_top15,
            'finish_probs': fp,
            'finish_ev':    finish_ev,
            'total_ev':     finish_ev,
        }
    return probs


def fast_optimize(candidates, probabilities, all_riders, force_in, force_out, budget, seed=0):
    """Quick 10k-iteration approximation. Used for forward cost estimation only."""
    rng = random.Random(seed)
    forced_set   = set(force_in or [])
    excluded_set = set(force_out or [])
    forced = [r for r in candidates if r['name'] in forced_set]
    pool   = [r for r in candidates
              if r['name'] not in excluded_set and r['name'] not in forced_set]

    team = get_valid_random_team(forced, pool, budget, rng=rng)
    if not team:
        return None

    ev_cache_local = {r['name']: probabilities.get(r['name'], {}).get('total_ev', 0.0) for r in candidates}
    sorted_pool    = sorted(pool, key=lambda r: ev_cache_local.get(r['name'], 0), reverse=True)
    top_n          = sorted_pool[:min(50, len(sorted_pool))]

    best_team  = team[:]
    best_ev    = compute_team_ev(team, probabilities)
    current_ev = best_ev
    T          = 50_000.0
    cooling    = 0.9995
    start      = time.time()
    n_forced   = len(forced)

    for _ in range(10_000):
        if time.time() - start > 1.0:
            break
        # biased swap inline
        if rng.random() < 0.7 and top_n:
            out_pos   = min(range(n_forced, 8), key=lambda idx: ev_cache_local.get(team[idx]['name'], 0))
            new_rider = top_n[rng.randrange(len(top_n))]
        else:
            out_pos   = rng.randrange(n_forced, 8)
            new_rider = pool[rng.randrange(len(pool))] if pool else team[out_pos]

        if any(new_rider['name'] == r['name'] for r in team):
            T *= cooling; continue
        new_team = team[:]
        new_team[out_pos] = new_rider
        if not is_valid(new_team, budget):
            T *= cooling; continue
        new_ev = compute_team_ev(new_team, probabilities)
        delta  = new_ev - current_ev
        if delta > 0 or rng.random() < math.exp(delta / max(T, 1)):
            team = new_team; current_ev = new_ev
            if new_ev > best_ev:
                best_ev = new_ev; best_team = team[:]
        T *= cooling

    return best_team


def estimate_forward_costs(current_team, candidates, all_riders,
                            probs_n1, probs_n2, force_in, force_out, budget,
                            seed=None):
    """Two-step transfer cost estimation using fast SA. The two forward chains
    use distinct sub-seeds so they don't run identical trajectories."""
    seed_n1 = (seed ^ 0xA) if seed is not None else 42
    seed_n2 = (seed ^ 0xB) if seed is not None else 42
    team_n1 = fast_optimize(candidates, probs_n1, all_riders, force_in, force_out, budget, seed=seed_n1)
    team_n2 = fast_optimize(candidates, probs_n2, all_riders, force_in, force_out, budget, seed=seed_n2)

    cost_n1 = compute_transfer_cost(current_team, team_n1 or [], probs_n1) if team_n1 else 0
    cost_n2 = compute_transfer_cost(team_n1 or [], team_n2 or [], probs_n2) if team_n1 and team_n2 else 0

    n_tr_n1 = len([r for r in (team_n1 or [])
                   if r['name'] not in {x['name'] for x in current_team}])
    n_tr_n2 = len([r for r in (team_n2 or [])
                   if r['name'] not in {x['name'] for x in (team_n1 or [])}])

    return cost_n1, cost_n2, n_tr_n1, n_tr_n2, team_n1, team_n2


def topup_team(team, candidates, probabilities, all_riders, budget):
    """Fill any gaps (team < 8) after SA. Should not normally be needed."""
    if len(team) >= 8:
        return team
    used = {r['name'] for r in team}
    pool = [r for r in candidates if r['name'] not in used]
    pool.sort(key=lambda r: probabilities.get(r['name'], {}).get('total_ev', 0), reverse=True)
    for r in pool:
        if len(team) >= 8:
            break
        cand = team + [r]
        if is_valid(cand, budget):
            team = cand
    return team


def compute_objective(team, probabilities, all_riders, objective='ev',
                      cost_n1=0, cost_n2=0, team_n1=None, team_n2=None,
                      current_team=None):
    """Multi-strategy objective for SA search.

    current_team is only consulted by the 'lookahead' objective — other
    strategies remain bit-identical regardless of whether it's passed.
    """
    base_ev = compute_team_ev(team, probabilities)

    if objective == 'ev':
        return base_ev

    elif objective == 'depth':
        expected_top15 = sum(
            probabilities.get(r['name'], {}).get('top15', 0.05) for r in team
        )
        return base_ev + DEPTH_BONUS.get(min(8, round(expected_top15)), 0) * 2

    elif objective == 'low_transfer':
        tc = compute_transfer_cost(team, team_n1 or []) if team_n1 else 0
        return base_ev - tc * 3

    elif objective == 'lookahead':
        # S16-4: align internal objective with the user-facing transfer-adj EV
        # metric. Pre-refactor missed tc_current, so Lookahead happily picked
        # candidate teams that required expensive current-stage transfers in
        # pursuit of marginal forward optionality. Post-refactor:
        #   maximize  ev − tc_current − cost_n1 − 0.7 × cost_n2
        # Coefficients (1.0 / 1.0 / 0.7) match the user-facing formula and
        # the result-assembly's 'total_forward_cost' field exactly.
        tc_current = compute_transfer_cost(current_team or [], team) if current_team else 0
        tc_n1      = compute_transfer_cost(team, team_n1 or [])      if team_n1 else 0
        tc_n2      = compute_transfer_cost(team_n1 or [], team_n2 or []) if team_n1 and team_n2 else 0
        return base_ev - tc_current - tc_n1 - (LOOKAHEAD_DISCOUNT * tc_n2)

    return base_ev


_SA_LOG_ITERS = {0, 50_000, 100_000, 500_000, 1_000_000, 2_000_000}
_sa_logger = logging.getLogger(__name__)


def simulated_annealing(all_riders, probs, force_in_names, force_out_names,
                         budget=BUDGET, n_iter=200_000, seed=42,
                         max_seconds=3, objective='ev', verbose=False,
                         cost_n1=0, cost_n2=0, team_n1=None, team_n2=None,
                         current_team=None,
                         initial_temperature=200_000.0,
                         cooling_rate=0.99997,
                         biased_swap_prob=0.7):
    """
    Single SA chain.  Returns (best_team_list, best_ev, diags).

    Search space: all riders subject to budget / team / count constraints.
    No tier filtering — cheap riders with team-bonus value appear naturally.

    Temperature schedule: T = initial_temperature; decay each iter by cooling_rate.
    objective: 'ev' (default) or 'depth' (maximise expected top-15 count).
    Time-based safety stop: exits after max_seconds regardless of n_iter.
    verbose: log team snapshot at key iterations (used for first chain only).

    Biased swap (`biased_swap_prob`): swap lowest-EV non-forced slot for a top-50-EV
    candidate. Random swap otherwise: pure exploration across full pool.

    S17-22 hyperparameter override surface: initial_temperature, cooling_rate,
    biased_swap_prob accept per-strategy overrides; defaults preserve the
    pre-S17-22 behavior (so non-overridden strategies remain bit-identical).
    """
    rng = random.Random(seed)

    forced_set   = set(force_in_names  or [])
    excluded_set = set(force_out_names or [])

    forced = [r for r in all_riders if r['name'] in forced_set]
    pool   = [r for r in all_riders
              if r['name'] not in excluded_set and r['name'] not in forced_set]

    n_forced = len(forced)

    # Pre-compute EV cache from probs (total_ev already set by add_stage_evs)
    ev_cache = {r['name']: probs.get(r['name'], {}).get('total_ev', 0.0) for r in pool}
    ev_cache.update({r['name']: probs.get(r['name'], {}).get('total_ev', 0.0) for r in forced})

    # Pre-sort pool for biased swaps: top-50 by EV
    sorted_pool  = sorted(pool, key=lambda r: ev_cache[r['name']], reverse=True)
    top_n_pool   = sorted_pool[:min(50, len(sorted_pool))]
    top_n_len    = len(top_n_pool)
    pool_len     = len(pool)

    # Initial solution
    team = get_valid_random_team(forced, pool, budget, rng=rng)
    if team is None:
        return None, 0.0, {'iters': 0, 'accepts': 0, 'rejects': 0, 'skips': 0,
                           'acceptance_rate': 0.0}

    # Mutable state
    current_score = compute_objective(team, probs, all_riders, objective,
                                      cost_n1, cost_n2, team_n1, team_n2,
                                      current_team=current_team)
    best_team     = team[:]
    best_score    = current_score

    # S17-21 multi-start diagnostics: count proposal outcomes per chain.
    accepts = 0    # delta>0 OR Boltzmann-accepted moves
    rejects = 0    # valid proposals that were Boltzmann-rejected
    skips   = 0    # proposals invalidated before scoring (already-in-team / budget / team-cap)

    T       = float(initial_temperature)
    cooling = float(cooling_rate)

    start = time.time()
    i = 0
    while i < n_iter:
        if time.time() - start > max_seconds:
            _sa_logger.info(
                f"SA stopping at iter {i} after {max_seconds}s (seed={seed}, obj={objective})"
            )
            break

        if verbose and i in _SA_LOG_ITERS:
            team_evs = sorted(
                [(r['name'], r.get('price', 0), ev_cache.get(r['name'], 0)) for r in team],
                key=lambda x: x[2], reverse=True
            )
            _sa_logger.info(
                f"SA[seed={seed}] iter={i:,} best_ev={best_score/1000:.0f}k "
                f"current_ev={current_score/1000:.0f}k T={T:.0f}"
            )
            for n, p, e in team_evs:
                _sa_logger.info(f"  {n:<35} {p/1e6:.2f}M  ev={e/1000:.0f}k")

        if n_forced >= 8:
            break

        # Biased swap: `biased_swap_prob` exploit (worst-for-top50), rest explore (random)
        if rng.random() < biased_swap_prob:
            out_pos   = min(range(n_forced, 8),
                            key=lambda idx: ev_cache.get(team[idx]['name'], 0))
            new_rider = top_n_pool[rng.randrange(top_n_len)]
        else:
            out_pos   = rng.randrange(n_forced, 8)
            new_rider = pool[rng.randrange(pool_len)]

        if any(new_rider['name'] == r['name'] for r in team):
            skips += 1
            T *= cooling
            i += 1
            continue

        new_team = team[:]
        new_team[out_pos] = new_rider

        if not is_valid(new_team, budget):
            skips += 1
            T *= cooling
            i += 1
            continue

        new_score = compute_objective(new_team, probs, all_riders, objective,
                                      cost_n1, cost_n2, team_n1, team_n2,
                                      current_team=current_team)
        delta     = new_score - current_score

        if delta > 0 or rng.random() < math.exp(delta / max(T, 0.01)):
            accepts += 1
            team          = new_team
            current_score = new_score
            if new_score > best_score:
                best_score = new_score
                best_team  = team[:]
        else:
            rejects += 1

        T *= cooling
        i += 1

    # Always return the true analytical EV (even for depth chains) for fair comparison
    best_ev = compute_team_ev(best_team, probs)
    decisions = accepts + rejects
    diags = {
        'iters':            i,
        'accepts':          accepts,
        'rejects':          rejects,
        'skips':            skips,
        'acceptance_rate':  (accepts / decisions) if decisions else 0.0,
    }
    return best_team, best_ev, diags


# ── Step 6: Team characterisation ────────────────────────────────────────────

def label_team(team, probs, budget=BUDGET):
    """Label team based on actual composition — structural diversity over generic names."""
    prices       = [r.get('price', 0) for r in team]
    total_price  = sum(prices)
    avg_price    = total_price / len(prices) if prices else 0
    has_milan    = any(r['name'] == 'Jonathan Milan' for r in team)
    team_counts  = Counter(_norm_team(r.get('team', '')) for r in team)
    max_same_team = max(team_counts.values()) if team_counts else 1
    # GC rider: climbing affinity > 0.65 AND meaningful win probability (in odds)
    has_gc = any(
        r.get('terrain_affinity', {}).get('climbing', 0) > 0.65
        and probs.get(r['name'], {}).get('top10', 0) > 0.10
        for r in team
    )
    if not has_milan:
        return 'No-Milan upset'
    if has_gc:
        return 'Sprint + GC bridge'
    # Team-bonus before budget-depth: expensive anchor + cheap teammates from same team
    # still reads as a team-bonus play, not a budget roster
    if max_same_team >= 2 and total_price >= 48_000_000:
        return 'Team-bonus concentration'
    if avg_price < 7_000_000:
        return 'Budget-depth sprint'
    return 'Sprint-maximal'


def generate_rationale(team, probs, label):
    """One-sentence rationale for a team."""
    top2   = sorted(team, key=lambda r: probs.get(r['name'], {}).get('win', 0), reverse=True)[:2]
    anchors = ' & '.join(r['name'] for r in top2)
    exp15  = sum(probs.get(r['name'], {}).get('top15', 0) for r in team)
    f_ev   = sum(probs.get(r['name'], {}).get('finish_ev', 0) for r in team)
    return (
        f'{label}: anchored by {anchors}. '
        f'Expected {exp15:.1f} riders in top-15, analytical finish EV {int(f_ev/1000)}k.'
    )


def estimate_forward_pressure(team):
    """Estimate how much transfer pressure this team creates for the next stage."""
    sprinters = sum(1 for r in team if r.get('terrain_affinity', {}).get('sprint', 0) > 0.6)
    climbers  = sum(1 for r in team if r.get('terrain_affinity', {}).get('climbing', 0) > 0.6)
    if sprinters >= 5:
        return {'n2': 'low',    'n3': 'medium'}
    if climbers  >= 4:
        return {'n2': 'medium', 'n3': 'low'}
    return {'n2': 'medium', 'n3': 'medium'}


# ── Step 7: Main entry point — four-strategy optimizer ───────────────────────

def generate_candidate_teams(candidates, probabilities,
                              probs_n1, probs_n2,
                              force_in, force_out, budget,
                              stage_config, scoring, all_riders,
                              current_team=None, seed=None):
    """
    Run four strategy-differentiated SA chains and return all four results.
    No deduplication — each strategy has a distinct objective.

    Strategies:
      optimal      — maximise stage EV
      depth        — maximise expected riders in top-15
      low-transfer — minimise transfer cost to n+1
      lookahead    — EV minus discounted two-stage transfer costs

    seed: base seed (typically from compute_seed). Each strategy uses a
    sub-seed (base_seed XOR strategy_idx) so strategies don't share an
    SA trajectory while still being deterministic. None → legacy hard-coded
    seeds (still deterministic per chain, but Plackett-Luce + initial-team
    shuffle remain unseeded → drift between runs, S16-1 verification noted
    0.7-2.1% non-determinism).
    """
    global rider_ev_cache
    rider_ev_cache = {
        r['name']: probabilities.get(r['name'], {}).get('total_ev', 0.0)
        for r in candidates
    }

    # Forward cost estimation — use current team or fast-optimised proxy
    proxy_seed = (seed ^ 0xF) if seed is not None else 0
    proxy = current_team or fast_optimize(
        candidates, probabilities, all_riders, force_in, force_out, budget,
        seed=proxy_seed,
    )
    cost_n1, cost_n2, n_tr_n1, n_tr_n2, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], candidates, all_riders,
        probs_n1, probs_n2, force_in, force_out, budget,
        seed=seed,
    )

    # ── S17-22 multi-start Phase 2 configuration ──────────────────────────
    # N=10 chains per strategy (uniform; Phase 1.5 N-curve diagnostic
    # justified N=10 as the floor — saturation point for optimal/depth on
    # Stage 3, with margin for stage types we haven't tested).
    # Sub-seeds use a high-byte strategy mask so they don't collide with
    # the existing seed scheme (forward 0xA/0xB, proxy/eval 0xF):
    # chain_seed = base ^ (strategy_xor << 8) ^ chain_xor
    # The 0xC0+i scheme is the seed-nesting property from Phase 1.5: first
    # K chains of N=K' (K<K') are identical to a complete N=K run.
    N_CHAINS = 10
    _CHAIN_XOR_MASKS = tuple(0xC0 + i for i in range(N_CHAINS))
    # Shared simulate_stage evaluation seed: ensures all N candidate teams
    # within a strategy are scored on the same Plackett-Luce random samples
    # for a fair EV-best comparison. Reuses the 0xF mask (independent from
    # the proxy fast_optimize call which also uses 0xF — different code path,
    # different RNG instance).
    eval_seed_shared = (seed ^ 0xF) if seed is not None else None

    # Per-strategy SA hyperparameter overrides (S17-22). Lookahead is
    # Pattern B (Phase 1.5: thin-basin EV-best found 1/50 chains). Sweep
    # results captured in the handoff report select these values.
    # Other strategies use simulated_annealing defaults (initial_T=200_000,
    # cooling=0.99997, biased_swap_prob=0.7) and remain bit-identical to
    # Phase 1.5's N=10 run.
    strategies = [
        {
            'name': 'optimal', 'label': 'Optimal',
            'description': 'Maximise stage EV — best team for today',
            'strategy_xor': 0x1, 'legacy_seed': 42,
            'objective': 'ev', 'max_budget': budget,
            'n_iter': 200_000, 'max_seconds': 5,
            'sa_overrides': {},
        },
        {
            'name': 'depth', 'label': 'Depth maximiser',
            'description': 'Maximise riders in top 15 — targets non-linear depth bonus',
            'strategy_xor': 0x2, 'legacy_seed': 123,
            'objective': 'depth', 'max_budget': budget,
            'n_iter': 200_000, 'max_seconds': 5,
            'sa_overrides': {},
        },
        {
            'name': 'low-transfer', 'label': 'Low transfer cost',
            'description': f'Minimise transfers needed for stage n+1 ({n_tr_n1} expected from optimal)',
            'strategy_xor': 0x3, 'legacy_seed': 777,
            'objective': 'low_transfer', 'max_budget': budget,
            'n_iter': 200_000, 'max_seconds': 5,
            'sa_overrides': {},
        },
        {
            'name': 'lookahead', 'label': 'Two-stage lookahead',
            'description': f'EV minus transfer costs n+1 ({n_tr_n1}) and n+2 ({n_tr_n2})',
            'strategy_xor': 0x4, 'legacy_seed': 2026,
            'objective': 'lookahead', 'max_budget': budget,
            'n_iter': 200_000, 'max_seconds': 5,
            # S17-22 sweep at N=20 against Stage 3 reproducer (May 10):
            # cooling_rate 0.99999 was the only config achieving conv > 1
            # (2/20 vs baseline 1/20). Trades 22k ev_best for reproducibility
            # — see ROADMAP S17-22 closure for the full sweep table.
            'sa_overrides': {'cooling_rate': 0.99999},
        },
    ]

    results = []
    for strategy in strategies:
        # Build the per-strategy chain seeds. Multi-start when a base seed is
        # supplied (the realistic path from server.py /run-optimizer); legacy
        # single-chain fallback when called without a seed.
        chain_seeds = (
            [seed ^ (strategy['strategy_xor'] << 8) ^ m for m in _CHAIN_XOR_MASKS]
            if seed is not None
            else [strategy['legacy_seed']]
        )

        # Run each chain, then evaluate every chain's team with the shared
        # simulate_stage seed so EVs are directly comparable.
        chain_results = []
        sa_overrides = strategy.get('sa_overrides') or {}
        for ci, ch_seed in enumerate(chain_seeds):
            team_ci, _ev_ci, sa_diags = simulated_annealing(
                candidates, probabilities, force_in, force_out,
                budget=strategy['max_budget'],
                n_iter=strategy['n_iter'],
                max_seconds=strategy['max_seconds'],
                seed=ch_seed,
                objective=strategy['objective'],
                # Verbose only on the first chain of optimal — keeps log noise bounded.
                verbose=(strategy['name'] == 'optimal' and ci == 0),
                cost_n1=cost_n1,
                cost_n2=cost_n2,
                team_n1=team_n1,
                team_n2=team_n2,
                **sa_overrides,
                current_team=current_team,
            )
            if team_ci is None:
                continue
            team_ci = topup_team(team_ci, candidates, probabilities, all_riders,
                                 strategy['max_budget'])
            captain_ci = select_captain(team_ci, probabilities)
            eval_seed_for_chain = (
                eval_seed_shared if eval_seed_shared is not None else ch_seed
            )
            sim_ci = simulate_stage(team_ci, probabilities, captain_ci['name'],
                                    all_riders=all_riders,
                                    stage_config=stage_config, scoring=scoring,
                                    seed=eval_seed_for_chain)
            chain_results.append({
                'index':    ci,
                'seed':     ch_seed,
                'team':     team_ci,
                'captain':  captain_ci,
                'sim':      sim_ci,
                'ev':       int(sim_ci['mean']),
                'sa_diags': sa_diags,
                # Team identity: sorted holdet_ids when present, fallback to
                # names. Used to detect convergence across chains.
                'team_id':  tuple(sorted(
                    str(r.get('holdet_id') if r.get('holdet_id') is not None else r.get('name', ''))
                    for r in team_ci
                )),
            })

        if not chain_results:
            continue

        # Pick the EV-best chain. Ties broken by lowest chain index for stability.
        best_idx = max(range(len(chain_results)),
                       key=lambda j: (chain_results[j]['ev'], -chain_results[j]['index']))
        best     = chain_results[best_idx]

        # ── S17-22 best-corroborated reporting ───────────────────────────
        # Count chains per team identity. The "chosen" team is the EV-best;
        # the "best-corroborated" team is the highest-EV team found by ≥2
        # chains, falling back to chosen if no team has count ≥2.
        chain_evs         = [c['ev'] for c in chain_results]
        ev_spread         = max(chain_evs) - min(chain_evs)
        team_count        = Counter(c['team_id'] for c in chain_results)
        chosen_team_count = team_count[best['team_id']]
        # Highest-EV per team_id (each team's chains all share an EV under
        # the shared simulate_stage seed, so any chain's EV is fine).
        team_ev = {}
        for c in chain_results:
            team_ev[c['team_id']] = c['ev']
        corroborated_ids = [tid for tid, cnt in team_count.items() if cnt >= 2]
        if chosen_team_count >= 2:
            corroboration_status      = 'corroborated'
            best_corroborated_ev      = best['ev']
            best_corroborated_count   = chosen_team_count
        elif corroborated_ids:
            best_corr_id = max(corroborated_ids, key=lambda tid: team_ev[tid])
            corroboration_status      = 'single_chain'
            best_corroborated_ev      = team_ev[best_corr_id]
            best_corroborated_count   = team_count[best_corr_id]
        else:
            corroboration_status      = 'no_corroboration'
            best_corroborated_ev      = best['ev']
            best_corroborated_count   = 1

        convergence_meta = {
            'chosen_team_count':       chosen_team_count,
            'n_chains':                len(chain_results),
            'best_seen_ev':            best['ev'],
            'best_corroborated_ev':    int(best_corroborated_ev),
            'best_corroborated_count': best_corroborated_count,
            'corroboration_status':    corroboration_status,
        }

        # ── Diagnostic log ────────────────────────────────────────────────
        diag = {
            'strategy':            strategy['name'],
            'n_chains_attempted':  len(chain_seeds),
            'n_chains_succeeded':  len(chain_results),
            'chosen_chain_index':  best['index'],
            'convergence_count':   chosen_team_count,
            'corroboration':       corroboration_status,
            'ev_spread':           ev_spread,
            'chain_evs':           chain_evs,
            'chain_acceptance':    [round(c['sa_diags']['acceptance_rate'], 3) for c in chain_results],
            'chain_iters':         [c['sa_diags']['iters'] for c in chain_results],
        }
        _log_optimizer(f"sa-multistart {json.dumps(diag, default=str)}")

        # Adopt the EV-best chain's outputs for the rest of the result-assembly.
        team    = best['team']
        captain = best['captain']
        sim     = best['sim']

        actual_cost_n1 = compute_transfer_cost(team, team_n1 or []) if team_n1 else 0
        actual_cost_n2 = compute_transfer_cost(team_n1 or [], team_n2 or []) if team_n1 and team_n2 else 0
        actual_n_tr_n1 = len([r for r in (team_n1 or [])
                               if r['name'] not in {x['name'] for x in team}])
        actual_n_tr_n2 = len([r for r in (team_n2 or [])
                               if r['name'] not in {x['name'] for x in (team_n1 or [])}])

        # Cost and transfers from user's current team → this candidate
        cur_names = {r['name'] for r in (current_team or [])}
        transfer_cost = int(compute_transfer_cost(current_team or [], team))
        n_transfers   = len([r for r in team if r['name'] not in cur_names])
        ev_net        = int(sim['mean']) - transfer_cost

        # Inject transfer_cost as a negative component into the breakdown
        breakdown = dict(sim['breakdown'])
        if transfer_cost > 0:
            breakdown['transfer_cost'] = -transfer_cost

        results.append({
            'label':         strategy['label'],
            'strategy':      strategy['name'],
            'description':   strategy['description'],
            'riders':        team,
            'total_price':   sum(r.get('price', 0) for r in team),
            'ev_estimate':   int(sim['mean']),
            'ev_net':        ev_net,
            'ev_breakdown':  breakdown,
            'transfer_cost': transfer_cost,
            'n_transfers':   n_transfers,
            'cdf':           sim['cdf'],
            'captain':       captain,
            'forward': {
                'transfers_n1': actual_n_tr_n1,
                'cost_n1':      int(actual_cost_n1),
                'transfers_n2': actual_n_tr_n2,
                'cost_n2':      int(actual_cost_n2),
                'total_forward_cost': int(actual_cost_n1 + actual_cost_n2 * LOOKAHEAD_DISCOUNT),
            },
            'convergence': convergence_meta,
            'rationale': strategy['description'],
        })

    return results  # always return all four


# ── Captain selection ─────────────────────────────────────────────────────────

def _ev_single(name, probs):
    """Single-rider total EV — finish + sprint + jersey + GC (used by select_captain)."""
    p = probs.get(name, {})
    return p.get('total_ev', p.get('finish_ev', 0.0))


def select_captain(team_riders, all_probs):
    """Select captain as rider with highest total single-rider EV (all scoring components)."""
    best_name, best_ev = None, -1.0
    for r in team_riders:
        name = r['name'] if isinstance(r, dict) else r
        ev   = _ev_single(name, all_probs)
        if ev > best_ev:
            best_ev, best_name = ev, name

    p       = all_probs.get(best_name, {})
    top3pct = p.get('top3', 0) * 100
    return {
        'name': best_name,
        'rationale': (
            f'{best_name} has the highest total EV in the team '
            f'(~{int(best_ev / 1000)}k doubled as captain, {top3pct:.0f}% top-3). '
            f'Includes sprint points, jersey, and GC bonus upside.'
        ),
    }


# ── Monte Carlo simulation (Plackett-Luce) ────────────────────────────────────

def simulate_stage(team_riders, all_probs, captain_name, all_riders=None,
                   n_sims=10_000, stage_config=None, scoring=None, seed=None):
    """
    Simulate n_sims stage outcomes using Plackett-Luce sampling.

    Scoring: stage finish · sprint (final + intermediates) · jersey · GC bonus ·
             KOM/climb points · team bonus · depth bonus.
    Captain: ALL positive per-rider components are doubled.

    stage_config: dict from stage_scoring.json['stages']['N']
    scoring:      full stage_scoring.json dict
    seed:         int for the Plackett-Luce RNG. None → unseeded (legacy).
    Returns {'mean', 'cdf': {p25,p50,p75,p90}, 'breakdown': {...}}.
    """
    if stage_config is None:
        stage_config = {}
    if scoring is None:
        scoring = {}

    pv          = scoring.get('point_value_kr', POINT_VALUE)
    sprint_pts_raw = stage_config.get('sprint_points', SPRINT_POINTS_FINAL)
    sprint_kr   = [p * pv for p in sprint_pts_raw]
    n_inter     = stage_config.get('n_intermediate_sprints', 1)
    inter_pts_raw = scoring.get('intermediate_sprint_points', SPRINT_POINTS_INTERMEDIATE)
    inter_kr    = [p * pv for p in inter_pts_raw]
    climbs      = stage_config.get('climbs', [])
    sprint_type = stage_config.get('sprint_type', 'A')

    rng = np.random.default_rng(seed)

    field_names = list(all_probs.keys())
    field_probs = np.array([all_probs[n]['win'] for n in field_names], dtype=np.float64)
    name_to_idx = {n: i for i, n in enumerate(field_names)}

    for r in team_riders:
        if r['name'] not in name_to_idx:
            field_names.append(r['name'])
            field_probs = np.append(field_probs, 1e-6)
            name_to_idx[r['name']] = len(field_names) - 1

    n_field     = len(field_names)
    field_probs = field_probs / field_probs.sum()

    team_idxs = np.array([name_to_idx[r['name']] for r in team_riders])
    team_real  = [r.get('team', '') for r in team_riders]
    capt_ti    = next((i for i, r in enumerate(team_riders) if r['name'] == captain_name), 0)

    rmap = {r['name']: r.get('team', '') for r in (all_riders or [])}
    for r in team_riders:
        rmap[r['name']] = r.get('team', '')
    field_real = np.array([rmap.get(n, '') for n in field_names])

    # Plackett-Luce: score_i = -log(U_i) / p_i → argsort = finish order
    u      = rng.uniform(1e-12, 1.0, (n_sims, n_field))
    scores = -np.log(u) / field_probs
    order  = np.argsort(scores, axis=1)
    rank   = np.argsort(order,  axis=1)

    team_pos = rank[:, team_idxs]   # (n_sims, 8), 0-indexed finish positions

    # ── Stage finish ──────────────────────────────────────────────────────────
    fp_lookup  = np.array(FINISH_POINTS, dtype=np.float64)
    finish_pts = np.where(team_pos < 15, fp_lookup[np.minimum(team_pos, 14)], 0.0)

    # ── Sprint points (zero on Type C mountain stages) ────────────────────────
    stage_type = sprint_type_to_stage_type(sprint_type)
    if stage_type in ('sprint', 'hilly') and sprint_kr:
        sp_lkp = np.zeros(n_field, dtype=np.float64)
        for i, kr in enumerate(sprint_kr):
            if i < n_field:
                sp_lkp[i] = kr
        sprint_pts = np.where(team_pos < len(sprint_kr),
                              sp_lkp[np.minimum(team_pos, n_field - 1)], 0.0)
        if n_inter > 0 and inter_kr:
            si_lkp = np.zeros(n_field, dtype=np.float64)
            for i, kr in enumerate(inter_kr):
                if i < n_field:
                    si_lkp[i] = kr
            sprint_pts = sprint_pts + np.where(
                team_pos < len(inter_kr),
                si_lkp[np.minimum(team_pos, n_field - 1)], 0.0
            ) * n_inter
    else:
        sprint_pts = np.zeros_like(finish_pts)

    # ── Jersey bonus ──────────────────────────────────────────────────────────
    winner_jersey = float(
        JERSEY_BONUS['gc'] + (JERSEY_BONUS['points'] if sprint_type == 'A' else 0)
    )
    jersey_pts = np.where(team_pos == 0, winner_jersey, 0.0)

    # ── GC bonus ─────────────────────────────────────────────────────────────
    gc_lkp = np.zeros(n_field, dtype=np.float64)
    for pos_1idx, bonus in GC_BONUS.items():
        if pos_1idx - 1 < n_field:
            gc_lkp[pos_1idx - 1] = float(bonus)
    gc_pts = np.where(team_pos < 10, gc_lkp[np.minimum(team_pos, n_field - 1)], 0.0)

    # ── KOM points (all categorised climbs on this stage) ────────────────────
    kom_pts = np.zeros_like(finish_pts)
    for climb in climbs:
        cat = climb.get('cat')
        if cat == 'cima_coppi':
            cat_key = 'cima_coppi'
        elif climb.get('at_finish') and cat == 1:
            cat_key = 'cat1_finish'
        else:
            cat_key = f'cat{cat}'
        cp   = scoring.get('climb_points', {}).get(cat_key, {})
        cpts = cp.get('points', [])
        if cpts:
            kl = np.zeros(n_field, dtype=np.float64)
            for i, p in enumerate(cpts):
                if i < n_field:
                    kl[i] = p * pv
            kom_pts += np.where(team_pos < len(cpts),
                                kl[np.minimum(team_pos, n_field - 1)], 0.0)

    # ── Depth bonus ───────────────────────────────────────────────────────────
    depth_cnt = (team_pos < 15).sum(axis=1)
    depth_pts = np.array(
        [DEPTH_BONUS[min(int(d), 8)] for d in depth_cnt], dtype=np.float64
    )

    # ── Team bonus ────────────────────────────────────────────────────────────
    team_bonus = np.zeros(n_sims, dtype=np.float64)
    for pos_off, bval in TEAM_BONUS_MAP.items():
        top_fidx  = order[:, pos_off]
        top_rteam = field_real[top_fidx]
        for rteam in team_real:
            if rteam:
                team_bonus += (top_rteam == rteam).astype(np.float64) * bval

    # ── Captain doubles ALL positive per-rider components ────────────────────
    rider_totals  = finish_pts + sprint_pts + jersey_pts + gc_pts + kom_pts
    cap_total     = rider_totals[:, capt_ti]
    captain_bonus = np.maximum(cap_total, 0.0)

    stage_totals  = finish_pts.sum(axis=1)
    sprint_totals = sprint_pts.sum(axis=1)
    jersey_totals = jersey_pts.sum(axis=1)
    gc_totals     = gc_pts.sum(axis=1)
    kom_totals    = kom_pts.sum(axis=1)
    totals        = rider_totals.sum(axis=1) + captain_bonus + depth_pts + team_bonus

    s = np.sort(totals)
    return {
        'mean': float(totals.mean()),
        'cdf':  {
            'p25': int(s[int(0.25 * n_sims)]),
            'p50': int(s[int(0.50 * n_sims)]),
            'p75': int(s[int(0.75 * n_sims)]),
            'p90': int(s[int(0.90 * n_sims)]),
        },
        'breakdown': {
            'stage_finish':  int(stage_totals.mean()),
            'sprint_points': int(sprint_totals.mean()),
            'jersey_bonus':  int(jersey_totals.mean()),
            'gc_bonus':      int(gc_totals.mean()),
            'kom_points':    int(kom_totals.mean()),
            'captain_bonus': int(captain_bonus.mean()),
            'team_bonus':    int(team_bonus.mean()),
            'depth_bonus':   int(depth_pts.mean()),
        },
    }
