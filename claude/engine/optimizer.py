"""
claude/engine/optimizer.py
Python Monte Carlo optimizer for Holdet fantasy cycling.

Hard-enforces:
  - Budget ≤ 50,000,000 kr
  - Exactly 8 riders
  - Max 2 riders from the same real-world team
  - Force-in / force-out constraints

Simulation uses Plackett-Luce sampling (vectorised with numpy).
"""

import re
import random
from collections import defaultdict

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

# 0-indexed position offset → bonus per fantasy rider from that real-world team
TEAM_BONUS_MAP = {0: 60_000, 1: 30_000, 2: 20_000}

INTEL_MULT = {
    ('up',      'strong'):   1.20,
    ('up',      'moderate'): 1.10,
    ('up',      'weak'):     1.05,
    ('down',    'strong'):   0.75,
    ('down',    'moderate'): 0.85,
    ('down',    'weak'):     0.95,
}


# ── Step 1: Build probabilities ───────────────────────────────────────────────

def build_probabilities(all_riders, odds, intel, sliders=None):
    """
    Returns dict: {rider_name: {'win': p, 'top3': p, 'top10': p, 'top15': p}}
    All probabilities in [0, 1].

    1. Start from bookmaker win_pct (already averaged, in odds list).
    2. Apply intel direction/strength multipliers.
    3. Renormalise so all win probs sum to 1.0.
    4. Derive top-3/10/15 from win probability.
       Riders absent from odds get P(win)≈0, P(top15)=0.05.
    """
    # Odds lookup: name → fraction (e.g. 5.2% → 0.052)
    odds_map = {
        o['name']: o.get('win_pct', 0) / 100.0
        for o in odds if o.get('name')
    }
    in_odds = set(n for n, p in odds_map.items() if p > 0)

    # Dynamic EPS: give non-odds riders collectively ~20% of probability mass.
    # This ensures the simulation has realistic variance — in real races, peloton
    # riders do occasionally infiltrate the top 15, bumping favorites out.
    # Formula: EPS = 0.25 * raw_odds_total / n_non_odds  →  after renorm ≈ 20%.
    raw_odds_total = sum(odds_map.values())
    n_non_odds = max(len(all_riders) - len(in_odds), 1)
    EPS = max(1e-5, 0.25 * raw_odds_total / n_non_odds)

    # Intel adjustment lookup
    adj = {}
    if isinstance(intel, dict):
        src = intel.get('intel', intel)      # handle both raw and wrapped formats
        if isinstance(src, dict):
            for sig in src.get('key_signals', []):
                key = (sig.get('direction', 'neutral'), sig.get('strength', 'weak'))
                mult = INTEL_MULT.get(key, 1.0)
                if sig.get('rider'):
                    adj[sig['rider']] = mult

    # Raw win probabilities with intel adjustments
    raw = {}
    for r in all_riders:
        name = r['name']
        base = odds_map.get(name, 0.0)
        raw[name] = base * adj.get(name, 1.0)

    # Assign EPS to riders with zero probability (Plackett-Luce stability)
    for name in raw:
        if raw[name] == 0:
            raw[name] = EPS

    # Renormalise
    total = sum(raw.values())
    if total > 0:
        for name in raw:
            raw[name] /= total

    # Build probability dicts
    result = {}
    for r in all_riders:
        name = r['name']
        pw = raw.get(name, EPS)
        if name in in_odds:
            result[name] = {
                'win':   pw,
                'top3':  min(0.95, pw * 3.5),
                'top10': min(0.95, pw * 8.0),
                'top15': min(0.95, pw * 12.0),
            }
        else:
            result[name] = {
                'win':   pw,
                'top3':  0.02,
                'top10': 0.04,
                'top15': 0.05,
            }

    return result


# ── Step 2: Monte Carlo simulation ────────────────────────────────────────────

def simulate_stage(team_riders, all_probs, captain_name, all_riders=None, n_sims=10_000):
    """
    Simulate n_sims stage outcomes using Plackett-Luce sampling.

    team_riders : list of rider dicts with 'name' and 'team'
    all_probs   : full probability dict (all active riders)
    captain_name: string name of the captain
    all_riders  : full field list (used for real-world team lookup in team bonus)

    Returns {'mean', 'cdf', 'breakdown'}
    """
    rng = np.random.default_rng()

    # Build full field
    field_names = list(all_probs.keys())
    field_probs = np.array([all_probs[n]['win'] for n in field_names], dtype=np.float64)
    name_to_idx = {n: i for i, n in enumerate(field_names)}

    # Ensure every team rider is in the field
    for r in team_riders:
        if r['name'] not in name_to_idx:
            field_names.append(r['name'])
            field_probs = np.append(field_probs, 1e-6)
            name_to_idx[r['name']] = len(field_names) - 1

    n_field = len(field_names)
    field_probs = field_probs / field_probs.sum()   # final normalisation

    # Team rider indices into field array
    team_idxs = np.array([name_to_idx[r['name']] for r in team_riders])
    team_real  = [r.get('team', '') for r in team_riders]
    capt_ti    = next((i for i, r in enumerate(team_riders) if r['name'] == captain_name), 0)

    # Real-world teams for the full field (team bonus calculation)
    rmap = {r['name']: r.get('team', '') for r in (all_riders or [])}
    for r in team_riders:
        rmap[r['name']] = r.get('team', '')
    field_real = np.array([rmap.get(n, '') for n in field_names])

    # ── Plackett-Luce: sample finish order ───────────────────────────────────
    # score_i = -log(U_i) / p_i  →  argsort ascending = finish order
    u      = rng.uniform(1e-12, 1.0, (n_sims, n_field))
    scores = -np.log(u) / field_probs               # (n_sims, n_field)
    order  = np.argsort(scores, axis=1)              # (n_sims, n_field) finish order
    rank   = np.argsort(order,  axis=1)              # (n_sims, n_field) finish position per rider

    team_pos = rank[:, team_idxs]                    # (n_sims, 8)

    # Stage finish points
    fp_lookup  = np.array(FINISH_POINTS, dtype=np.float64)
    finish_pts = np.where(
        team_pos < 15,
        fp_lookup[np.minimum(team_pos, 14)],
        0.0,
    )                                                # (n_sims, 8)

    # Captain bonus: double positive outcomes → add once more
    cap_pts      = finish_pts[:, capt_ti]
    captain_bonus = np.maximum(cap_pts, 0.0)        # (n_sims,)

    # Depth bonus: non-linear, based on count of team riders in top 15
    depth_cnt = (team_pos < 15).sum(axis=1)         # (n_sims,)
    depth_pts = np.array(
        [DEPTH_BONUS[min(int(d), 8)] for d in depth_cnt],
        dtype=np.float64,
    )

    # Team bonus: for each top-3 position, check if any team rider shares that real-world team
    team_bonus = np.zeros(n_sims, dtype=np.float64)
    for pos_off, bval in TEAM_BONUS_MAP.items():
        top_fidx  = order[:, pos_off]               # (n_sims,) field index of finisher
        top_rteam = field_real[top_fidx]            # (n_sims,) real-world team of finisher
        for rteam in team_real:
            if rteam:
                team_bonus += (top_rteam == rteam).astype(np.float64) * bval

    stage_totals = finish_pts.sum(axis=1)           # (n_sims,)
    totals = stage_totals + captain_bonus + depth_pts + team_bonus

    s = np.sort(totals)
    return {
        'mean': float(totals.mean()),
        'cdf': {
            'p25': int(s[int(0.25 * n_sims)]),
            'p50': int(s[int(0.50 * n_sims)]),
            'p75': int(s[int(0.75 * n_sims)]),
            'p90': int(s[int(0.90 * n_sims)]),
        },
        'breakdown': {
            'stage_finish':  int(stage_totals.mean()),
            'captain_bonus': int(captain_bonus.mean()),
            'team_bonus':    int(team_bonus.mean()),
            'depth_bonus':   int(depth_pts.mean()),
            'gc_bonus':      0,
        },
    }


# ── Step 3: Team generation ───────────────────────────────────────────────────

def _norm_team(name):
    """
    Normalise a real-world team name for constraint counting.

    The riders.json has several name-variant pairs for the same team, e.g.:
      'Tudor Pro Cycling'  vs 'Tudor Pro Cycling Team'
      'Lidl-Trek'          vs 'Lidl - Trek'
      'XDS Astana'         vs 'XDS Astana Team'
      'Netcompany INEOS'   vs 'Netcompany INEOS Cycling Team'
      'Red Bull BORA hansgrohe' vs 'Red Bull - BORA - hansgrohe'
      'EF Education EasyPost'   vs 'EF Education - EasyPost'

    Strategy: lowercase, replace all punctuation separators with space,
    remove the words 'team' and 'cycling', collapse whitespace.
    """
    n = re.sub(r'[^\w\s]', ' ', (name or '').lower())  # punct/hyphens → space
    n = re.sub(r'\bcycling\b', '', n)                   # drop word 'cycling'
    n = re.sub(r'\bteam\b', '', n)                      # drop word 'team'
    return re.sub(r'\s+', ' ', n).strip()               # collapse spaces


def _ev_single(name, probs):
    """Simple single-rider EV estimate (no team interaction)."""
    p    = probs.get(name, {})
    pw   = p.get('win',   0.0)
    pt3  = p.get('top3',  0.0)
    pt10 = p.get('top10', 0.0)
    pt15 = p.get('top15', 0.0)
    ev   = (
        pw                    * FINISH_POINTS[0]
        + max(0, pt3  - pw)   * (FINISH_POINTS[1] + FINISH_POINTS[2])     / 2
        + max(0, pt10 - pt3)  * sum(FINISH_POINTS[3:10])                  / 7
        + max(0, pt15 - pt10) * sum(FINISH_POINTS[10:15])                 / 5
    )
    return max(0.0, ev)


def _greedy_fill(seed, pool, budget, key_fn, n=8, budget_reserve=False):
    """
    Greedily fill a team from pool, sorted descending by key_fn.
    Returns a list of n rider dicts, or None if the target size cannot be reached.
    Hard constraints: budget, max 2 per real-world team (normalised names).

    budget_reserve=True: before picking a rider, ensure the remaining budget after
    the pick is still enough to fill the remaining slots at minimum pool price.
    This prevents early expensive picks from leaving no room for later slots.
    """
    team        = list(seed)
    team_names  = {r['name'] for r in team}
    team_counts = defaultdict(int)
    for r in team:
        team_counts[_norm_team(r.get('team', ''))] += 1
    rem = budget - sum(r['price'] for r in team)

    min_price = min((r['price'] for r in pool), default=0) if budget_reserve else 0
    sorted_pool = sorted(pool, key=key_fn, reverse=True)

    for r in sorted_pool:
        if len(team) >= n:
            break
        if r['name'] in team_names:
            continue
        if team_counts[_norm_team(r.get('team', ''))] >= 2:
            continue
        # Budget check: must leave enough for the remaining slots after this pick
        slots_after = n - len(team) - 1
        reserve = slots_after * min_price
        if r['price'] > rem - reserve:
            continue
        team.append(r)
        team_names.add(r['name'])
        team_counts[_norm_team(r.get('team', ''))] += 1
        rem -= r['price']

    return team if len(team) == n else None


def _forward_pressure(team_riders):
    """Estimate forward transfer pressure from team composition."""
    sprinters = sum(
        1 for r in team_riders
        if r.get('terrain_affinity', {}).get('sprint', 0) > 0.6
    )
    climbers = sum(
        1 for r in team_riders
        if r.get('terrain_affinity', {}).get('climbing', 0) > 0.6
    )
    if sprinters >= 5:
        return {'n2': 'low', 'n3': 'medium'}
    if climbers >= 4:
        return {'n2': 'medium', 'n3': 'low'}
    return {'n2': 'medium', 'n3': 'medium'}


def generate_candidate_teams(all_riders, probs, force_in_names, force_out_names,
                              budget=BUDGET):
    """
    Generate up to 5 structurally distinct candidate teams.

    Strategies:
      1. EV-greedy       — maximise single-rider EV
      2. Depth play      — maximise P(top15) for depth bonus
      3. Top-3 anchor    — lock top favourites, cheapest fill
      4. Balanced        — terrain-affinity weighted EV
      5. Best of random  — best team from 100 random valid attempts
    """
    forced_names = set(force_in_names or [])
    excluded     = set(force_out_names or [])

    forced = [r for r in all_riders if r['name'] in forced_names]
    pool   = [r for r in all_riders
              if r['name'] not in excluded and r['name'] not in forced_names]

    # Validate forced riders
    forced_price = sum(r['price'] for r in forced)
    if forced_price > budget:
        raise ValueError(f'Force-in riders cost {forced_price:,} which exceeds budget {budget:,}')
    ftc = defaultdict(int)
    for r in forced:
        ftc[_norm_team(r.get('team', ''))] += 1
        if ftc[_norm_team(r.get('team', ''))] > 2:
            raise ValueError(f'Force-in has >2 riders from {r.get("team","?")}')

    # ── Strategy 1: EV-greedy ────────────────────────────────────────────────
    # Filter: P(top15) > 0.07 keeps all in-odds riders (min ~8%) while
    # excluding non-odds riders (hardcoded 5%). Sort by EV/price (value
    # efficiency) so expensive picks don't crowd out cheaper good-value slots.
    # budget_reserve=True prevents early expensive picks from starving later slots.
    TOP15_MIN = 0.07
    pool_ev = [r for r in pool if probs.get(r['name'], {}).get('top15', 0) > TOP15_MIN]
    if len(pool_ev) + len(forced) < 8:
        pool_ev = pool  # fallback: insufficient in-odds candidates
    t1 = _greedy_fill(forced, pool_ev, budget,
                      lambda r: _ev_single(r['name'], probs) / max(r.get('price', 1), 1),
                      budget_reserve=True)

    # ── Strategy 2: Depth (P(top15)) ────────────────────────────────────────
    t2 = _greedy_fill(forced, pool, budget,
                      lambda r: probs.get(r['name'], {}).get('top15', 0))

    # ── Strategy 3: Top-3 favourites anchor + cheapest fill ─────────────────
    favs = sorted(pool, key=lambda r: probs.get(r['name'], {}).get('win', 0), reverse=True)
    anchor, tmp_tc = list(forced), defaultdict(int)
    for r in forced:
        tmp_tc[_norm_team(r.get('team', ''))] += 1
    for r in favs:
        if len(anchor) >= len(forced) + 3:
            break
        if tmp_tc[_norm_team(r.get('team', ''))] < 2 and r not in anchor:
            anchor.append(r)
            tmp_tc[_norm_team(r.get('team', ''))] += 1
    anchor_names = {r['name'] for r in anchor}
    rest = [r for r in pool if r['name'] not in anchor_names]
    t3 = _greedy_fill(anchor, rest, budget, lambda r: -r['price'])

    # ── Strategy 4: Balanced terrain affinity ───────────────────────────────
    def balanced(r):
        p  = probs.get(r['name'], {})
        ta = r.get('terrain_affinity', {})
        return p.get('top15', 0) * (
            1 + ta.get('sprint', 0) * 0.2 + ta.get('climbing', 0) * 0.2
        )
    t4 = _greedy_fill(forced, pool, budget, balanced)

    # ── Strategy 5: Best of 100 random valid teams ──────────────────────────
    rng_pool = pool[:]
    rng_teams = []
    for _ in range(100):
        random.shuffle(rng_pool)
        rt = _greedy_fill(forced, rng_pool, budget, lambda r: random.random())
        if rt:
            rng_teams.append(rt)
    t5 = (
        max(rng_teams, key=lambda t: sum(_ev_single(r['name'], probs) for r in t))
        if rng_teams else None
    )

    # ── Collect, validate, deduplicate ───────────────────────────────────────
    LABELS = [
        ('EV-maximal',           'Highest expected-value build; greedily selects top EV riders within constraints.'),
        ('Depth play',           'Maximises top-15 depth bonus; breadth of coverage over pure star power.'),
        ('Top-3 anchor + value', 'Locks the top favourites and fills remaining slots with the cheapest valid picks.'),
        ('Balanced sprint/GC',   'Mixed terrain affinity — spreads EV across sprint and GC stage types.'),
        ('Contrarian build',     'Best team found by random search; avoids the obvious groupthink picks.'),
    ]

    candidates = []
    for raw_team in [t1, t2, t3, t4, t5]:
        if raw_team is None or len(raw_team) != 8:
            continue

        # Hard constraint re-verification (uses normalised team names)
        total_price = sum(r['price'] for r in raw_team)
        if total_price > budget:
            continue
        tc, ok = defaultdict(int), True
        for r in raw_team:
            tc[_norm_team(r.get('team', ''))] += 1
            if tc[_norm_team(r.get('team', ''))] > 2:
                ok = False
                break
        if not ok:
            continue

        # Deduplicate: drop if >6 riders in common with an existing candidate
        overlap_fail = any(
            len({r['name'] for r in raw_team} & {r['name'] for r in c['riders']}) > 6
            for c in candidates
        )
        if overlap_fail:
            continue

        label, base_rat = LABELS[len(candidates)] if len(candidates) < len(LABELS) else (f'Team {len(candidates)+1}', '')
        top2 = sorted(raw_team, key=lambda r: probs.get(r['name'], {}).get('win', 0), reverse=True)[:2]
        rationale = base_rat + f' Anchored by {" & ".join(r["name"] for r in top2)}.'

        candidates.append({
            'label':            label,
            'riders':           raw_team,
            'forward_pressure': _forward_pressure(raw_team),
            'rationale':        rationale,
        })

        if len(candidates) >= 5:
            break

    return candidates


# ── Step 4: Captain selection ─────────────────────────────────────────────────

def select_captain(team_riders, all_probs):
    """
    Select captain as rider with highest single-rider stage-finish EV.
    Captain bonus = E[stage_finish_points] (doubling positive outcomes).
    """
    best_name, best_ev = None, -1.0
    for r in team_riders:
        name = r['name'] if isinstance(r, dict) else r
        ev   = _ev_single(name, all_probs)
        if ev > best_ev:
            best_ev, best_name = ev, name

    p       = all_probs.get(best_name, {})
    top3pct = p.get('top3', 0) * 100

    return {
        'name':     best_name,
        'rationale': (
            f'{best_name} has the highest stage-finish EV in the team '
            f'(~{int(best_ev / 1000)}k captain bonus, {top3pct:.0f}% top-3 probability). '
            f'Doubling positive outcomes captures maximum right-tail upside.'
        ),
    }
