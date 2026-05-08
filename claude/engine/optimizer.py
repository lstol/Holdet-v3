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

_FP_W1    = FINISH_POINTS[0]
_FP_W23   = (FINISH_POINTS[1] + FINISH_POINTS[2]) / 2
_FP_W4_10 = sum(FINISH_POINTS[3:10]) / 7
_FP_W11_15= sum(FINISH_POINTS[10:15]) / 5


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


# ── Step 1: Build probabilities ───────────────────────────────────────────────

def build_probabilities(all_riders, odds, intel, sliders=None):
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
    # Odds lookup
    odds_map = {
        o['name']: o.get('win_pct', 0) / 100.0
        for o in odds if o.get('name')
    }
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
            top3  = min(0.95, pw * 3.5)
            top10 = min(0.95, pw * 8.0)
            top15 = min(0.95, pw * 12.0)
        else:
            top3 = 0.02; top10 = 0.04; top15 = 0.05

        # Per-position finish probabilities (used by simulate_stage directly)
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
            'team_bonus_ev': 0.0,          # filled in pass 2
            'team': _norm_team(r.get('team', '')),
            'name': name,
        }

    # Pass 2: team_bonus_ev — expected bonus from real-world teammates finishing top 3
    # This is independent of fantasy team composition, so precompute once.
    by_team = defaultdict(list)
    for name, p in result.items():
        by_team[p['team']].append(name)

    for name, p in result.items():
        bonus = 0.0
        for tname in by_team[p['team']]:
            if tname == name:
                continue
            tp     = result[tname]
            bonus += tp['win']  * 60_000
            bonus += tp['p2']   * 30_000
            bonus += tp['p3']   * 20_000
        p['team_bonus_ev'] = bonus

    return result


# ── Step 2: Analytical team EV (fast — used during SA search) ─────────────────

def compute_team_ev(team, probs):
    """
    Fast analytical expected value for a team of 8 rider dicts.
    Uses precomputed finish_ev and team_bonus_ev from build_probabilities.

    Components:
      1. Stage finish EV per rider (precomputed)
      2. Captain bonus EV ≈ best rider's finish_ev (doubling positive outcomes)
      3. Team bonus EV per rider (precomputed from teammates' top-3 probability)
      4. Depth bonus EV (expected riders in top-15 → depth bonus table)
    """
    finish_evs = [probs.get(r['name'], {}).get('finish_ev', 0.0) for r in team]
    total  = sum(finish_evs)
    total += max(finish_evs) if finish_evs else 0.0          # captain bonus
    total += sum(probs.get(r['name'], {}).get('team_bonus_ev', 0.0) for r in team)
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

def simulated_annealing(all_riders, probs, force_in_names, force_out_names,
                         budget=BUDGET, n_iter=100_000, seed=42):
    """
    Single SA chain.  Returns (best_team_list, best_ev).

    Search space: all 184 riders subject to budget / team / count constraints.
    No tier filtering — cheap riders with team-bonus value appear naturally.

    Temperature schedule: T₀ = 50,000 (≈ 50k fantasy points), decay = 0.99995.
    After 100k iterations T ≈ 335, accepting only tiny downgrades.
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
    current_ev = compute_team_ev(team, probs)
    best_team  = team[:]
    best_ev    = current_ev

    T        = 50_000.0
    cooling  = 0.99995
    pool_len = len(pool)
    # Build index: name → position in pool, for duplicate detection
    pool_idx = {r['name']: i for i, r in enumerate(pool)}

    for _ in range(n_iter):
        # Pick a random swappable slot (never touch forced riders)
        if n_forced >= 8:
            break
        out_pos    = rng.randrange(n_forced, 8)
        new_rider  = pool[rng.randrange(pool_len)]

        # Skip if rider already in team
        if any(new_rider['name'] == r['name'] for r in team):
            T *= cooling
            continue

        # Propose swap
        new_team = team[:]
        new_team[out_pos] = new_rider

        if not is_valid(new_team, budget):
            T *= cooling
            continue

        new_ev = compute_team_ev(new_team, probs)
        delta  = new_ev - current_ev

        if delta > 0 or rng.random() < math.exp(delta / max(T, 0.01)):
            team       = new_team
            current_ev = new_ev
            if new_ev > best_ev:
                best_ev   = new_ev
                best_team = team[:]

        T *= cooling

    return best_team, best_ev


# ── Step 6: Team characterisation ────────────────────────────────────────────

def label_team(team, probs):
    """Detect and label the dominant structural pattern in a team."""
    tc = Counter(_norm_team(r.get('team', '')) for r in team)

    # Team-bonus concentration: top-win rider's real-world team has ≥2 in fantasy
    top_win_rider = max(team, key=lambda r: probs.get(r['name'], {}).get('win', 0))
    top_nt        = _norm_team(top_win_rider.get('team', ''))
    if tc[top_nt] >= 2:
        return 'Team-bonus concentration'

    # Sprint-maximal: multiple high sprint-affinity riders
    sprint_heavy = sum(
        1 for r in team if r.get('terrain_affinity', {}).get('sprint', 0) > 0.70
    )
    if sprint_heavy >= 4:
        return 'Sprint-maximal'

    # GC-heavy: multiple high climbing-affinity riders
    climbers = sum(
        1 for r in team if r.get('terrain_affinity', {}).get('climbing', 0) > 0.65
    )
    if climbers >= 4:
        return 'GC-heavy build'

    # Star build: two marquee riders (price > 9M)
    stars = sum(1 for r in team if r.get('price', 0) >= 9_000_000)
    if stars >= 3:
        return 'Star-power build'

    # Depth build: many mid-priced riders
    mid = sum(1 for r in team if 3_000_000 < r.get('price', 0) < 8_000_000)
    if mid >= 5:
        return 'Depth play'

    return 'Balanced build'


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
                              budget=BUDGET):
    """
    Run 5 independent SA chains with different seeds.
    Each chain searches all 184 riders with budget/team/count as the only
    hard constraints — no tier filtering anywhere.

    Riders with team-bonus value appear naturally if their EV justifies inclusion.
    After deduplication, run full Plackett-Luce Monte Carlo on each distinct team
    to produce accurate CDF and breakdown.

    Returns a list of candidate dicts sorted by ev_estimate descending.
    """
    forced_set = set(force_in_names  or [])
    excluded   = set(force_out_names or [])

    # Validate forced riders
    forced      = [r for r in all_riders if r['name'] in forced_set]
    forced_price = sum(r.get('price', 0) for r in forced)
    if forced_price > budget:
        raise ValueError(f'Force-in riders cost {forced_price:,} > budget {budget:,}')
    ftc = defaultdict(int)
    for r in forced:
        ftc[_norm_team(r.get('team', ''))] += 1
        if ftc[_norm_team(r.get('team', ''))] > 2:
            raise ValueError(f'Force-in has >2 riders from {r.get("team","?")}')

    # Run 5 SA chains
    SEEDS = [42, 123, 777, 2026, 99]
    raw_results = []
    for seed in SEEDS:
        team, ev = simulated_annealing(
            all_riders, probs, force_in_names, force_out_names,
            budget=budget, n_iter=100_000, seed=seed,
        )
        if team is not None:
            raw_results.append((ev, team))

    if not raw_results:
        return []

    # Deduplicate: discard any team that shares >6 riders with a higher-EV team
    raw_results.sort(key=lambda x: x[0], reverse=True)
    distinct = []
    for ev, team in raw_results:
        names = {r['name'] for r in team}
        if not any(len(names & {r['name'] for r in t}) > 6 for _, t in distinct):
            distinct.append((ev, team))

    # Run full Monte Carlo on each distinct team
    candidates = []
    for _, team in distinct[:5]:
        total_price = sum(r.get('price', 0) for r in team)
        assert total_price <= budget, (
            f"Budget violation: team costs {total_price:,} > budget {budget:,} "
            f"(riders: {[r['name'] for r in team]})"
        )
        cap = select_captain(team, probs)
        sim = simulate_stage(team, probs, cap['name'], all_riders=all_riders)
        lbl = label_team(team, probs)
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
    """Single-rider finish EV (used by select_captain)."""
    p    = probs.get(name, {})
    pw   = p.get('win',   0.0)
    pt3  = p.get('top3',  0.0)
    pt10 = p.get('top10', 0.0)
    pt15 = p.get('top15', 0.0)
    return max(0.0,
        pw                    * FINISH_POINTS[0]
        + max(0, pt3  - pw)   * (FINISH_POINTS[1] + FINISH_POINTS[2]) / 2
        + max(0, pt10 - pt3)  * sum(FINISH_POINTS[3:10]) / 7
        + max(0, pt15 - pt10) * sum(FINISH_POINTS[10:15]) / 5
    )


def select_captain(team_riders, all_probs):
    """Select captain as rider with highest single-rider stage-finish EV."""
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
            f'{best_name} has the highest stage-finish EV in the team '
            f'(~{int(best_ev / 1000)}k captain bonus, {top3pct:.0f}% top-3 probability). '
            f'Doubling positive outcomes captures maximum right-tail upside.'
        ),
    }


# ── Monte Carlo simulation (Plackett-Luce) ────────────────────────────────────

def simulate_stage(team_riders, all_probs, captain_name, all_riders=None, n_sims=10_000):
    """
    Simulate n_sims stage outcomes using Plackett-Luce sampling.
    Returns {'mean', 'cdf': {p25,p50,p75,p90}, 'breakdown': {...}}.
    """
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

    team_pos = rank[:, team_idxs]                         # (n_sims, 8)

    fp_lookup  = np.array(FINISH_POINTS, dtype=np.float64)
    finish_pts = np.where(team_pos < 15, fp_lookup[np.minimum(team_pos, 14)], 0.0)

    cap_pts       = finish_pts[:, capt_ti]
    captain_bonus = np.maximum(cap_pts, 0.0)

    depth_cnt = (team_pos < 15).sum(axis=1)
    depth_pts = np.array(
        [DEPTH_BONUS[min(int(d), 8)] for d in depth_cnt], dtype=np.float64
    )

    team_bonus = np.zeros(n_sims, dtype=np.float64)
    for pos_off, bval in TEAM_BONUS_MAP.items():
        top_fidx  = order[:, pos_off]
        top_rteam = field_real[top_fidx]
        for rteam in team_real:
            if rteam:
                team_bonus += (top_rteam == rteam).astype(np.float64) * bval

    stage_totals = finish_pts.sum(axis=1)
    totals       = stage_totals + captain_bonus + depth_pts + team_bonus

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
            'captain_bonus': int(captain_bonus.mean()),
            'team_bonus':    int(team_bonus.mean()),
            'depth_bonus':   int(depth_pts.mean()),
            'gc_bonus':      0,
        },
    }
