"""
N-curve diagnostic — canonical reproducer for multi-start SA sampling calibration.

NOTE (S17-26): the `low-transfer` strategy was retired from the live
optimizer. This diagnostic retains the strategy entry for archaeological
re-runs against pre-retirement git revisions. Current-codebase invocations
will produce a different output shape (3 strategies, not 4) — re-run from
a checkout of an earlier commit if you need the historical N-curve including
low-transfer.

Originally produced for S17-21 Phase 1.5 (May 10 2026) to determine the right
N value for Phase 2's uniform-N choice. Re-run when:
  - hyperparameter changes (S17-22 lookahead sweep, future SA tuning)
  - mid-Giro re-baselining (S18-1)
  - Tour-prep recalibration

Canonical reproducer:
  - Stage:        3
  - Sliders n1:   neutral (25/25/25/25)
  - Sliders n2/n3: defaults (50/30/10/10, 30/30/30/10)
  - Tickbox:      OFF (use_race_type_adjustment=False)
  - Force_in/out: empty
  - N values:     {5, 10, 20, 50}

Snapshot dependencies (read from shared/data/snapshots/):
  - stage_3_odds.json
  - stage_3_intel.json
  - stage_3_holdet.json (for budget; falls back to default if absent)
  - stage_2_results.json (for current_team)

Seed-nesting property: chain_xor = 0xC0 + chain_index for index ∈ [0, N).
Means the first K chains of an N=K' run (K < K') are identical to a
complete N=K run — `ev_best` is monotonically non-decreasing as N grows
(implicit nesting verification).

Read-only. Calls optimizer functions directly. Mirrors server.py /run-optimizer
setup but parameterises chain count N. Outputs per-N per-strategy summary
(ev_best, ev_spread, convergence_count, unique_teams, runtime, top-5 EVs).

Usage:
    python3 claude/diagnostics/n_curve_diagnostic.py

Persists raw results to /tmp/n_curve_results.json for re-analysis.
"""
import json
import os
import sys
import time
from collections import defaultdict

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
    BUDGET,
)

SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE  = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')

STAGE = 3
N_VALUES = [5, 10, 20, 50]

# Same payload semantics as the dashboard sends:
SLIDERS = {
    "n1": {"bunch_sprint": 25, "reduced_sprint": 25, "gc": 25, "breakaway": 25},  # neutral
    "n2": {"bunch_sprint": 50, "reduced_sprint": 30, "gc": 10, "breakaway": 10},  # default-ish
    "n3": {"bunch_sprint": 30, "reduced_sprint": 30, "gc": 30, "breakaway": 10},  # default-ish
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

    # Current team = previous stage's results
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
    """Same identity scheme as Phase 1's diagnostic logging."""
    return tuple(sorted(
        str(r.get('holdet_id') if r.get('holdet_id') is not None else r.get('name', ''))
        for r in team
    ))


def run_strategy_chains(strategy, candidates, probabilities, all_riders,
                         force_in, force_out, budget,
                         stage_config, scoring,
                         current_team,
                         cost_n1, cost_n2, team_n1, team_n2,
                         base_seed, eval_seed_shared, n_chains):
    """Reproduces Phase 1's per-strategy multi-chain loop with parametric N."""
    chain_seeds = [base_seed ^ (strategy['strategy_xor'] << 8) ^ (0xC0 + i)
                   for i in range(n_chains)]
    chain_results = []
    t0 = time.time()
    for ci, ch_seed in enumerate(chain_seeds):
        team_ci, _ev_ci, _diags = simulated_annealing(
            candidates, probabilities, force_in, force_out,
            budget=strategy['max_budget'],
            n_iter=strategy['n_iter'],
            max_seconds=strategy['max_seconds'],
            seed=ch_seed,
            objective=strategy['objective'],
            verbose=False,
            cost_n1=cost_n1, cost_n2=cost_n2,
            team_n1=team_n1, team_n2=team_n2,
            current_team=current_team,
        )
        if team_ci is None:
            continue
        team_ci = topup_team(team_ci, candidates, probabilities, all_riders,
                             strategy['max_budget'])
        captain_ci = select_captain(team_ci, probabilities)
        sim_ci = simulate_stage(
            team_ci, probabilities, captain_ci['name'],
            all_riders=all_riders,
            stage_config=stage_config, scoring=scoring,
            seed=eval_seed_shared,
        )
        chain_results.append({
            'index':   ci,
            'ev':      int(sim_ci['mean']),
            'team_id': _team_id(team_ci),
        })
    elapsed = time.time() - t0
    return chain_results, elapsed


def _aggregate(chain_results):
    """Phase-1-equivalent summary."""
    if not chain_results:
        return {'ev_best': None, 'ev_spread': 0, 'convergence_count': 0,
                'unique_teams': 0, 'evs_sorted': []}
    best = max(chain_results, key=lambda c: c['ev'])
    ev_list = [c['ev'] for c in chain_results]
    convergence_count = sum(1 for c in chain_results if c['team_id'] == best['team_id'])
    unique_teams      = len({c['team_id'] for c in chain_results})
    return {
        'ev_best':           best['ev'],
        'ev_spread':         max(ev_list) - min(ev_list),
        'convergence_count': convergence_count,
        'unique_teams':      unique_teams,
        'evs_sorted':        sorted(ev_list, reverse=True),
    }


def main():
    print("Loading inputs ...", flush=True)
    active_riders, odds, intel, budget, current_team = _load_data()
    print(f"  active_riders={len(active_riders)}, odds_rows={len(odds)}, "
          f"intel_signals={len(intel.get('intel', intel).get('key_signals', []))}, "
          f"current_team={'set' if current_team else 'None'}, budget={budget:,}", flush=True)

    scoring      = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    base_seed = compute_seed(STAGE, SLIDERS, FORCE_IN, FORCE_OUT, USE_RACE_TYPE)
    print(f"  base_seed={base_seed}", flush=True)

    probs_current = build_probabilities(
        active_riders, odds, intel, SLIDERS.get('n1', {}),
        stage_config=stage_config, scoring=scoring,
        use_race_type=USE_RACE_TYPE,
    )
    probs_n1_fwd = build_forward_probabilities(active_riders, SLIDERS.get('n2', {}))
    probs_n2_fwd = build_forward_probabilities(active_riders, SLIDERS.get('n3', {}))

    proxy_seed = base_seed ^ 0xF
    proxy = current_team or fast_optimize(
        active_riders, probs_current, active_riders, FORCE_IN, FORCE_OUT, budget,
        seed=proxy_seed,
    )
    cost_n1, cost_n2, n_tr_n1, n_tr_n2, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], active_riders, active_riders,
        probs_n1_fwd, probs_n2_fwd, FORCE_IN, FORCE_OUT, budget,
        seed=base_seed,
    )

    eval_seed_shared = base_seed ^ 0xF

    strategies = [
        {'name': 'optimal',      'strategy_xor': 0x1,
         'objective': 'ev',           'max_budget': budget,
         'n_iter': 200_000, 'max_seconds': 5},
        {'name': 'depth',        'strategy_xor': 0x2,
         'objective': 'depth',        'max_budget': budget,
         'n_iter': 200_000, 'max_seconds': 5},
        {'name': 'low-transfer', 'strategy_xor': 0x3,
         'objective': 'low_transfer', 'max_budget': budget,
         'n_iter': 200_000, 'max_seconds': 5},
        {'name': 'lookahead',    'strategy_xor': 0x4,
         'objective': 'lookahead',    'max_budget': budget,
         'n_iter': 200_000, 'max_seconds': 5},
    ]

    # results[strategy_name][N] = {summary dict + 'runtime_seconds'}
    results = defaultdict(dict)
    total_t0 = time.time()
    for strategy in strategies:
        for N in N_VALUES:
            print(f"\n{strategy['name']:<14} N={N:<3} running ...", flush=True)
            chain_results, elapsed = run_strategy_chains(
                strategy, active_riders, probs_current, active_riders,
                FORCE_IN, FORCE_OUT, budget,
                stage_config, scoring,
                current_team,
                cost_n1, cost_n2, team_n1, team_n2,
                base_seed, eval_seed_shared, N,
            )
            agg = _aggregate(chain_results)
            agg['runtime_seconds'] = elapsed
            results[strategy['name']][N] = agg
            print(f"  ev_best={agg['ev_best']:>9}  spread={agg['ev_spread']:>7}  "
                  f"conv={agg['convergence_count']}/{N}  unique={agg['unique_teams']}/{N}  "
                  f"runtime={elapsed:.1f}s", flush=True)
    print(f"\ntotal runtime: {time.time() - total_t0:.1f}s", flush=True)

    # Markdown report
    print("\n\n=========================== MARKDOWN REPORT ===========================\n")
    for strategy in strategies:
        name = strategy['name']
        print(f"### {name}")
        print()
        print(f"| N  | ev_best     | ev_spread | conv | unique | runtime")
        print(f"|----|-------------|-----------|------|--------|--------")
        for N in N_VALUES:
            r = results[name][N]
            ev_best = f"{r['ev_best']:,}" if r['ev_best'] is not None else "—"
            print(f"| {N:<2} | {ev_best:>11} | {r['ev_spread']:>9,} | "
                  f"{r['convergence_count']:>2}/{N:<2} | "
                  f"{r['unique_teams']:>2}/{N:<2} | {r['runtime_seconds']:.1f}s")
        # Top-5 EVs at largest N
        top_evs = results[name][N_VALUES[-1]]['evs_sorted'][:5]
        print()
        print(f"  Top-5 EVs at N={N_VALUES[-1]}: {top_evs}")
        print()

    # Persist for re-analysis
    payload = {n: {str(N): r for N, r in by_n.items()} for n, by_n in results.items()}
    with open('/tmp/n_curve_results.json', 'w') as f:
        json.dump(payload, f, indent=2)
    print("Raw results saved to /tmp/n_curve_results.json")


if __name__ == '__main__':
    main()
