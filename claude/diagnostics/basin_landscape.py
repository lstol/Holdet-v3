"""
Basin landscape diagnostic — S17-22-followup Phase 1.

Characterises per-strategy basin landscape across three slider configurations
of Stage 2. Drives Phase 2's case classification (A/B/C/D) for the lookahead
strategy and informs whether the convergence problem is hyperparameter-tunable,
landscape-intrinsic, false-corroboration risk, or a strategy-specific
pathology.

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
    python3 claude/diagnostics/basin_landscape.py
"""
import json
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


def run_cell(strategy, sliders, active_riders, odds, intel, budget,
             current_team, scoring, stage_config, deadline_total):
    """Run N_CHAINS chains for one (config, strategy) cell.

    Returns (chain_results, elapsed, status, captured_teams).
    status ∈ {'ok', 'cell_timeout', 'total_timeout'}.
    captured_teams: dict team_id → team list (one representative team).
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
        chain_results.append({
            'index':   ci,
            'ev':      int(sim_ci['mean']),
            'team_id': tid,
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


def main():
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

    # results[config_name][strategy_name] = {agg + 'elapsed' + 'status'}
    results = defaultdict(dict)
    aborted = False
    for config_name, sliders in SLIDER_CONFIGS.items():
        if aborted:
            break
        for strategy in STRATEGIES:
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
            results[config_name][strategy['name']] = {
                **agg, 'elapsed': elapsed, 'status': status,
            }
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

    print(f"\n========================== PER-CELL DETAIL ==========================")
    for config_name in SLIDER_CONFIGS.keys():
        if config_name not in results:
            continue
        print(f"\n### Config {config_name}")
        for strategy in STRATEGIES:
            sname = strategy['name']
            if sname not in results[config_name]:
                continue
            cell = results[config_name][sname]
            print_cell_section(config_name, sname, cell, cell['status'], cell['elapsed'])

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

    # Persist for re-analysis
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
    out_path = '/tmp/basin_landscape_results.json'
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nRaw results saved to {out_path}")


if __name__ == '__main__':
    main()
