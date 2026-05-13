"""S17-ζ-redo per-chain enumeration: run 10 lookahead SA chains under the
captured Stage 5 reproducer payload, capture EACH chain's:
  - Final roster
  - Final stage-EV (simulate_stage mean)
  - Final lookahead-objective value (ev_estimate − tc_current − cost_n1 − 0.7·cost_n2)
  - Magnier in final roster?

Critical comparison: the cross-chain selection at optimizer.py:1193 picks
max by stage-EV, NOT by lookahead-objective. If the 9/10 corroborated basin
has a BETTER lookahead-objective than the 1/10 best-seen basin, that's the
bug.

Read-only. Uses the same compute_seed → simulated_annealing path as live
/run-optimizer for lookahead. Substrate matches live snapshots (verified).
"""
import json, os, sys, time
from collections import Counter

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
    compute_team_ev,
    compute_transfer_cost,
    load_stage_scoring,
    get_stage_config,
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

# Captured payload sliders
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


def run_chains(active, odds, intel, budget, current_team, force_in, force_out, label):
    scoring = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    probs    = build_probabilities(active, odds, intel, SLIDERS.get('n1', {}),
                                   stage_config=stage_config, scoring=scoring,
                                   use_race_type=False)
    probs_n1 = build_forward_probabilities(active, SLIDERS.get('n2', {}))
    probs_n2 = build_forward_probabilities(active, SLIDERS.get('n3', {}))

    base_seed = compute_seed(STAGE, SLIDERS, force_in, force_out, False)
    proxy = current_team or fast_optimize(active, probs, active,
                                          force_in, force_out, budget,
                                          seed=base_seed ^ 0xF)
    cost_n1, cost_n2, n_tr_n1, n_tr_n2, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], active, active, probs_n1, probs_n2,
        force_in, force_out, budget, seed=base_seed,
    )
    print(f'\n=== {label} ===')
    print(f'  base_seed: {base_seed}  proxy_cost_n1: {cost_n1:,.0f} ({n_tr_n1} tr)  '
          f'proxy_cost_n2: {cost_n2:,.0f} ({n_tr_n2} tr)')
    eval_seed_shared = base_seed ^ 0xF

    rows = []
    for ci, chain_xor in enumerate(CHAIN_XOR_MASKS):
        ch_seed = base_seed ^ (LOOKAHEAD_XOR << 8) ^ chain_xor
        team_ci, _, sa_diags = simulated_annealing(
            active, probs, force_in, force_out,
            budget=budget, n_iter=N_ITER, max_seconds=MAX_SECONDS,
            seed=ch_seed, objective='lookahead',
            cost_n1=cost_n1, cost_n2=cost_n2,
            team_n1=team_n1, team_n2=team_n2,
            current_team=current_team,
            cooling_rate=COOLING_RATE,
        )
        if team_ci is None:
            continue
        team_ci = topup_team(team_ci, active, probs, active, budget)
        captain_ci = select_captain(team_ci, probs)
        sim_ci = simulate_stage(team_ci, probs, captain_ci['name'],
                                all_riders=active,
                                stage_config=stage_config, scoring=scoring,
                                seed=eval_seed_shared)
        # Per-chain actual transfer cost + actual forward costs (vs proxy)
        actual_tc = compute_transfer_cost(team_ci, current_team or [])
        actual_cost_n1 = compute_transfer_cost(team_ci, team_n1 or []) if team_n1 else 0
        actual_cost_n2 = compute_transfer_cost(team_ci, team_n2 or []) if team_n2 else 0
        # Lookahead objective using THIS chain's actual costs
        # (matches what /run-optimizer reports post-chain selection)
        ev_estimate = int(sim_ci['mean'])
        lookahead_obj = ev_estimate - actual_tc - actual_cost_n1 - LOOKAHEAD_DISCOUNT * actual_cost_n2
        # Team identity (matches optimizer.py:1183-1186)
        team_id = tuple(sorted(
            str(r.get('holdet_id') if r.get('holdet_id') is not None else r.get('name', ''))
            for r in team_ci
        ))
        rows.append({
            'chain': ci, 'seed': ch_seed, 'team_id': team_id,
            'ev_estimate': ev_estimate,
            'actual_tc': actual_tc,
            'actual_cost_n1': actual_cost_n1,
            'actual_cost_n2': actual_cost_n2,
            'lookahead_obj': lookahead_obj,
            'has_magnier': any(r['name'] == TARGET for r in team_ci),
            'roster': sorted(r['name'] for r in team_ci),
        })
    return rows, cost_n1, cost_n2, team_n1, team_n2


def print_table(rows, label):
    print(f'\n  ─── {label} per-chain table ───')
    print(f"  {'ch':<3} {'team_id_hash':<11} {'M?':<3} {'ev_est':>10} {'tc':>9} {'c_n1':>9} {'c_n2':>9} {'look_obj':>11}")
    for r in rows:
        # Hash the team_id to a short string for grouping visibility
        th = hex(abs(hash(r['team_id'])) % 0xFFFFFFFF)[2:]
        print(f"  {r['chain']:<3} {th:<11} {'Y' if r['has_magnier'] else '·':<3} "
              f"{r['ev_estimate']:>10,} {r['actual_tc']:>9,} "
              f"{r['actual_cost_n1']:>9,} {r['actual_cost_n2']:>9,} "
              f"{r['lookahead_obj']:>11,.0f}")
    # Group by team_id
    teams = Counter(r['team_id'] for r in rows)
    print(f"  ─── Distinct basins: {len(teams)} ───")
    for tid, cnt in sorted(teams.items(), key=lambda kv: -kv[1]):
        sample = next(r for r in rows if r['team_id'] == tid)
        print(f"      N={cnt}  M={'Y' if sample['has_magnier'] else '·'}  "
              f"ev_est={sample['ev_estimate']:,}  look_obj={sample['lookahead_obj']:>10,.0f}  "
              f"roster_first3={sample['roster'][:3]}")


def main():
    active, odds, intel, budget, current_team = _load()
    print(f'Loaded Stage 5: active={len(active)} odds={len(odds)} budget={budget:,} '
          f'current_team={len(current_team) if current_team else 0}')
    if current_team:
        print(f'  current_team has Magnier? {any(r["name"]==TARGET for r in current_team)}')

    # Run unconstrained
    rows_unc, c1_unc, c2_unc, _, _ = run_chains(active, odds, intel, budget,
                                                 current_team, [], [],
                                                 'UNCONSTRAINED')
    print_table(rows_unc, 'unconstrained')

    # Identify the displayed (best stage-EV) chain
    best_idx = max(range(len(rows_unc)),
                   key=lambda j: (rows_unc[j]['ev_estimate'], -rows_unc[j]['chain']))
    best = rows_unc[best_idx]
    print(f'\n  → Cross-chain selection (max by ev_estimate): chain {best["chain"]} '
          f'ev_est={best["ev_estimate"]:,} look_obj={best["lookahead_obj"]:,.0f} '
          f'M={"Y" if best["has_magnier"] else "·"}')
    # Identify the corroborated basin (most popular team)
    teams = Counter(r['team_id'] for r in rows_unc)
    corr_id, corr_cnt = teams.most_common(1)[0]
    corr_row = next(r for r in rows_unc if r['team_id'] == corr_id)
    print(f'  → Corroborated basin (N={corr_cnt}): ev_est={corr_row["ev_estimate"]:,} '
          f'look_obj={corr_row["lookahead_obj"]:,.0f} '
          f'M={"Y" if corr_row["has_magnier"] else "·"}')

    # Compare lookahead-objective between best-seen and corroborated
    delta = best['lookahead_obj'] - corr_row['lookahead_obj']
    print(f'  → look_obj delta (best-seen − corroborated): {delta:+,.0f}')
    if delta > 0:
        print(f'    Best-seen has HIGHER lookahead-obj — selection is correct.')
    elif delta < 0:
        print(f'    Best-seen has LOWER lookahead-obj — cross-chain selection is dropping '
              f'the better basin! This is the bug.')
    else:
        print(f'    Same lookahead-obj — no discrimination needed.')

    # Force-in chains for comparison
    rows_fi, c1_fi, c2_fi, _, _ = run_chains(active, odds, intel, budget,
                                              current_team, [TARGET], [],
                                              'FORCE-IN Magnier')
    print_table(rows_fi, 'force-in')
    if rows_fi:
        fi_best = max(rows_fi, key=lambda r: r['ev_estimate'])
        print(f'\n  → Force-in displayed: ev_est={fi_best["ev_estimate"]:,} '
              f'look_obj={fi_best["lookahead_obj"]:,.0f}  (per-chain magnier? '
              f'all={sum(r["has_magnier"] for r in rows_fi)}/{len(rows_fi)})')

if __name__ == '__main__':
    main()
