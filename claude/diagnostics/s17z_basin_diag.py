"""S17-ζ basin-search failure diagnostic — Stage 5 lookahead Magnier case.

Tests:
  T1. 10-chain final objective distribution UNCONSTRAINED.
      Question: how many chains land in keep-Magnier basin (~-115k)?
      How many in drop-Magnier basin (~-234k)?
  T2. 10-chain final objective distribution FORCE-IN Magnier (sanity check
      that the basin is correctly evaluated as -115k).
  T3. Per-iteration trajectory for one chain that started with Magnier
      and ended without — when does Magnier get dropped and why.
  T4. Initialization diversity check — how many of the 10 initial random
      teams contain Magnier?

Read-only. Uses optimizer functions directly with the same setup as
/run-optimizer for Stage 5 lookahead.
"""
import json, os, sys, time, math, random
from collections import Counter

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    compute_seed,
    build_probabilities,
    build_forward_probabilities,
    estimate_forward_costs,
    simulated_annealing,
    select_captain,
    fast_optimize,
    load_stage_scoring,
    get_stage_config,
    add_stage_evs,
    compute_team_ev,
    compute_objective,
    INTEL_MULT,
)

STAGE     = 5
TARGET    = 'Paul Magnier'
N_CHAINS  = 10
LOOKAHEAD_XOR     = 0x4
CHAIN_XOR_MASKS   = tuple(0xC0 + i for i in range(N_CHAINS))
COOLING_RATE      = 0.99999  # lookahead override per generate_candidate_teams
MAX_SECONDS       = 5
N_ITER            = 200_000

SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE  = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')


def _load():
    odds = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_odds.json')))
    if isinstance(odds, dict):
        odds = odds.get('odds', odds)
    intel = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_intel.json')))
    riders_doc = json.load(open(RIDERS_FILE))
    active = [r for r in riders_doc['riders'] if not r.get('isOut') and r.get('status') != 'dns']
    # server.py falls back to 50M if stage_{N}_holdet.json absent
    holdet_path = os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_holdet.json')
    holdet = json.load(open(holdet_path)) if os.path.exists(holdet_path) else {}
    budget = int(holdet.get('bank_balance', 50_000_000))
    # current team from prev stage results
    res_path = os.path.join(SNAPSHOT_DIR, f'stage_{STAGE-1}_results.json')
    current_team = None
    if os.path.exists(res_path):
        res = json.load(open(res_path))
        names = [r['name'] for r in res.get('rider_results', []) if r.get('name')]
        by_name = {r['name']: r for r in active}
        current_team = [by_name[n] for n in names if n in by_name] or None
    return active, odds, intel, budget, current_team


def _run_chains(active, probs, probs_n1, probs_n2, force_in, force_out, budget,
                cost_n1, cost_n2, team_n1, team_n2, current_team, base_seed,
                instrument_trajectory=False):
    """Run N=10 SA chains under lookahead config; capture per-chain results."""
    chain_results = []
    for ci, chain_xor in enumerate(CHAIN_XOR_MASKS):
        ch_seed = base_seed ^ (LOOKAHEAD_XOR << 8) ^ chain_xor

        # Capture initial team by replicating the SA init path (same RNG seed)
        from optimizer import get_valid_random_team
        forced_set   = set(force_in or [])
        excluded_set = set(force_out or [])
        forced = [r for r in active if r['name'] in forced_set]
        pool   = [r for r in active
                  if r['name'] not in excluded_set and r['name'] not in forced_set]
        init_rng = random.Random(ch_seed)
        initial_team = get_valid_random_team(forced, pool, budget, rng=init_rng)
        initial_names = [r['name'] for r in initial_team] if initial_team else []

        # Now run the actual SA chain (its rng will produce the same initial)
        team, sa_ev, diags = simulated_annealing(
            active, probs, force_in, force_out,
            budget=budget, n_iter=N_ITER, max_seconds=MAX_SECONDS,
            seed=ch_seed, objective='lookahead',
            cost_n1=cost_n1, cost_n2=cost_n2,
            team_n1=team_n1, team_n2=team_n2,
            current_team=current_team,
            cooling_rate=COOLING_RATE,
        )
        final_names = sorted(r['name'] for r in team)
        final_obj = compute_objective(team, probs, active, 'lookahead',
                                      cost_n1, cost_n2, team_n1, team_n2,
                                      current_team=current_team)
        chain_results.append({
            'chain': ci, 'seed': ch_seed,
            'initial_has_magnier': TARGET in initial_names,
            'final_has_magnier':   TARGET in final_names,
            'final_obj':           final_obj,
            'final_team':          final_names,
            'iters':               diags['iters'],
            'acceptance_rate':     diags['acceptance_rate'],
        })
    return chain_results


def _print_summary(label, chain_results):
    print(f'\n=== {label} ===')
    print(f'{"chain":<6}{"seed":>15}  {"init_M?":<8}{"final_M?":<9}{"final_obj":>12}  iters    acc_rate')
    for c in chain_results:
        print(f"  {c['chain']:<4}{c['seed']:>15}  {str(c['initial_has_magnier']):<8}"
              f"{str(c['final_has_magnier']):<9}{c['final_obj']:>12,.0f}  "
              f"{c['iters']:>6,}  {c['acceptance_rate']:.3f}")
    n_init_m  = sum(c['initial_has_magnier'] for c in chain_results)
    n_final_m = sum(c['final_has_magnier']   for c in chain_results)
    print(f"  → {n_init_m}/{len(chain_results)} chains START with Magnier; "
          f"{n_final_m}/{len(chain_results)} END with Magnier")
    # Group by final team
    team_groups = Counter(tuple(c['final_team']) for c in chain_results)
    print(f"  → {len(team_groups)} distinct final basins:")
    for team, count in sorted(team_groups.items(), key=lambda kv: -kv[1]):
        objs = [c['final_obj'] for c in chain_results if tuple(c['final_team']) == team]
        avg_obj = sum(objs) / len(objs)
        has_m = TARGET in team
        print(f"      basin (N={count}, M={has_m}): avg_obj={avg_obj:>12,.0f}  "
              f"sample_team={', '.join(team[:3])}, …")


def main():
    print('Loading Stage 5 inputs …')
    active, odds, intel, budget, current_team = _load()
    print(f'  active={len(active)} odds={len(odds)} budget={budget:,} '
          f'current_team={len(current_team) if current_team else "None"}')
    if current_team:
        ct_names = {r['name'] for r in current_team}
        print(f'  current_team has Magnier? {TARGET in ct_names}')

    scoring      = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    # Dashboard's current sliders are in localStorage only; use defaults (n1=70/20/5/5
    # etc. per renderSliders init)
    sliders = {
        'n1': {'bunch_sprint': 70, 'reduced_sprint': 20, 'breakaway': 5,  'gc': 5},
        'n2': {'bunch_sprint': 50, 'reduced_sprint': 30, 'breakaway': 10, 'gc': 10},
        'n3': {'bunch_sprint': 30, 'reduced_sprint': 30, 'breakaway': 10, 'gc': 30},
    }
    use_race_type = False

    # Build probabilities for current + forward
    probs    = build_probabilities(active, odds, intel, sliders.get('n1', {}),
                                   stage_config=stage_config, scoring=scoring,
                                   use_race_type=use_race_type)
    probs_n1 = build_forward_probabilities(active, sliders.get('n2', {}))
    probs_n2 = build_forward_probabilities(active, sliders.get('n3', {}))

    # Test 1 — unconstrained
    force_in_unc, force_out_unc = [], []
    base_seed_unc = compute_seed(STAGE, sliders, force_in_unc, force_out_unc, use_race_type)
    print(f'\nUnconstrained base_seed: {base_seed_unc}')
    # Forward costs (proxy via fast_optimize)
    proxy_unc = current_team or fast_optimize(active, probs, active,
                                              force_in_unc, force_out_unc, budget,
                                              seed=base_seed_unc ^ 0xF)
    cost_n1_unc, cost_n2_unc, n_tr_n1_unc, n_tr_n2_unc, team_n1_unc, team_n2_unc = \
        estimate_forward_costs(proxy_unc or [], active, active,
                               probs_n1, probs_n2, force_in_unc, force_out_unc, budget,
                               seed=base_seed_unc)
    print(f'  cost_n1={cost_n1_unc:,.0f} ({n_tr_n1_unc} tr)  '
          f'cost_n2={cost_n2_unc:,.0f} ({n_tr_n2_unc} tr)')

    t0 = time.time()
    chains_unc = _run_chains(active, probs, probs_n1, probs_n2,
                             force_in_unc, force_out_unc, budget,
                             cost_n1_unc, cost_n2_unc, team_n1_unc, team_n2_unc,
                             current_team, base_seed_unc)
    print(f'  → {N_CHAINS} chains in {time.time()-t0:.1f}s')
    _print_summary('Test 1 — UNCONSTRAINED Stage 5 lookahead', chains_unc)

    # Magnier's current-stage ev_cache value (the signal biased-swap uses to pick "worst")
    magnier_ev = probs.get(TARGET, {}).get('total_ev', 0.0)
    print(f"\n[ev_cache probe] Magnier total_ev on Stage 5 = {magnier_ev:,.0f}")
    # Distribution of total_ev values across all riders
    all_evs = sorted(((r['name'], probs.get(r['name'], {}).get('total_ev', 0.0))
                       for r in active),
                     key=lambda x: x[1])
    print(f"  Bottom-5 by total_ev:")
    for n, e in all_evs[:5]:
        print(f"    {n:<35} {e:>10,.0f}")
    # Magnier's rank from bottom
    mag_rank = next(i for i, (n, _) in enumerate(all_evs) if n == TARGET)
    print(f"  Magnier rank from bottom: {mag_rank} (of {len(all_evs)})")
    print(f"  Top-50 EV pool threshold (the biased-swap candidate pool):")
    top50_threshold = sorted(all_evs, key=lambda x: -x[1])[49][1]
    print(f"    50th-best EV: {top50_threshold:,.0f}  → Magnier {'IN' if magnier_ev >= top50_threshold else 'OUT'} of top-50")

    # Test 2 — force_in Magnier
    force_in_fi, force_out_fi = [TARGET], []
    base_seed_fi = compute_seed(STAGE, sliders, force_in_fi, force_out_fi, use_race_type)
    print(f'\nForce-in base_seed: {base_seed_fi}')
    proxy_fi = current_team or fast_optimize(active, probs, active,
                                             force_in_fi, force_out_fi, budget,
                                             seed=base_seed_fi ^ 0xF)
    cost_n1_fi, cost_n2_fi, n_tr_n1_fi, n_tr_n2_fi, team_n1_fi, team_n2_fi = \
        estimate_forward_costs(proxy_fi or [], active, active,
                               probs_n1, probs_n2, force_in_fi, force_out_fi, budget,
                               seed=base_seed_fi)
    print(f'  cost_n1={cost_n1_fi:,.0f} ({n_tr_n1_fi} tr)  '
          f'cost_n2={cost_n2_fi:,.0f} ({n_tr_n2_fi} tr)')

    t0 = time.time()
    chains_fi = _run_chains(active, probs, probs_n1, probs_n2,
                            force_in_fi, force_out_fi, budget,
                            cost_n1_fi, cost_n2_fi, team_n1_fi, team_n2_fi,
                            current_team, base_seed_fi)
    print(f'  → {N_CHAINS} chains in {time.time()-t0:.1f}s')
    _print_summary('Test 2 — FORCE-IN Magnier Stage 5 lookahead', chains_fi)

    # Test 4 — initialization diversity (already captured above as initial_has_magnier)
    print('\n=== Test 4 — Initialization diversity ===')
    print(f'  Unconstrained: {sum(c["initial_has_magnier"] for c in chains_unc)}/{N_CHAINS} '
          f'initial teams contain Magnier')
    print(f'  Force-in:      {sum(c["initial_has_magnier"] for c in chains_fi)}/{N_CHAINS} '
          f'initial teams contain Magnier (by construction, all 10 since forced)')


if __name__ == '__main__':
    main()
