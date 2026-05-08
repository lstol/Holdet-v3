"""
claude/engine/optimizer.py
Python Monte Carlo optimizer for Holdet fantasy cycling.

Search: Simulated Annealing — 5 independent chains, single objective function.
Scoring: Plackett-Luce Monte Carlo on final candidates (exact CDF).

Hard constraints (enforced throughout):
  - Budget ≤ 50,000,000 kr
  - Exactly 8 riders
  - Max 2 riders from the same real-world team
"""

import math
import re
import random
import time
from collections import Counter, defaultdict

import numpy as np

# ── Scoring constants ─────────────────────────────────────────────────────────

BUDGET = 50_000_000

FINISH_POINTS = [
    200_000, 150_000, 130_000, 120_000, 110_000, 100_000,
     95_000,  90_000,  85_000,  80_000,  70_000,  55_000,
     40_000,  30_000,  15_000,
]

DEPTH_BONUS = {
    0:       0,
    1:       0,
    2:  20_000,
    3:  50_000,
    4:  90_000,
    5: 140_000,
    6: 200_000,
    7: 270_000,
    8: 350_000,
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
                        stage_config=None, scoring=None):
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
        if o.get('top3_pct') is not None:
            top3_map[name]  = o['top3_pct']  / 100.0
        if o.get('top10_pct') is not None:
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

def get_valid_random_team(forced, pool, budget):
    """
    Return a random valid team by shuffling pool and greedily filling.
    Returns None if no valid team found after many attempts.
    """
    for _ in range(5_000):
        shuffled = pool[:]
        random.shuffle(shuffled)

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


def simulated_annealing(all_riders, probs, force_in_names, force_out_names,
                         budget=BUDGET, n_iter=2_000_000, seed=42,
                         max_seconds=9, objective='ev'):
    """
    Single SA chain.  Returns (best_team_list, best_ev).

    Search space: all riders subject to budget / team / count constraints.
    No tier filtering — cheap riders with team-bonus value appear naturally.

    Temperature schedule: T₀ = 200,000, decay = 0.999993.
    objective: 'ev' (default) or 'depth' (maximise expected top-15 count).
    Time-based safety stop: exits after max_seconds regardless of n_iter.
    """
    rng = random.Random(seed)

    forced_set  = set(force_in_names  or [])
    excluded_set= set(force_out_names or [])

    forced = [r for r in all_riders if r['name'] in forced_set]
    pool   = [r for r in all_riders
              if r['name'] not in excluded_set and r['name'] not in forced_set]

    n_forced = len(forced)

    # Initial solution
    team = get_valid_random_team(forced, pool, budget)
    if team is None:
        return None, 0.0

    # Mutable state
    current_score = _compute_objective(team, probs, objective)
    best_team     = team[:]
    best_score    = current_score

    T        = 200_000.0
    cooling  = 0.999993
    pool_len = len(pool)

    start = time.time()
    i = 0
    while i < n_iter:
        if time.time() - start > max_seconds:
            import logging
            logging.getLogger(__name__).info(
                f"SA stopping at iter {i} after {max_seconds}s (seed={seed}, obj={objective})"
            )
            break

        if n_forced >= 8:
            break
        out_pos   = rng.randrange(n_forced, 8)
        new_rider = pool[rng.randrange(pool_len)]

        if any(new_rider['name'] == r['name'] for r in team):
            T *= cooling
            i += 1
            continue

        new_team = team[:]
        new_team[out_pos] = new_rider

        if not is_valid(new_team, budget):
            T *= cooling
            i += 1
            continue

        new_score = _compute_objective(new_team, probs, objective)
        delta     = new_score - current_score

        if delta > 0 or rng.random() < math.exp(delta / max(T, 0.01)):
            team          = new_team
            current_score = new_score
            if new_score > best_score:
                best_score = new_score
                best_team  = team[:]

        T *= cooling
        i += 1

    # Always return the true analytical EV (even for depth chains) for fair comparison
    best_ev = compute_team_ev(best_team, probs)
    return best_team, best_ev


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


# ── Step 7: Main entry point ──────────────────────────────────────────────────

def generate_candidate_teams(all_riders, probs, force_in_names, force_out_names,
                              budget=BUDGET, stage_config=None, scoring=None):
    """
    Run 7 strategy-differentiated SA chains (target: ~60 s total, 9 s each).

    Chains:
      0. ev-maximal        — unconstrained EV (seed 42)
      1. ev-maximal-v2     — unconstrained EV, different seed (seed 123)
      2. team-bonus        — force best available real-world team pair (seed 777)
      3. depth-maximiser   — depth-weighted objective, top-15 coverage (seed 2026)
      4. budget-war-chest  — budget capped at 88% of available (seed 99)
      5. no-favourite      — exclude highest-win-prob rider (seed 314)
      6. gc-bridge         — force GC climbing specialist (seed 555)

    Deduplication: drop teams sharing >6 riders with a higher-EV team.
    Min-EV filter: drop teams below 50% of best analytical EV (degenerate solutions).
    """
    full_roster     = all_riders
    user_forced_set = set(force_in_names  or [])
    user_excluded   = set(force_out_names or [])

    # Validate user-forced riders
    user_forced       = [r for r in all_riders if r['name'] in user_forced_set]
    user_forced_price = sum(r.get('price', 0) for r in user_forced)
    if user_forced_price > budget:
        raise ValueError(f'Force-in riders cost {user_forced_price:,} > budget {budget:,}')
    ftc = defaultdict(int)
    for r in user_forced:
        ftc[_norm_team(r.get('team', ''))] += 1
        if ftc[_norm_team(r.get('team', ''))] > 2:
            raise ValueError(f'Force-in has >2 riders from {r.get("team","?")}')

    # Top win rider (excluded in no-favourite chain)
    top_win_rider = None
    for r in sorted(all_riders, key=lambda r: probs.get(r['name'], {}).get('win', 0), reverse=True):
        if r['name'] not in user_excluded and r['name'] not in user_forced_set:
            top_win_rider = r['name']
            break

    # GC anchor: best climbing specialist with meaningful odds
    gc_anchor = None
    for r in sorted(all_riders, key=lambda r: probs.get(r['name'], {}).get('top10', 0), reverse=True):
        if (r['name'] not in user_excluded
                and r['name'] not in user_forced_set
                and r.get('terrain_affinity', {}).get('climbing', 0) > 0.65
                and probs.get(r['name'], {}).get('top10', 0) > 0.10):
            gc_anchor = r['name']
            break

    strategies = [
        # 0 — unconstrained EV optimum
        {'name': 'ev-maximal',       'seed': 42,   'objective': 'ev',
         'riders': all_riders,
         'force_in':  list(user_forced_set),
         'force_out': list(user_excluded),
         'budget': budget},
        # 1 — EV optimum, different starting point
        {'name': 'ev-maximal-v2',    'seed': 123,  'objective': 'ev',
         'riders': all_riders,
         'force_in':  list(user_forced_set),
         'force_out': list(user_excluded),
         'budget': budget},
        # 2 — EV optimum, third seed — SA finds team-bonus pairs naturally
        {'name': 'team-bonus',       'seed': 777,  'objective': 'ev',
         'riders': all_riders,
         'force_in':  list(user_forced_set),
         'force_out': list(user_excluded),
         'budget': budget},
        # 3 — depth-weighted objective: maximise expected riders in top-15
        {'name': 'depth-maximiser',  'seed': 2026, 'objective': 'depth',
         'riders': all_riders,
         'force_in':  list(user_forced_set),
         'force_out': list(user_excluded),
         'budget': budget},
        # 4 — budget war chest: spend only 88% to preserve transfers
        {'name': 'budget-war-chest', 'seed': 99,   'objective': 'ev',
         'riders': all_riders,
         'force_in':  list(user_forced_set),
         'force_out': list(user_excluded),
         'budget': int(budget * 0.88)},
        # 5 — no-favourite: exclude highest win-probability rider
        {'name': 'no-favourite',     'seed': 314,  'objective': 'ev',
         'riders': all_riders,
         'force_in':  list(user_forced_set),
         'force_out': list(user_excluded) + ([top_win_rider] if top_win_rider else []),
         'budget': budget},
        # 6 — GC bridge: force in best climbing specialist
        {'name': 'gc-bridge',        'seed': 555,  'objective': 'ev',
         'riders': all_riders,
         'force_in':  list(user_forced_set) + ([gc_anchor] if gc_anchor else []),
         'force_out': list(user_excluded),
         'budget': budget},
    ]

    raw_results = []
    for strat in strategies:
        team, ev = simulated_annealing(
            strat['riders'], probs, strat['force_in'], strat['force_out'],
            budget=strat['budget'], n_iter=2_000_000, seed=strat['seed'],
            max_seconds=9, objective=strat['objective'],
        )
        if team is not None:
            raw_results.append((ev, team, strat['name']))

    if not raw_results:
        return []

    # Filter degenerate solutions: drop teams below 50% of best analytical EV
    max_ev = max(ev for ev, _, _ in raw_results)
    raw_results = [(ev, team, name) for ev, team, name in raw_results
                   if ev > 0.5 * max_ev]

    # Deduplicate: discard any team sharing >6 riders with a higher-EV team
    raw_results.sort(key=lambda x: x[0], reverse=True)
    distinct = []
    for ev, team, name in raw_results:
        names = {r['name'] for r in team}
        if not any(len(names & {r['name'] for r in t}) > 6 for _, t, _ in distinct):
            distinct.append((ev, team, name))

    # Run full Monte Carlo on each distinct team
    candidates = []
    for _, team, strat_name in distinct[:5]:
        total_price = sum(r.get('price', 0) for r in team)
        assert total_price <= budget, (
            f"Budget violation: team costs {total_price:,} > budget {budget:,} "
            f"(riders: {[r['name'] for r in team]})"
        )
        cap = select_captain(team, probs)
        sim = simulate_stage(team, probs, cap['name'], all_riders=full_roster,
                             stage_config=stage_config, scoring=scoring)
        lbl = label_team(team, probs, budget)
        candidates.append({
            'label':            lbl,
            'riders':           team,
            'total_price':      total_price,
            'ev_estimate':      int(sim['mean']),
            'ev_breakdown':     sim['breakdown'],
            'cdf':              sim['cdf'],
            'forward_pressure': estimate_forward_pressure(team),
            'rationale':        generate_rationale(team, probs, lbl),
            'captain':          cap,
        })

    return sorted(candidates, key=lambda x: x['ev_estimate'], reverse=True)


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
                   n_sims=10_000, stage_config=None, scoring=None):
    """
    Simulate n_sims stage outcomes using Plackett-Luce sampling.

    Scoring: stage finish · sprint (final + intermediates) · jersey · GC bonus ·
             KOM/climb points · team bonus · depth bonus.
    Captain: ALL positive per-rider components are doubled.

    stage_config: dict from stage_scoring.json['stages']['N']
    scoring:      full stage_scoring.json dict
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

    rng = np.random.default_rng()

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
