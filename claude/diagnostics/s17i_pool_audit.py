"""S17-ι Phase 0 — Proposal pool composition audit (read-only).

Replicates the biased-swap candidate pool construction from
optimizer.py:866-899 against the captured Stage 5 reproducer substrate.
Dumps the actual pool composition to JSON, then computes coverage against
the Tier 1–5 framework.

Inputs:
  shared/data/tmp/s17z_repro_state/  (preserved Stage 5 substrate)
  s17z_payload_unc.txt               (unconstrained payload)

Output:
  claude/diagnostics/s17i_pool_audit_results.json
"""
import json, os, re, sys
from collections import defaultdict

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    build_probabilities, build_forward_probabilities,
    load_stage_scoring, get_stage_config,
)

STAGE = 5
SUBSTRATE = os.path.join(REPO, 'shared', 'data', 'tmp', 's17z_repro_state')
RIDERS_FILE = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')
OUT_PATH = os.path.join(REPO, 'claude', 'diagnostics', 's17i_pool_audit_results.json')


def _parse_payload(path):
    """Extract --data-raw '{...}' from curl payload."""
    txt = open(path).read()
    m = re.search(r"--data-raw\s+'(\{.*\})'", txt, re.DOTALL)
    if not m:
        raise ValueError(f'no JSON body found in {path}')
    return json.loads(m.group(1))


def _load_substrate():
    payload = _parse_payload(os.path.join(SUBSTRATE, 's17z_payload_unc.txt'))
    odds = json.load(open(os.path.join(SUBSTRATE, f'stage_{STAGE}_odds.json')))
    if isinstance(odds, dict):
        odds = odds.get('odds', odds)
    intel_full = json.load(open(os.path.join(SUBSTRATE, f'stage_{STAGE}_intel.json')))
    standings = json.load(open(os.path.join(SUBSTRATE, f'stage_{STAGE-1}_standings.json')))
    results = json.load(open(os.path.join(SUBSTRATE, f'stage_{STAGE-1}_results.json')))
    riders_doc = json.load(open(RIDERS_FILE))
    active = [r for r in riders_doc['riders']
              if not r.get('isOut') and r.get('status') != 'dns']
    return payload, odds, intel_full, standings, results, active


def _construct_pool(payload, odds, intel_full, active):
    """Replicate optimizer.py:866-899 pool construction faithfully."""
    sliders = payload['sliders']
    force_in = payload.get('force_in', [])
    force_out = payload.get('force_out', [])
    use_race_type = payload.get('use_race_type_adjustment', False)

    scoring = load_stage_scoring()
    stage_config = get_stage_config(STAGE, scoring)
    probs = build_probabilities(active, odds, intel_full,
                                sliders.get('n1', {}),
                                stage_config=stage_config, scoring=scoring,
                                use_race_type=use_race_type)

    forced_set = set(force_in or [])
    excluded_set = set(force_out or [])
    forced = [r for r in active if r['name'] in forced_set]
    pool = [r for r in active
            if r['name'] not in excluded_set and r['name'] not in forced_set]
    ev_cache = {r['name']: probs.get(r['name'], {}).get('total_ev', 0.0) for r in pool}
    ev_cache.update({r['name']: probs.get(r['name'], {}).get('total_ev', 0.0) for r in forced})
    sorted_pool = sorted(pool, key=lambda r: ev_cache[r['name']], reverse=True)
    top_n_pool = sorted_pool[:min(50, len(sorted_pool))]
    # S17-ζ-fix (d): union with current_team members
    current_team = _current_team_objects(active)
    if current_team:
        top_n_names = {r['name'] for r in top_n_pool}
        for ct_r in current_team:
            n = ct_r.get('name')
            if (n and n not in top_n_names
                    and n not in excluded_set
                    and n not in forced_set):
                canonical = next((r for r in pool if r.get('name') == n), ct_r)
                top_n_pool.append(canonical)
                top_n_names.add(n)
    return top_n_pool, pool, ev_cache, probs


def _current_team_objects(active):
    res = json.load(open(os.path.join(SUBSTRATE, f'stage_{STAGE-1}_results.json')))
    names = [r['name'] for r in res.get('rider_results', []) if r.get('name')]
    by_name = {r['name']: r for r in active}
    return [by_name[n] for n in names if n in by_name]


def _tier1_external_signal(odds, intel_full):
    """Riders with non-zero win odds OR strong intel signal."""
    win_riders = {row.get('name') for row in odds
                  if (row.get('win_pct') or 0) > 0 and row.get('name')}
    intel_inner = intel_full.get('intel', intel_full) if isinstance(intel_full, dict) else {}
    sigs = intel_inner.get('key_signals', []) or []
    strong_riders = {s.get('rider') for s in sigs
                     if (s.get('strength') or '').lower() == 'strong' and s.get('rider')}
    return win_riders, strong_riders, win_riders | strong_riders


def _tier2_gc_top10(standings):
    """GC top-10 from previous-stage standings."""
    gc = standings.get('gc') or standings.get('samlet') or standings.get('classifications', {}).get('gc') or []
    # standings.json shape varies; try common patterns
    if isinstance(gc, list) and gc and isinstance(gc[0], dict):
        names = [(e.get('rider') or e.get('name') or e.get('rider_name')) for e in gc[:10]]
        return {n for n in names if n}
    return set()


def _tier3_current_with_affinity(current_team, sliders):
    """Current team riders whose terrain_affinity matches n2 or n3 slider distribution."""
    # Compute the dominant terrain dimension for n2/n3
    def dominant(slider):
        if not slider: return None
        return max(slider.items(), key=lambda kv: kv[1])[0] if slider else None
    n2_dom = dominant(sliders.get('n2'))
    n3_dom = dominant(sliders.get('n3'))
    # Map slider bucket to terrain_affinity dimensions (per SCENARIO_TO_TERRAIN)
    bucket_to_dim = {
        'bunch_sprint':   ['flat'],
        'reduced_sprint': ['hilly'],
        'breakaway':      ['mixed'],
        'gc':             ['climbing'],
    }
    target_dims = set()
    for b in (n2_dom, n3_dom):
        if b in bucket_to_dim:
            target_dims.update(bucket_to_dim[b])
    matched = []
    for r in current_team:
        ta = r.get('terrain_affinity', {})
        max_dim = max(ta.items(), key=lambda kv: kv[1])[0] if ta else None
        if max_dim in target_dims:
            matched.append(r['name'])
    return matched, {r['name'] for r in current_team}, target_dims


def _tier4_points_kom_top10(standings):
    """Points + KOM top-10. Key names per actual standings JSON:
    `points_classification` (sprint) and `kom_classification` (mountain).
    """
    out = set()
    for key in ('points_classification', 'kom_classification'):
        v = standings.get(key)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            for e in v[:10]:
                n = e.get('rider') or e.get('name') or e.get('rider_name')
                if n:
                    out.add(n)
    return out


def _tier5_team_fillers(active, tier1_names, budget_per_filler=3_500_000):
    """For each Tier 1 favorite, find teammates with affinity match or cheapest."""
    by_team = defaultdict(list)
    for r in active:
        t = r.get('team') or ''
        by_team[t].append(r)
    fillers = set()
    for fav in tier1_names:
        fav_obj = next((r for r in active if r['name'] == fav), None)
        if not fav_obj: continue
        teammates = [r for r in by_team[fav_obj.get('team') or ''] if r['name'] != fav]
        cheap = sorted(teammates, key=lambda r: r.get('price', 999_999_999))[:3]
        for c in cheap:
            fillers.add(c['name'])
    return fillers


def main():
    payload, odds, intel_full, standings, results, active = _load_substrate()
    print(f'Loaded substrate: active={len(active)}, odds={len(odds)}, '
          f'intel signals={len((intel_full.get("intel", intel_full) or {}).get("key_signals", []))}, '
          f'current_team_size={len(results.get("rider_results", []))}')
    current_team = _current_team_objects(active)
    top_n_pool, full_pool, ev_cache, probs = _construct_pool(payload, odds, intel_full, active)
    pool_names = {r['name'] for r in top_n_pool}

    print(f'\n=== Pool composition ===')
    print(f'  full_pool size:  {len(full_pool)} (= 174 active − force_out − force_in)')
    print(f'  top_n_pool size: {len(top_n_pool)} (biased-swap candidates)')
    print(f'  top_n_pool − sorted_pool[:50] (added via current_team union): '
          f'{len(top_n_pool) - 50}')

    # Tier 1
    win_riders, strong_riders, t1 = _tier1_external_signal(odds, intel_full)
    print(f'\n=== Tier 1 — current-stage favorites (external signal) ===')
    print(f'  Riders with non-zero win odds: {len(win_riders)}')
    print(f'  Riders with strong intel signal: {len(strong_riders)}')
    print(f'  Tier 1 union size: {len(t1)}')
    print(f'  In top_n_pool: {len(t1 & pool_names)}/{len(t1)}')
    missing_t1 = sorted(t1 - pool_names)
    if missing_t1:
        print(f'  Missing from pool: {missing_t1}')

    # Tier 2
    t2 = _tier2_gc_top10(standings)
    print(f'\n=== Tier 2 — GC top-10 ===')
    print(f'  standings.json keys: {sorted(standings.keys())[:10]}')
    print(f'  Tier 2 size: {len(t2)}')
    if t2:
        print(f'  Members: {sorted(t2)}')
        print(f'  In top_n_pool: {len(t2 & pool_names)}/{len(t2)}')
        missing = sorted(t2 - pool_names)
        if missing:
            print(f'  Missing from pool: {missing}')

    # Tier 3
    affinity_match, ct_set, target_dims = _tier3_current_with_affinity(current_team, payload.get('sliders', {}))
    print(f'\n=== Tier 3 — current team with n+1/n+2 affinity fit ===')
    print(f'  Forward slider target terrain dimensions: {target_dims}')
    print(f'  Current team: {sorted(ct_set)}')
    print(f'  Affinity-matched: {affinity_match}')
    t3 = ct_set
    print(f'  In top_n_pool: {len(t3 & pool_names)}/{len(t3)} (current team union from S17-ζ-fix (d))')

    # Tier 4
    t4 = _tier4_points_kom_top10(standings)
    print(f'\n=== Tier 4 — Points + KOM top-10 ===')
    print(f'  Tier 4 size: {len(t4)}')
    if t4:
        print(f'  In top_n_pool: {len(t4 & pool_names)}/{len(t4)}')
        missing = sorted(t4 - pool_names)
        if missing:
            print(f'  Missing from pool: {missing}')

    # Tier 5
    t5 = _tier5_team_fillers(active, t1)
    t5_in_pool = t5 & pool_names
    print(f'\n=== Tier 5 — team-bonus fillers (teammates of Tier 1 favorites) ===')
    print(f'  Tier 5 size: {len(t5)}')
    print(f'  In top_n_pool: {len(t5_in_pool)}/{len(t5)}')
    missing_t5 = sorted(t5 - pool_names)
    if missing_t5:
        print(f'  Missing from pool ({len(missing_t5)}): {missing_t5[:20]}...' if len(missing_t5) > 20 else f'  Missing: {missing_t5}')

    # Price distribution
    print(f'\n=== Price distribution (top_n_pool) ===')
    prices = sorted(r.get('price', 0) for r in top_n_pool)
    buckets = defaultdict(int)
    for p in prices:
        b = (p // 1_000_000)
        buckets[b] += 1
    for b in sorted(buckets):
        bar = '█' * buckets[b]
        print(f'  {b}–{b+1}M: {buckets[b]:>3}  {bar}')
    print(f'  min:    {min(prices):>10,}')
    print(f'  max:    {max(prices):>10,}')
    print(f'  avg:    {sum(prices)//len(prices):>10,}')
    print(f'  <3.5M:  {sum(1 for p in prices if p < 3_500_000)} riders')

    # Dump JSON for re-analysis
    out = {
        'stage': STAGE,
        'payload': payload,
        'pool': {
            'top_n_pool_size': len(top_n_pool),
            'full_pool_size': len(full_pool),
            'top_n_added_via_current_team_union': len(top_n_pool) - 50,
            'riders': [
                {
                    'name': r['name'],
                    'holdet_id': r.get('holdet_id'),
                    'price': r.get('price'),
                    'team': r.get('team'),
                    'current_stage_total_ev': ev_cache.get(r['name'], 0.0),
                    'terrain_affinity': r.get('terrain_affinity', {}),
                }
                for r in top_n_pool
            ],
        },
        'tiers': {
            'tier1_external_signal': {
                'win_odds': sorted(win_riders),
                'strong_intel': sorted(strong_riders),
                'union': sorted(t1),
                'in_pool': sorted(t1 & pool_names),
                'missing': sorted(t1 - pool_names),
            },
            'tier2_gc_top10': {
                'members': sorted(t2),
                'in_pool': sorted(t2 & pool_names),
                'missing': sorted(t2 - pool_names),
            },
            'tier3_current_team_affinity': {
                'current_team': sorted(ct_set),
                'affinity_matched': affinity_match,
                'target_dims': sorted(target_dims),
                'in_pool': sorted(ct_set & pool_names),
                'missing': sorted(ct_set - pool_names),
            },
            'tier4_points_kom_top10': {
                'members': sorted(t4),
                'in_pool': sorted(t4 & pool_names),
                'missing': sorted(t4 - pool_names),
            },
            'tier5_team_fillers': {
                'members': sorted(t5),
                'in_pool': sorted(t5 & pool_names),
                'missing': sorted(t5 - pool_names),
            },
        },
        'price_distribution': {
            'min': min(prices), 'max': max(prices),
            'avg': sum(prices) // len(prices),
            'under_3_5M': sum(1 for p in prices if p < 3_500_000),
            'buckets_M': {str(b): buckets[b] for b in sorted(buckets)},
        },
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f'\nDumped audit results to {OUT_PATH}')


if __name__ == '__main__':
    main()
