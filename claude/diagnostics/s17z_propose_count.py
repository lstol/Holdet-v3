"""S17-ζ Test 3 (adapted): count Magnier proposal frequency during one
unconstrained SA chain. If Magnier IS proposed but rejected, the basin-search
is correctly evaluating him; if NOT proposed, the proposal mechanism is
systematically blind to him."""
import json, os, sys, random, math, time
from collections import Counter

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))
from optimizer import (
    compute_seed, build_probabilities, build_forward_probabilities,
    estimate_forward_costs, get_valid_random_team, fast_optimize,
    compute_objective, compute_team_ev, load_stage_scoring, get_stage_config,
    INTEL_MULT, is_valid,
)

STAGE  = 5
TARGET = 'Paul Magnier'
SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE  = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')


def load():
    odds = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_odds.json')))
    if isinstance(odds, dict): odds = odds.get('odds', odds)
    intel = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE}_intel.json')))
    riders_doc = json.load(open(RIDERS_FILE))
    active = [r for r in riders_doc['riders'] if not r.get('isOut') and r.get('status') != 'dns']
    res = json.load(open(os.path.join(SNAPSHOT_DIR, f'stage_{STAGE-1}_results.json')))
    names = [r['name'] for r in res.get('rider_results', []) if r.get('name')]
    by_name = {r['name']: r for r in active}
    current_team = [by_name[n] for n in names if n in by_name] or None
    return active, odds, intel, current_team


def instrumented_sa(active, probs, force_in, force_out, budget, cost_n1, cost_n2,
                    team_n1, team_n2, current_team, seed, max_seconds=5,
                    cooling_rate=0.99999, biased_swap_prob=0.7, n_iter=200_000):
    rng = random.Random(seed)
    forced_set   = set(force_in or [])
    excluded_set = set(force_out or [])
    forced = [r for r in active if r['name'] in forced_set]
    pool   = [r for r in active
              if r['name'] not in excluded_set and r['name'] not in forced_set]
    n_forced = len(forced)
    ev_cache = {r['name']: probs.get(r['name'], {}).get('total_ev', 0.0) for r in pool}
    ev_cache.update({r['name']: probs.get(r['name'], {}).get('total_ev', 0.0) for r in forced})
    sorted_pool = sorted(pool, key=lambda r: ev_cache[r['name']], reverse=True)
    top_n_pool  = sorted_pool[:min(50, len(sorted_pool))]
    top_n_len   = len(top_n_pool)
    pool_len    = len(pool)
    target_in_pool = any(r['name'] == TARGET for r in pool)
    target_in_top50 = any(r['name'] == TARGET for r in top_n_pool)
    print(f"  Magnier in pool? {target_in_pool}  in top-50? {target_in_top50}")

    team = get_valid_random_team(forced, pool, budget, rng=rng)
    if team is None:
        return None, {}
    initial_has = any(r['name'] == TARGET for r in team)
    print(f"  initial team has Magnier? {initial_has}")

    current_score = compute_objective(team, probs, active, 'lookahead',
                                      cost_n1, cost_n2, team_n1, team_n2,
                                      current_team=current_team)
    best_team, best_score = team[:], current_score

    counters = {
        'iters': 0, 'accepts': 0, 'rejects': 0, 'skips': 0,
        'target_proposed_in': 0,    # times Magnier proposed as new_rider
        'target_proposed_out': 0,   # times Magnier was in team and proposed to swap out
        'target_swap_accepted': 0,  # times Magnier was added via accepted swap
        'target_swap_rejected': 0,
        'target_drop_accepted': 0,  # times Magnier dropped from team
        'target_drop_rejected': 0,
    }
    target_visits_iter = []  # iters when Magnier was in current team
    T = float(200_000)
    cooling = float(cooling_rate)
    start = time.time()
    i = 0
    while i < n_iter:
        if time.time() - start > max_seconds:
            break
        target_in_current = any(r['name'] == TARGET for r in team)
        if target_in_current:
            target_visits_iter.append(i)
        if n_forced >= 8: break
        if rng.random() < biased_swap_prob:
            out_pos = min(range(n_forced, 8),
                          key=lambda idx: ev_cache.get(team[idx]['name'], 0))
            new_rider = top_n_pool[rng.randrange(top_n_len)]
        else:
            out_pos = rng.randrange(n_forced, 8)
            new_rider = pool[rng.randrange(pool_len)]
        if new_rider['name'] == TARGET:
            counters['target_proposed_in'] += 1
        if team[out_pos]['name'] == TARGET:
            counters['target_proposed_out'] += 1
        if any(new_rider['name'] == r['name'] for r in team):
            counters['skips'] += 1; T *= cooling; i += 1; continue
        new_team = team[:]
        new_team[out_pos] = new_rider
        if not is_valid(new_team, budget):
            counters['skips'] += 1; T *= cooling; i += 1; continue
        new_score = compute_objective(new_team, probs, active, 'lookahead',
                                      cost_n1, cost_n2, team_n1, team_n2,
                                      current_team=current_team)
        delta = new_score - current_score
        accepted = delta > 0 or rng.random() < math.exp(delta / max(T, 0.01))
        is_target_in = (new_rider['name'] == TARGET)
        is_target_out = (team[out_pos]['name'] == TARGET)
        if accepted:
            counters['accepts'] += 1
            if is_target_in:  counters['target_swap_accepted'] += 1
            if is_target_out: counters['target_drop_accepted'] += 1
            team = new_team
            current_score = new_score
            if new_score > best_score: best_score = new_score; best_team = team[:]
        else:
            counters['rejects'] += 1
            if is_target_in:  counters['target_swap_rejected'] += 1
            if is_target_out: counters['target_drop_rejected'] += 1
        T *= cooling
        i += 1
        counters['iters'] = i
    return best_team, best_score, counters, target_visits_iter


def main():
    active, odds, intel, current_team = load()
    scoring = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    sliders = {
        'n1': {'bunch_sprint': 70, 'reduced_sprint': 20, 'breakaway': 5,  'gc': 5},
        'n2': {'bunch_sprint': 50, 'reduced_sprint': 30, 'breakaway': 10, 'gc': 10},
        'n3': {'bunch_sprint': 30, 'reduced_sprint': 30, 'breakaway': 10, 'gc': 30},
    }
    probs    = build_probabilities(active, odds, intel, sliders['n1'],
                                   stage_config=stage_config, scoring=scoring,
                                   use_race_type=False)
    probs_n1 = build_forward_probabilities(active, sliders['n2'])
    probs_n2 = build_forward_probabilities(active, sliders['n3'])

    base_seed = compute_seed(STAGE, sliders, [], [], False)
    proxy = current_team or fast_optimize(active, probs, active, [], [], 50_000_000,
                                          seed=base_seed ^ 0xF)
    cost_n1, cost_n2, _, _, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], active, active, probs_n1, probs_n2, [], [], 50_000_000,
        seed=base_seed,
    )
    print(f'Unconstrained: cost_n1={cost_n1:,.0f} cost_n2={cost_n2:,.0f}')
    print(f'\nInstrumenting chain 0 (seed=base ^ 0x400 ^ 0xC0) …')
    ch_seed = base_seed ^ (0x4 << 8) ^ 0xC0
    best_team, best_score, counters, visits = instrumented_sa(
        active, probs, [], [], 50_000_000, cost_n1, cost_n2, team_n1, team_n2,
        current_team, ch_seed,
    )
    print(f'\nFinal objective: {best_score:,.0f}')
    print(f'Final has Magnier? {any(r["name"] == TARGET for r in best_team)}')
    print(f'\nProposal/acceptance counts during {counters["iters"]:,} iters:')
    for k, v in counters.items():
        if k != 'iters':
            print(f'  {k:<28}{v:>8,}')
    print(f'\nIters where Magnier was in current team: {len(visits)} '
          f'({100*len(visits)/counters["iters"]:.1f}%)')
    if visits[:5]:
        print(f'  first few visit iters: {visits[:5]}')
        print(f'  last few visit iters:  {visits[-5:]}')


main()
