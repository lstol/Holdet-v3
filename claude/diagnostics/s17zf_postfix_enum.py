"""S17-ζ-fix V8 verification: per-chain enumeration with new seed_team logic.

Replicates the live optimizer's chain orchestration for Stage 5 lookahead
under breakaway-80% sliders. Chain 0 uses seed_team=current_team (fix a).
All chains union current_team into top_n_pool (fix d, automatic inside SA).
Per-chain look_obj computed for fix (c) inspection.
"""
import json, os, sys, time
from collections import Counter

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    compute_seed, build_probabilities, build_forward_probabilities,
    estimate_forward_costs, simulated_annealing, simulate_stage,
    select_captain, topup_team, fast_optimize, compute_transfer_cost,
    load_stage_scoring, get_stage_config,
)

STAGE     = 5
TARGET    = 'Paul Magnier'
N_CHAINS  = 10
LOOKAHEAD_XOR     = 0x4
CHAIN_XOR_MASKS   = tuple(0xC0 + i for i in range(N_CHAINS))
COOLING_RATE      = 0.99999
MAX_SECONDS       = 5
N_ITER            = 200_000
LOOKAHEAD_DISCOUNT = 0.7

SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE  = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')

SLIDERS = {
    'n1': {'bunch_sprint': 0,   'reduced_sprint': 20, 'gc': 0,  'breakaway': 80},
    'n2': {'bunch_sprint': 100, 'reduced_sprint': 0,  'gc': 0,  'breakaway': 0},
    'n3': {'bunch_sprint': 0,   'reduced_sprint': 0,  'gc': 80, 'breakaway': 20},
}


def _load():
    odds = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_odds.json')))
    if isinstance(odds, dict):
        odds = odds.get('odds', odds)
    intel = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_intel.json')))
    riders_doc = json.load(open(RIDERS_FILE))
    active = [r for r in riders_doc['riders']
              if not r.get('isOut') and r.get('status') != 'dns']
    holdet_path = os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_holdet.json')
    holdet = json.load(open(holdet_path)) if os.path.exists(holdet_path) else {}
    budget = int(holdet.get('bank_balance', 50_000_000))
    res = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE-1}_results.json')))
    names = [r['name'] for r in res.get('rider_results', []) if r.get('name')]
    by_name = {r['name']: r for r in active}
    current_team = [by_name[n] for n in names if n in by_name] or None
    return active, odds, intel, budget, current_team


def run(force_in, force_out, label):
    active, odds, intel, budget, current_team = _load()
    scoring = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    probs    = build_probabilities(active, odds, intel, SLIDERS['n1'],
                                   stage_config=stage_config, scoring=scoring,
                                   use_race_type=False)
    probs_n1 = build_forward_probabilities(active, SLIDERS['n2'])
    probs_n2 = build_forward_probabilities(active, SLIDERS['n3'])

    base_seed = compute_seed(STAGE, SLIDERS, force_in, force_out, False)
    proxy = current_team or fast_optimize(active, probs, active,
                                          force_in, force_out, budget,
                                          seed=base_seed ^ 0xF)
    cost_n1, cost_n2, _, _, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], active, active, probs_n1, probs_n2,
        force_in, force_out, budget, seed=base_seed,
    )
    eval_seed_shared = base_seed ^ 0xF

    print(f'\n=== {label} (current_team has Magnier: {current_team and any(r["name"]==TARGET for r in current_team)}) ===')
    rows = []
    for ci, chain_xor in enumerate(CHAIN_XOR_MASKS):
        ch_seed = base_seed ^ (LOOKAHEAD_XOR << 8) ^ chain_xor
        # S17-ζ-fix (a) wiring: chain 0 gets seed_team=current_team
        seed_team = current_team if (ci == 0 and current_team) else None
        team_ci, _, sa_diags = simulated_annealing(
            active, probs, force_in, force_out,
            budget=budget, n_iter=N_ITER, max_seconds=MAX_SECONDS,
            seed=ch_seed, objective='lookahead',
            cost_n1=cost_n1, cost_n2=cost_n2,
            team_n1=team_n1, team_n2=team_n2,
            current_team=current_team,
            cooling_rate=COOLING_RATE,
            seed_team=seed_team,
        )
        if team_ci is None:
            continue
        team_ci = topup_team(team_ci, active, probs, active, budget)
        captain_ci = select_captain(team_ci, probs)
        sim_ci = simulate_stage(team_ci, probs, captain_ci['name'],
                                all_riders=active,
                                stage_config=stage_config, scoring=scoring,
                                seed=eval_seed_shared)
        ev_est = int(sim_ci['mean'])
        tc = compute_transfer_cost(current_team or [], team_ci) if current_team else 0
        c_n1 = compute_transfer_cost(team_ci, team_n1 or []) if team_n1 else 0
        c_n2 = compute_transfer_cost(team_n1 or [], team_n2 or []) if team_n1 and team_n2 else 0
        look_obj = ev_est - tc - c_n1 - LOOKAHEAD_DISCOUNT * c_n2
        rows.append({
            'chain': ci, 'has_magnier': any(r['name'] == TARGET for r in team_ci),
            'ev_est': ev_est, 'tc': tc, 'c_n1': c_n1, 'c_n2': c_n2,
            'look_obj': look_obj, 'seed_team_used': seed_team is not None,
            'team_id': tuple(sorted(r['name'] for r in team_ci)),
        })

    print(f"  {'ch':<3} {'seed?':<6} {'M?':<3} {'ev_est':>10} {'tc':>9} {'c_n1':>9} {'c_n2':>9} {'look_obj':>11}")
    for r in rows:
        marker = '✓' if r['seed_team_used'] else '·'
        print(f"  {r['chain']:<3} {marker:<6} {'Y' if r['has_magnier'] else '·':<3} "
              f"{r['ev_est']:>10,} {r['tc']:>9,} {r['c_n1']:>9,} {r['c_n2']:>9,} "
              f"{r['look_obj']:>11,.0f}")
    teams = Counter(r['team_id'] for r in rows)
    print(f'  ─── Basins: {len(teams)} distinct')
    for tid, cnt in sorted(teams.items(), key=lambda kv: -kv[1]):
        sample = next(r for r in rows if r['team_id'] == tid)
        print(f'    N={cnt}  M={"Y" if sample["has_magnier"] else "·"}  '
              f'ev_est={sample["ev_est"]:,}  look_obj={sample["look_obj"]:,.0f}')

    if rows:
        # Cross-chain selection by look_obj (matching fix (c) logic)
        best_lo = max(rows, key=lambda r: (r['look_obj'], -r['chain']))
        best_ev = max(rows, key=lambda r: (r['ev_est'], -r['chain']))
        print(f"  ── Selection:")
        print(f"    look_obj-best (lookahead): chain {best_lo['chain']}, M={best_lo['has_magnier']}, "
              f"ev_est={best_lo['ev_est']:,} look_obj={best_lo['look_obj']:,.0f}")
        print(f"    ev_est-best (pre-fix):     chain {best_ev['chain']}, M={best_ev['has_magnier']}, "
              f"ev_est={best_ev['ev_est']:,} look_obj={best_ev['look_obj']:,.0f}")
    return rows


run([], [], 'UNCONSTRAINED post-fix')
run([TARGET], [], 'FORCE-IN Magnier post-fix')
