"""
Basin landscape diagnostic — S17-22-followup Phase 1 + Phase 2A.

Phase 1: characterises per-strategy basin landscape across three slider
configurations of Stage 2 (3 configs × 4 strategies × 50 chains = 600 SA
runs). Drives the case classification (A/B/C/D) for the lookahead strategy
and informs whether the convergence problem is hyperparameter-tunable,
landscape-intrinsic, false-corroboration risk, or strategy-specific.

Phase 2A (this augmentation): objective decomposition. Persists per-chain
data (rider rosters, sim_ev, compute_objective value, and decomposed
components ev_estimate / tc_current / cost_n1 / cost_n2) so a downstream
analysis can localize EV-inversion to (a) ev_estimate-vs-sim_ev divergence
or (b) forward-cost weighting. The augmentation is backward-compatible —
re-runs can target a subset of cells via --cells and merge into the existing
persisted JSON without disturbing cells already on disk.

Why this exists:
  - S17-22 V4 reported no convergence improvement at operational N=10, but
    the comparison was confounded (pre-Tier-A baseline vs post-Tier-A
    cooling=0.99999, single seed each). Best-corroborated reporting works
    correctly but "ship marginal, rely on UX" was always a fallback. The
    user wants a quality fix; this characterises the landscape so the fix
    is data-driven, not guessed.

Re-run when:
  - SA hyperparameter tuning beyond cooling_rate (Phase 2 sweep)
  - Considering heterogeneous N (per-strategy n_chains)
  - Mid-Giro re-baselining (S18-1)
  - Tour-prep recalibration

Configurations (all on Stage 2):
  A — saved   : n1=70/20/5/5, n2=50/30/10/10, n3=30/30/30/10  (dashboard defaults;
                Stage 2 saved sliders are NOT persisted in any snapshot file —
                the dashboard's localStorage is the only source. Defaults serve
                as the most defensible "saved" stand-in.)
  B — sprint  : n1=n2=n3=90/5/3/2
  C — uniform : n1=n2=n3=25/25/25/25

For each (config, strategy), 50 chains. SA hyperparameters mirror optimizer.py's
strategies dict exactly (lookahead has cooling_rate=0.99999, others empty).
Per-strategy XOR sub-seeds 0xC0..0xF1 (50 distinct masks); none collide with
0xF (eval/proxy), 0xA, 0xB.

Cell-level stop: any (config, strategy) cell exceeding 15 min → abort, log,
continue.
Total stop: > 60 min → stop, partial report.

Outputs:
  - Per-cell metrics: N_distinct_teams, count histogram (top-10), EV of top-10
    most-hit teams, EV spreads (top1−top5; best_seen−best_corroborated), 5
    non-overlapping N=10 sub-sample corroboration checks.
  - Aggregate: cross-strategy at config A; cross-config for lookahead;
    cross-config for one non-lookahead strategy.
  - Case classification (A/B/C/D) for lookahead, brief for others.
  - Phase 2 sketch.

Read-only. Calls optimizer functions directly; no persistence files written.
Raw results dumped to /tmp/basin_landscape_results.json for re-analysis.

Snapshot dependencies (from shared/data/snapshots/):
  - stage_2_odds.json
  - stage_2_intel.json
  - stage_2_holdet.json (for budget; falls back to default if absent)
  - stage_1_results.json (for current_team)

Important property of S17-2 Tier A under race_type_adjustment=False:
  - n1 sliders are dropped from compute_seed's hash AND build_probabilities's
    adjustment block is gated on race_type=True. So under race_type=False,
    varying n1 alone changes nothing observable; configs A/B/C only differ
    operationally via n2/n3 (which (a) feed build_forward_probabilities so
    cost_n1/cost_n2 change, affecting lookahead's objective, and (b) remain
    in compute_seed's hash so SA initial conditions shift). This is the
    realistic operational picture; the diagnostic stays meaningful.

Usage:
    # Phase 1 (full sweep, 12 cells, ~37 min)
    python3 claude/diagnostics/basin_landscape.py

    # Phase 2A (subset; persisted JSON merged in-place)
    python3 claude/diagnostics/basin_landscape.py \\
        --cells A_saved:lookahead,B_sprint:lookahead,B_sprint:low-transfer \\
        --analyze-objectives
"""
import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    compute_seed,
    build_probabilities,
    build_forward_probabilities,
    estimate_forward_costs,
    simulated_annealing,
    simulate_stage,
    select_captain,
    topup_team,
    fast_optimize,
    load_stage_scoring,
    get_stage_config,
    compute_objective,
    compute_team_ev,
    compute_transfer_cost,
)

SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE  = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')

STAGE = 2
N_CHAINS = 50
PER_CELL_TIMEOUT_SECS = 15 * 60   # 15 min cell cap
TOTAL_TIMEOUT_SECS    = 60 * 60   # 60 min total cap

# Slider configurations. n2/n3 mirror n1's skew within each config (handoff:
# "matches how a user would actually configure for a sustained stage type").
SLIDER_CONFIGS = {
    'A_saved': {
        'n1': {'bunch_sprint': 70, 'reduced_sprint': 20, 'gc': 5,  'breakaway': 5 },
        'n2': {'bunch_sprint': 50, 'reduced_sprint': 30, 'gc': 10, 'breakaway': 10},
        'n3': {'bunch_sprint': 30, 'reduced_sprint': 30, 'gc': 30, 'breakaway': 10},
    },
    'B_sprint': {
        'n1': {'bunch_sprint': 90, 'reduced_sprint': 5, 'gc': 3, 'breakaway': 2},
        'n2': {'bunch_sprint': 90, 'reduced_sprint': 5, 'gc': 3, 'breakaway': 2},
        'n3': {'bunch_sprint': 90, 'reduced_sprint': 5, 'gc': 3, 'breakaway': 2},
    },
    'C_uniform': {
        'n1': {'bunch_sprint': 25, 'reduced_sprint': 25, 'gc': 25, 'breakaway': 25},
        'n2': {'bunch_sprint': 25, 'reduced_sprint': 25, 'gc': 25, 'breakaway': 25},
        'n3': {'bunch_sprint': 25, 'reduced_sprint': 25, 'gc': 25, 'breakaway': 25},
    },
}

USE_RACE_TYPE = False
FORCE_IN  = []
FORCE_OUT = []


def _load_data():
    odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_odds.json')
    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_intel.json')
    snapshot_path = os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_holdet.json')
    rider_data = json.load(open(RIDERS_FILE))

    raw_odds = json.load(open(odds_path)) if os.path.exists(odds_path) else []
    odds = raw_odds.get('odds', raw_odds) if isinstance(raw_odds, dict) else raw_odds
    intel = json.load(open(intel_path)) if os.path.exists(intel_path) else {}
    snap = json.load(open(snapshot_path)) if os.path.exists(snapshot_path) else {}
    budget = int(snap.get('bank_balance', 50_000_000) or 50_000_000)

    current_team = None
    prev = STAGE - 1
    if prev >= 1:
        results_path = os.path.join(SNAPSHOT_DIR, f'stage_{prev}_results.json')
        if os.path.exists(results_path):
            results = json.load(open(results_path))
            prev_names = [r.get('name') for r in results.get('rider_results', []) if r.get('name')]
            active = [r for r in rider_data['riders']
                      if not r.get('isOut') and r.get('status') != 'dns']
            by_lower = {r['name'].lower(): r for r in active}
            matched = []
            for n in prev_names:
                if n.lower() in by_lower:
                    matched.append(by_lower[n.lower()])
            current_team = matched or None

    active_riders = [r for r in rider_data['riders']
                     if not r.get('isOut') and r.get('status') != 'dns']
    return active_riders, odds, intel, budget, current_team


def _team_id(team):
    return tuple(sorted(
        str(r.get('holdet_id') if r.get('holdet_id') is not None else r.get('name', ''))
        for r in team
    ))


def _team_label(team, k=3):
    """Top-k riders by price as a short label."""
    sorted_team = sorted(team, key=lambda r: -(r.get('price') or 0))
    parts = []
    for r in sorted_team[:k]:
        n = r.get('name', '?')
        # Last name only
        last = n.split()[-1] if n else '?'
        parts.append(last)
    return '/'.join(parts)


# Mirror of optimizer.py's strategies dict (post-S17-22). lookahead has
# cooling_rate=0.99999; others use SA defaults.
STRATEGIES = [
    {'name': 'optimal',      'strategy_xor': 0x1, 'objective': 'ev',
     'n_iter': 200_000, 'max_seconds': 5, 'sa_overrides': {}},
    {'name': 'depth',        'strategy_xor': 0x2, 'objective': 'depth',
     'n_iter': 200_000, 'max_seconds': 5, 'sa_overrides': {}},
    {'name': 'low-transfer', 'strategy_xor': 0x3, 'objective': 'low_transfer',
     'n_iter': 200_000, 'max_seconds': 5, 'sa_overrides': {}},
    {'name': 'lookahead',    'strategy_xor': 0x4, 'objective': 'lookahead',
     'n_iter': 200_000, 'max_seconds': 5,
     'sa_overrides': {'cooling_rate': 0.99999}},
]


def _holdet_ids(team):
    return sorted(int(r['holdet_id']) for r in team if r.get('holdet_id') is not None)


def run_cell(strategy, sliders, active_riders, odds, intel, budget,
             current_team, scoring, stage_config, deadline_total):
    """Run N_CHAINS chains for one (config, strategy) cell.

    Returns (chain_results, elapsed, status, captured_teams).
    status ∈ {'ok', 'cell_timeout', 'total_timeout'}.
    captured_teams: dict team_id → team list (one representative team).

    Phase 2A augmentation: each chain_results entry carries roster +
    objective decomposition fields (holdet_ids, captain, objective_value,
    ev_estimate, tc_current, cost_n1_team_to_team_n1, cost_n2_const) so
    downstream analysis can localize EV-inversion without SA re-runs.
    """
    base_seed = compute_seed(STAGE, sliders, FORCE_IN, FORCE_OUT, USE_RACE_TYPE)

    probs_current = build_probabilities(
        active_riders, odds, intel, sliders.get('n1', {}),
        stage_config=stage_config, scoring=scoring,
        use_race_type=USE_RACE_TYPE,
    )
    probs_n1_fwd = build_forward_probabilities(active_riders, sliders.get('n2', {}))
    probs_n2_fwd = build_forward_probabilities(active_riders, sliders.get('n3', {}))

    proxy_seed = base_seed ^ 0xF
    proxy = current_team or fast_optimize(
        active_riders, probs_current, active_riders, FORCE_IN, FORCE_OUT, budget,
        seed=proxy_seed,
    )
    cost_n1, cost_n2, _, _, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], active_riders, active_riders,
        probs_n1_fwd, probs_n2_fwd, FORCE_IN, FORCE_OUT, budget,
        seed=base_seed,
    )

    eval_seed_shared = base_seed ^ 0xF

    chain_xors = tuple(0xC0 + i for i in range(N_CHAINS))
    chain_seeds = [base_seed ^ (strategy['strategy_xor'] << 8) ^ m for m in chain_xors]

    chain_results = []
    captured_teams = {}
    sa_overrides = strategy.get('sa_overrides') or {}

    cell_start = time.time()
    for ci, ch_seed in enumerate(chain_seeds):
        # Total-budget guard
        if time.time() > deadline_total:
            return chain_results, time.time() - cell_start, 'total_timeout', captured_teams
        # Cell-budget guard
        if time.time() - cell_start > PER_CELL_TIMEOUT_SECS:
            return chain_results, time.time() - cell_start, 'cell_timeout', captured_teams

        team_ci, _ev_ci, _diags = simulated_annealing(
            active_riders, probs_current, FORCE_IN, FORCE_OUT,
            budget=budget,
            n_iter=strategy['n_iter'],
            max_seconds=strategy['max_seconds'],
            seed=ch_seed,
            objective=strategy['objective'],
            verbose=False,
            cost_n1=cost_n1, cost_n2=cost_n2,
            team_n1=team_n1, team_n2=team_n2,
            current_team=current_team,
            **sa_overrides,
        )
        if team_ci is None:
            continue
        team_ci = topup_team(team_ci, active_riders, probs_current, active_riders, budget)
        captain_ci = select_captain(team_ci, probs_current)
        sim_ci = simulate_stage(
            team_ci, probs_current, captain_ci['name'],
            all_riders=active_riders,
            stage_config=stage_config, scoring=scoring,
            seed=eval_seed_shared,
        )
        tid = _team_id(team_ci)
        if tid not in captured_teams:
            captured_teams[tid] = team_ci

        # Phase 2A: capture objective decomposition for the chain's final team.
        obj_val = compute_objective(
            team_ci, probs_current, active_riders, strategy['objective'],
            cost_n1, cost_n2, team_n1, team_n2,
            current_team=current_team,
        )
        ev_estimate_team = compute_team_ev(team_ci, probs_current)
        tc_current_team  = compute_transfer_cost(current_team or [], team_ci) \
                           if current_team else 0
        cost_n1_team     = compute_transfer_cost(team_ci, team_n1 or []) \
                           if team_n1 else 0
        cost_n2_const    = compute_transfer_cost(team_n1 or [], team_n2 or []) \
                           if team_n1 and team_n2 else 0

        chain_results.append({
            'index':           ci,
            'ev':              int(sim_ci['mean']),
            'team_id':         tid,
            'holdet_ids':      _holdet_ids(team_ci),
            'captain':         captain_ci['name'],
            'sim_ev':          int(sim_ci['mean']),
            'objective_value': float(obj_val),
            'ev_estimate':     float(ev_estimate_team),
            'tc_current':      float(tc_current_team),
            'cost_n1':         float(cost_n1_team),
            'cost_n2_const':   float(cost_n2_const),
        })
    return chain_results, time.time() - cell_start, 'ok', captured_teams


def _corroboration_status(chain_results_subset):
    """Mirror optimizer.py:1167-1188 corroboration logic on a subset."""
    if not chain_results_subset:
        return 'empty'
    best = max(chain_results_subset,
               key=lambda c: (c['ev'], -c['index']))
    team_count = Counter(c['team_id'] for c in chain_results_subset)
    chosen_count = team_count[best['team_id']]
    if chosen_count >= 2:
        return 'corroborated'
    if any(cnt >= 2 for cnt in team_count.values()):
        return 'single_chain'
    return 'no_corroboration'


def aggregate_cell(chain_results, captured_teams):
    """Per-cell summary: histogram, EV spreads, sub-sample corroboration."""
    if not chain_results:
        return {
            'n_chains': 0,
            'n_distinct_teams': 0,
            'top_teams': [],
            'ev_top1_minus_top5': None,
            'ev_best_seen_minus_corroborated': None,
            'subsample_corroboration': [],
        }

    # Per-team EV (any chain's EV is fine — shared eval_seed makes them
    # identical for chains landing on the same team_id).
    team_ev = {}
    team_count = Counter()
    for c in chain_results:
        team_count[c['team_id']] += 1
        team_ev[c['team_id']] = c['ev']

    # Top-10 most-hit
    most_common = team_count.most_common(10)
    top_teams = []
    for rank, (tid, cnt) in enumerate(most_common, start=1):
        team = captured_teams.get(tid, [])
        top_teams.append({
            'rank':  rank,
            'count': cnt,
            'ev':    team_ev[tid],
            'label': _team_label(team) if team else '?',
        })

    # EV spread metrics
    sorted_by_count = top_teams
    ev_top1 = sorted_by_count[0]['ev']
    ev_top5 = sorted_by_count[4]['ev'] if len(sorted_by_count) >= 5 else sorted_by_count[-1]['ev']
    ev_top1_minus_top5 = ev_top1 - ev_top5

    ev_best_seen = max(c['ev'] for c in chain_results)
    corroborated_ids = [tid for tid, cnt in team_count.items() if cnt >= 2]
    if corroborated_ids:
        ev_best_corroborated = max(team_ev[tid] for tid in corroborated_ids)
    else:
        ev_best_corroborated = ev_best_seen   # nothing ≥2; fall back so spread = 0
    ev_best_seen_minus_corroborated = ev_best_seen - ev_best_corroborated

    # Sub-sampled N=10 corroboration: 5 non-overlapping windows over chain index
    subsample_corroboration = []
    by_index = sorted(chain_results, key=lambda c: c['index'])
    for s in range(5):
        subset = [c for c in by_index if s * 10 <= c['index'] < (s + 1) * 10]
        subsample_corroboration.append({
            'window':   f'{s*10}-{s*10+9}',
            'n':        len(subset),
            'status':   _corroboration_status(subset),
        })

    return {
        'n_chains': len(chain_results),
        'n_distinct_teams': len(team_count),
        'top_teams': top_teams,
        'ev_top1_minus_top5': ev_top1_minus_top5,
        'ev_best_seen_minus_corroborated': ev_best_seen_minus_corroborated,
        'subsample_corroboration': subsample_corroboration,
        # Phase 2A: full per-chain detail for objective decomposition.
        'chain_data': chain_results,
    }


def fmt_int(n):
    return f"{n:,}" if n is not None else "—"


def print_cell_section(config_name, strategy_name, agg, status, elapsed):
    print(f"\n#### {config_name} × {strategy_name}")
    print()
    print(f"- runtime: {elapsed:.1f}s  status: {status}  chains: {agg['n_chains']}/{N_CHAINS}")
    print(f"- N_distinct_teams: {agg['n_distinct_teams']}")
    print(f"- ev_top1_hit − ev_top5_hit: {fmt_int(agg['ev_top1_minus_top5'])}")
    print(f"- ev_best_seen − ev_best_corroborated: {fmt_int(agg['ev_best_seen_minus_corroborated'])}")
    if agg['top_teams']:
        print()
        print(f"  | rank | count | ev          | top-3 riders (by price)")
        print(f"  |-----:|------:|------------:|--------------------------")
        for t in agg['top_teams']:
            print(f"  | {t['rank']:>4} | {t['count']:>5} | {fmt_int(t['ev']):>11} | {t['label']}")
    print()
    print(f"  N=10 sub-sample corroboration (non-overlapping windows):")
    for s in agg['subsample_corroboration']:
        print(f"    window {s['window']:>5} (n={s['n']}): {s['status']}")


RESULTS_PATH = '/tmp/basin_landscape_results.json'


def _load_existing_results():
    if not os.path.exists(RESULTS_PATH):
        return {}
    try:
        with open(RESULTS_PATH) as f:
            return json.load(f)
    except Exception as exc:
        print(f"  WARN: existing {RESULTS_PATH} unreadable ({exc}); ignoring.",
              flush=True)
        return {}


def _bit_identical_check(new_cell, existing_cell, config_name, strategy_name):
    """Compare new top-2 basins (label + count) against existing persisted
    top_teams[:2] for the same cell. Returns (ok: bool, detail: str).

    Verifies the seed/algorithm path is reproducing Phase 1's basins exactly.
    """
    new_top  = new_cell.get('top_teams', [])[:2]
    old_top  = existing_cell.get('top_teams', [])[:2]
    if not old_top:
        return True, "(no prior data for this cell — skipping bit-identical check)"
    if len(new_top) != len(old_top):
        return False, f"top-2 length mismatch: new={len(new_top)} old={len(old_top)}"
    for i, (n, o) in enumerate(zip(new_top, old_top)):
        if n['label'] != o['label']:
            return False, f"top-{i+1} label diverged: new='{n['label']}' old='{o['label']}'"
        if n['count'] != o['count']:
            return False, f"top-{i+1} count diverged: new={n['count']} old={o['count']}"
    return True, "top-2 basins bit-identical to Phase 1"


def _parse_cells_arg(s):
    """Parse 'A_saved:lookahead,B_sprint:lookahead,...' into a set of tuples."""
    out = set()
    for tok in s.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if ':' not in tok:
            raise SystemExit(f"--cells: bad token {tok!r}; expected config:strategy")
        cfg, strat = tok.split(':', 1)
        out.add((cfg.strip(), strat.strip()))
    return out


def _spearman(xs, ys):
    """Spearman rank correlation. Returns NaN if zero variance."""
    n = len(xs)
    if n < 2:
        return float('nan')
    def ranks(vals):
        idx = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        for rank_i, orig_i in enumerate(idx, start=1):
            r[orig_i] = rank_i
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num   = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    denx  = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    deny  = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if denx == 0 or deny == 0:
        return float('nan')
    return num / (denx * deny)


def analyze_objectives(results, target_cells):
    """Phase 2A decomposition over the target cells' chain_data.

    Outputs per-cell basin tables, Q1 (ev_estimate vs sim_ev divergence),
    Q2 (forward-cost dominance for lookahead), and an overall verdict.
    """
    print("\n========================== OBJECTIVE DECOMPOSITION (Phase 2A) ==========================")
    verdicts = {}
    for (cfg, strat) in sorted(target_cells):
        cell = results.get(cfg, {}).get(strat)
        if not cell or not cell.get('chain_data'):
            print(f"\n### {cfg} × {strat} — no chain_data; skipped.")
            continue
        chains = cell['chain_data']

        # Basin aggregation: group by team_id tuple.
        # team_id values arrive from JSON as lists (JSON doesn't preserve
        # tuples); normalise to tuples for hashing.
        by_basin = defaultdict(list)
        for c in chains:
            tid = tuple(c['team_id']) if isinstance(c['team_id'], list) else c['team_id']
            by_basin[tid].append(c)

        # Sort basins by count descending.
        sorted_basins = sorted(by_basin.items(), key=lambda kv: -len(kv[1]))

        # Build label map from cell['top_teams'].
        label_by_count_ev = {}
        for t in cell.get('top_teams', []):
            label_by_count_ev[(t['count'], t['ev'])] = t['label']

        # Print top-5 (or more if needed) basin table.
        print(f"\n### {cfg} × {strat}")
        print(f"\n| basin | count | mean_obj    | mean_ev_est | mean_sim_ev | mean_tc_cur | mean_cost_n1 | label                       |")
        print(f"|------:|------:|------------:|------------:|------------:|------------:|-------------:|-----------------------------|")
        basin_rows = []
        for rank, (tid, chs) in enumerate(sorted_basins[:max(5, 2)], start=1):
            n      = len(chs)
            m_obj  = sum(c['objective_value']   for c in chs) / n
            m_evest= sum(c['ev_estimate']       for c in chs) / n
            m_sim  = sum(c['sim_ev']            for c in chs) / n
            m_tcc  = sum(c['tc_current']        for c in chs) / n
            m_c1   = sum(c['cost_n1']           for c in chs) / n
            label  = label_by_count_ev.get((n, int(m_sim)), '?')
            basin_rows.append((rank, n, m_obj, m_evest, m_sim, m_tcc, m_c1, label))
            print(f"| {rank:>5} | {n:>5} | {m_obj:>11,.0f} | {m_evest:>11,.0f} | "
                  f"{m_sim:>11,.0f} | {m_tcc:>11,.0f} | {m_c1:>12,.0f} | {label:<27} |")

        # Q1: ev_estimate vs sim_ev correlation across all 50 chains.
        evs_est = [c['ev_estimate'] for c in chains]
        evs_sim = [c['sim_ev']      for c in chains]
        rho = _spearman(evs_est, evs_sim)
        print(f"\n  Q1 — Spearman(ev_estimate, sim_ev) across {len(chains)} chains: ρ = {rho:.3f}")

        if len(basin_rows) >= 2:
            r1, r2 = basin_rows[0], basin_rows[1]
            # Side-by-side mean_ev_est vs mean_sim_ev for top-2 basins.
            evest_gap = r1[3] - r2[3]   # basin1 - basin2 by count
            sim_gap   = r1[4] - r2[4]
            agree_sign = (evest_gap > 0) == (sim_gap > 0) if evest_gap != 0 and sim_gap != 0 else None
            print(f"  Q1 top-2 side-by-side (basin1 by count vs basin2):")
            print(f"    mean_ev_est:  {r1[3]:>11,.0f} vs {r2[3]:>11,.0f}  (Δ = {evest_gap:+,.0f})")
            print(f"    mean_sim_ev:  {r1[4]:>11,.0f} vs {r2[4]:>11,.0f}  (Δ = {sim_gap:+,.0f})")
            print(f"    Δ sign agreement: {agree_sign}")

        # Q2: lookahead only — forward-cost dominance of basin choice.
        q2_verdict = None
        if strat == 'lookahead' and len(basin_rows) >= 2:
            r1, r2 = basin_rows[0], basin_rows[1]
            # Objective gap basin1 − basin2.
            obj_gap   = r1[2] - r2[2]
            evest_gap = r1[3] - r2[3]
            tcc_gap   = -(r1[5] - r2[5])   # objective sign on tc is negative
            cn1_gap   = -(r1[6] - r2[6])
            # tc_n2 differences = 0 across basins (team_n1, team_n2 are cell-level constants).
            attributed = evest_gap + tcc_gap + cn1_gap
            # Fraction explanation (signed): how much of the objective gap is
            # explained by each component.
            def pct(part):
                if obj_gap == 0:
                    return float('nan')
                return 100.0 * part / obj_gap
            print(f"  Q2 — top-2 objective gap decomposition (basin1 − basin2):")
            print(f"    obj_gap          = {obj_gap:+12,.0f}")
            print(f"    Δ ev_estimate    = {evest_gap:+12,.0f}  ({pct(evest_gap):+5.1f}% of obj_gap)")
            print(f"    Δ (−tc_current)  = {tcc_gap:+12,.0f}  ({pct(tcc_gap):+5.1f}% of obj_gap)")
            print(f"    Δ (−cost_n1)     = {cn1_gap:+12,.0f}  ({pct(cn1_gap):+5.1f}% of obj_gap)")
            print(f"    (residual / Δ tc_n2 constant): {obj_gap - attributed:+,.0f}")
            # Verdict heuristic: which single term covers the largest |share|?
            shares = {'ev_estimate': evest_gap, 'tc_current': tcc_gap, 'cost_n1': cn1_gap}
            dominant = max(shares.items(), key=lambda kv: abs(kv[1]))
            q2_verdict = (dominant[0], dominant[1], pct(dominant[1]))
            print(f"    Q2 dominant term: {dominant[0]} ({pct(dominant[1]):+.1f}% of obj_gap)")

        # One-line conclusion.
        concl = []
        if not math.isnan(rho) and rho < 0.9:
            concl.append(f"Q1: ev_estimate diverges from sim_ev (ρ={rho:.3f})")
        else:
            concl.append(f"Q1: ev_estimate ≈ sim_ev (ρ={rho:.3f})")
        if q2_verdict:
            concl.append(f"Q2 dominant term: {q2_verdict[0]} ({q2_verdict[2]:+.1f}%)")
        print(f"\n  → {' | '.join(concl)}")

        verdicts[(cfg, strat)] = {'q1_rho': rho, 'q2': q2_verdict}

    print("\n========================== VERDICTS ==========================")
    for (cfg, strat), v in sorted(verdicts.items()):
        print(f"  {cfg:<10} × {strat:<14}  ρ={v['q1_rho']:.3f}"
              + (f"   Q2 dominant: {v['q2'][0]} ({v['q2'][2]:+.1f}%)" if v['q2'] else ""))
    return verdicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cells', help='Comma-separated config:strategy pairs to run; '
                                    'omit for full 12-cell sweep.')
    ap.add_argument('--analyze-objectives', action='store_true',
                    help='Run Phase 2A objective decomposition on the selected '
                         'cells after the run (or on previously persisted data '
                         'if --cells is omitted alongside --no-run).')
    ap.add_argument('--no-run', action='store_true',
                    help='Skip SA; only run --analyze-objectives over persisted JSON.')
    args = ap.parse_args()

    target_cells = _parse_cells_arg(args.cells) if args.cells else None

    print("Loading inputs ...", flush=True)
    active_riders, odds, intel, budget, current_team = _load_data()
    print(f"  active_riders={len(active_riders)}, odds_rows={len(odds)}, "
          f"intel_signals={len(intel.get('intel', intel).get('key_signals', []))}, "
          f"current_team={'set' if current_team else 'None'}, budget={budget:,}",
          flush=True)
    if not odds:
        print("  ERROR: stage_2_odds.json missing or empty — STOP", flush=True)
        sys.exit(2)
    if not intel:
        print("  WARNING: stage_2_intel.json missing or empty — continuing without intel signals",
              flush=True)

    scoring      = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    deadline_total = time.time() + TOTAL_TIMEOUT_SECS

    existing = _load_existing_results()
    # Materialise loaded cells into the in-memory results dict so analysis can
    # read either fresh or existing per-cell chain_data uniformly.
    results = defaultdict(dict)
    for cfg, by_strat in existing.items():
        for strat, cell in by_strat.items():
            results[cfg][strat] = cell

    aborted = False
    first_rerun_checked = False
    if not args.no_run:
        for config_name, sliders in SLIDER_CONFIGS.items():
            if aborted:
                break
            for strategy in STRATEGIES:
                if target_cells and (config_name, strategy['name']) not in target_cells:
                    continue
                if time.time() > deadline_total:
                    print(f"\n  TOTAL TIMEOUT at {config_name}/{strategy['name']} — aborting",
                          flush=True)
                    aborted = True
                    break
                print(f"\n[{config_name}/{strategy['name']:<12}] running {N_CHAINS} chains ...",
                      flush=True)
                chain_results, elapsed, status, captured_teams = run_cell(
                    strategy, sliders, active_riders, odds, intel, budget,
                    current_team, scoring, stage_config, deadline_total,
                )
                agg = aggregate_cell(chain_results, captured_teams)
                new_cell = {**agg, 'elapsed': elapsed, 'status': status}

                # Bit-identical check on the very first re-run cell that has
                # prior persisted data. If it diverges, stop before mutating
                # anything else.
                if not first_rerun_checked:
                    prior = existing.get(config_name, {}).get(strategy['name'])
                    if prior:
                        ok, detail = _bit_identical_check(
                            new_cell, prior, config_name, strategy['name']
                        )
                        print(f"  bit-identical check: {'PASS' if ok else 'FAIL'} — {detail}",
                              flush=True)
                        if not ok:
                            print(f"  STOPPING: top-2 basins diverged from Phase 1. "
                                  f"Aborting before merge-write.", flush=True)
                            sys.exit(3)
                        first_rerun_checked = True

                results[config_name][strategy['name']] = new_cell
                print(f"  done: {agg['n_chains']}/{N_CHAINS} chains, "
                      f"{agg['n_distinct_teams']} distinct teams, "
                      f"ev_best_seen={fmt_int(max((c['ev'] for c in chain_results), default=None))}, "
                      f"runtime={elapsed:.1f}s, status={status}",
                      flush=True)
                if status == 'cell_timeout':
                    print(f"  cell timed out (>15 min); continuing with remaining cells.",
                          flush=True)
                elif status == 'total_timeout':
                    print(f"  TOTAL TIMEOUT inside cell — partial cell recorded.",
                          flush=True)
                    aborted = True
                    break

    # Decide which cells to print in detail. When --cells is set, only show
    # those cells (concise, focused report). When not, show every cell.
    detail_filter = target_cells if target_cells else None
    print(f"\n========================== PER-CELL DETAIL ==========================")
    for config_name in SLIDER_CONFIGS.keys():
        if config_name not in results:
            continue
        emitted_header = False
        for strategy in STRATEGIES:
            sname = strategy['name']
            if sname not in results[config_name]:
                continue
            if detail_filter and (config_name, sname) not in detail_filter:
                continue
            if not emitted_header:
                print(f"\n### Config {config_name}")
                emitted_header = True
            cell = results[config_name][sname]
            print_cell_section(config_name, sname, cell,
                                cell.get('status', '—'),
                                cell.get('elapsed', 0.0))

    print(f"\n========================== AGGREGATES ==========================")

    # Cross-strategy at config A
    print(f"\n### Cross-strategy at config A_saved")
    print(f"\n| strategy      | distinct | dom_count | dom_pct | ev_top1−top5 | ev_seen−corr |")
    print(f"|---------------|---------:|----------:|--------:|-------------:|-------------:|")
    if 'A_saved' in results:
        for strategy in STRATEGIES:
            sname = strategy['name']
            if sname not in results['A_saved']:
                continue
            cell = results['A_saved'][sname]
            dom_count = cell['top_teams'][0]['count'] if cell['top_teams'] else 0
            dom_pct = f"{(dom_count / cell['n_chains']) * 100:.0f}%" if cell['n_chains'] else "—"
            print(f"| {sname:<13} | {cell['n_distinct_teams']:>8} | {dom_count:>9} | "
                  f"{dom_pct:>7} | {fmt_int(cell['ev_top1_minus_top5']):>12} | "
                  f"{fmt_int(cell['ev_best_seen_minus_corroborated']):>12} |")

    # Cross-config for lookahead
    print(f"\n### Cross-config for lookahead")
    print(f"\n| config     | distinct | dom_count | dom_pct | ev_top1−top5 | ev_seen−corr |")
    print(f"|------------|---------:|----------:|--------:|-------------:|-------------:|")
    for config_name in SLIDER_CONFIGS.keys():
        if config_name not in results or 'lookahead' not in results[config_name]:
            continue
        cell = results[config_name]['lookahead']
        dom_count = cell['top_teams'][0]['count'] if cell['top_teams'] else 0
        dom_pct = f"{(dom_count / cell['n_chains']) * 100:.0f}%" if cell['n_chains'] else "—"
        print(f"| {config_name:<10} | {cell['n_distinct_teams']:>8} | {dom_count:>9} | "
              f"{dom_pct:>7} | {fmt_int(cell['ev_top1_minus_top5']):>12} | "
              f"{fmt_int(cell['ev_best_seen_minus_corroborated']):>12} |")

    # Cross-config for the smoothest non-lookahead at A_saved (smallest distinct count)
    smoothest = None
    if 'A_saved' in results:
        candidates = [(s['name'], results['A_saved'].get(s['name'], {}).get('n_distinct_teams', 999))
                      for s in STRATEGIES if s['name'] != 'lookahead']
        candidates = [(n, d) for n, d in candidates if d != 999]
        if candidates:
            smoothest = min(candidates, key=lambda x: x[1])[0]
    if smoothest:
        print(f"\n### Cross-config for {smoothest} (smoothest non-lookahead at A_saved)")
        print(f"\n| config     | distinct | dom_count | dom_pct | ev_top1−top5 | ev_seen−corr |")
        print(f"|------------|---------:|----------:|--------:|-------------:|-------------:|")
        for config_name in SLIDER_CONFIGS.keys():
            if config_name not in results or smoothest not in results[config_name]:
                continue
            cell = results[config_name][smoothest]
            dom_count = cell['top_teams'][0]['count'] if cell['top_teams'] else 0
            dom_pct = f"{(dom_count / cell['n_chains']) * 100:.0f}%" if cell['n_chains'] else "—"
            print(f"| {config_name:<10} | {cell['n_distinct_teams']:>8} | {dom_count:>9} | "
                  f"{dom_pct:>7} | {fmt_int(cell['ev_top1_minus_top5']):>12} | "
                  f"{fmt_int(cell['ev_best_seen_minus_corroborated']):>12} |")

    # Persist for re-analysis (merge-aware: results dict already includes
    # any prior cells loaded from disk plus this run's fresh cells).
    payload = {
        config_name: {
            sname: {
                **{k: v for k, v in cell.items() if k != 'top_teams'},
                'top_teams': cell['top_teams'],
            }
            for sname, cell in by_strat.items()
        }
        for config_name, by_strat in results.items()
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nResults persisted to {RESULTS_PATH}")

    if args.analyze_objectives:
        cells_for_analysis = (
            target_cells
            if target_cells
            else {(c, s) for c, by in results.items() for s in by}
        )
        analyze_objectives(results, cells_for_analysis)


if __name__ == '__main__':
    main()
