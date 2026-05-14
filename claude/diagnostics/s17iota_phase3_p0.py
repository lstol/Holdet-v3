"""S17-ι Phase 3 Phase 0 diagnostic — Eulalio surfacing classification.

Origin: Stage 6 prep 2026-05-14. Three strategy cards failed to surface
Afonso Eulálio (current Giro GC leader, 4.5M, ~140k expected jersey/GC
value on sprint stages). S17-ι Phase 1 shipped tier-union pool composition
including Tier 2 = GC top-10. This diagnostic classifies the failure as:

  (a) In pool but SA undersamples (Phase 3 weighting fix sufficient)
  (b) In pool, proposed, but _ev_single returns ~30-50k not ~140k
      (Phase 3 + Sub-B1 + Sub-B2 elevation needed)
  (c) Not in Tier 2 pool at all (Phase 1 regression diagnostic before
      Phase 3 work)

Read-only. Does not alter optimizer.py or any runtime code. Uses Stage 6
substrate from the canonical worktree (feature worktree has stub
snapshots per the worktree-substrate-gap operational note).
"""
import json
import os
import sys

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3/.claude/worktrees/epic-hofstadter-ab23f7'
CANON = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    build_tier_union_pool, build_probabilities, _ev_single,
    load_stage_scoring, get_stage_config,
    _tier1_external_signal, _tier2_gc_top10, _tier3_current_team_affinity,
    _tier4_points_kom_top10, _tier5_team_bonus_fillers,
)

STAGE = 6
TARGET = 'Afonso Eulálio'  # canonical spelling per riders.json (note accent)

# Stage 6 sliders: bunch-sprint stage in Naples
# Using the dashboard's typical sprint-stage config for current; n2/n3 reasonable forward proxies
SLIDERS = {
    'n1': {'bunch_sprint': 80, 'reduced_sprint': 20, 'gc': 0,  'breakaway': 0},
    'n2': {'bunch_sprint': 0,  'reduced_sprint': 20, 'gc': 80, 'breakaway': 0},   # Stage 7 mountain
    'n3': {'bunch_sprint': 0,  'reduced_sprint': 0,  'gc': 0,  'breakaway': 100}, # Stage 8 ITT
}


def load_substrate():
    """Load Stage 6 substrate. riders.json + stage_6_odds + stage_6_intel from
    the feature worktree's tracked tree; stage_5_standings from canonical
    (where post-Stage-5 race results live)."""
    riders = json.load(open(os.path.join(CANON, 'shared/data/riders/giro_2026/riders.json')))['riders']
    active = [r for r in riders if not r.get('isOut') and r.get('status') != 'dns']
    odds = json.load(open(os.path.join(CANON, 'shared/data/snapshots/stage_6_odds.json')))
    if isinstance(odds, dict):
        odds = odds.get('odds', odds)
    intel = json.load(open(os.path.join(CANON, 'shared/data/snapshots/stage_6_intel.json')))
    standings = json.load(open(os.path.join(CANON, 'shared/data/snapshots/stage_5_standings.json')))
    res_path = os.path.join(CANON, 'shared/data/snapshots/stage_5_results.json')
    if os.path.exists(res_path):
        res = json.load(open(res_path))
        by_name = {r['name']: r for r in active}
        current_team = [by_name[r['name']] for r in res.get('rider_results', []) if r.get('name') in by_name]
    else:
        current_team = []
    return active, odds, intel, standings, current_team


def step1_substrate():
    print('=' * 72)
    print('STEP 1 — Substrate availability + raw Eulálio location')
    print('=' * 72)
    active, odds, intel, standings, current_team = load_substrate()
    print(f'  active riders: {len(active)}')
    print(f'  odds entries:  {len(odds) if isinstance(odds, list) else "(dict)"}')
    print(f'  intel keys:    {list(intel.keys()) if isinstance(intel, dict) else type(intel).__name__}')
    print(f'  standings keys:{list(standings.keys())[:6]} ...')
    print(f'  current_team:  {len(current_team)} riders')

    # Eulalio in riders.json?
    eu = next((r for r in active if r['name'] == TARGET), None)
    print(f'\n  Eulálio in active riders: {eu is not None}')
    if eu:
        print(f'    name={eu["name"]!r}  holdet_id={eu.get("holdet_id")}  price={eu.get("price",0):,}  team={eu.get("team")}')
        print(f'    terrain_affinity={eu.get("terrain_affinity")}')

    # Eulalio in GC top-10?
    gc = standings.get('gc') or standings.get('classifications', {}).get('gc') or []
    in_gc_10 = [e for e in gc[:10] if e.get('name') == TARGET or e.get('rider') == TARGET
                                       or (e.get('name', '').lower() == TARGET.lower())]
    print(f'\n  Eulálio in standings GC top-10: {bool(in_gc_10)}')
    if in_gc_10:
        for e in in_gc_10:
            print(f'    rank={e.get("rank")}  name={e.get("name")!r}  name_raw={e.get("name_raw")!r}  rider_id={e.get("rider_id")}')
    return active, odds, intel, standings, current_team, eu


def step2_pool(active, odds, intel, standings, current_team):
    print()
    print('=' * 72)
    print('STEP 2 — build_tier_union_pool + per-tier attribution')
    print('=' * 72)
    # Per-tier set construction (matching build_tier_union_pool internals)
    t1 = _tier1_external_signal(odds, intel, active)
    t2 = _tier2_gc_top10(standings, active)
    t3 = _tier3_current_team_affinity(current_team, SLIDERS)
    t4 = _tier4_points_kom_top10(standings, active)
    t5 = _tier5_team_bonus_fillers(t1, active)
    print(f'\n  |Tier 1 external_signal| = {len(t1)}')
    print(f'  |Tier 2 gc_top10|        = {len(t2)}')
    print(f'  |Tier 3 ct_affinity|     = {len(t3)}')
    print(f'  |Tier 4 points+kom|      = {len(t4)}')
    print(f'  |Tier 5 team_bonus|      = {len(t5)}')
    union_names = t1 | t2 | t3 | t4 | t5 | {r['name'] for r in current_team}
    print(f'  |union ∪ current_team|   = {len(union_names)}')

    # Full pool via the actual helper
    pool = build_tier_union_pool(active, odds, intel, standings, current_team,
                                  SLIDERS, [], [])
    print(f'\n  build_tier_union_pool returned: {len(pool) if pool else None} riders')

    # Check Eulalio in every tier
    print(f'\n  Eulálio per-tier presence:')
    for label, s in [('T1 external_signal', t1), ('T2 gc_top10', t2),
                     ('T3 ct_affinity', t3), ('T4 points+kom', t4),
                     ('T5 team_bonus', t5)]:
        present = TARGET in s
        print(f'    {label:24} {"✓" if present else "·"} ({len(s)} total)')
    in_pool = pool and any(r['name'] == TARGET for r in pool)
    print(f'    in build_tier_union_pool {"✓" if in_pool else "✗"}')
    in_current = any(r['name'] == TARGET for r in current_team)
    print(f'    in current_team           {"✓" if in_current else "·"}')

    # Show Tier 2 contents
    print(f'\n  Tier 2 (GC top-10) members: {sorted(t2)}')

    return pool, in_pool, t1, t2, t3, t4, t5


def step3_ev(active, odds, intel, in_pool):
    print()
    print('=' * 72)
    print('STEP 3 — Probability + _ev_single decomposition (Eulálio vs refs)')
    print('=' * 72)
    if not in_pool:
        print('  Eulálio not in pool — Step 3 still informative (does build_probabilities')
        print('  produce a meaningful EV for him anyway?)')
    scoring = load_stage_scoring()
    sc = get_stage_config(STAGE, scoring)
    # Match dashboard cards: race-type adjustment ON for sprint stage
    probs_rt = build_probabilities(active, odds, intel, SLIDERS['n1'],
                                    stage_config=sc, scoring=scoring,
                                    use_race_type=True)
    probs_no = build_probabilities(active, odds, intel, SLIDERS['n1'],
                                    stage_config=sc, scoring=scoring,
                                    use_race_type=False)
    refs = ['Afonso Eulálio', 'Jonathan Milan', 'Paul Magnier']
    for label, probs in [('use_race_type=False (bookmaker + intel only)', probs_no),
                         ('use_race_type=True  (dashboard cards)',         probs_rt)]:
        print(f'\n  --- {label} ---')
        print(f'  {"rider":<22} {"win%":>6} {"top3%":>7} {"top10%":>7} {"top15%":>7}'
              f' {"finish":>10} {"sprint":>10} {"jersey":>10} {"gc":>10} {"total":>10}')
        for r in refs:
            p = probs.get(r, {})
            print(f'  {r:<22} {p.get("win",0)*100:>6.2f} {p.get("top3",0)*100:>7.2f}'
                  f' {p.get("top10",0)*100:>7.2f} {p.get("top15",0)*100:>7.2f}'
                  f' {p.get("finish_ev",0):>10,.0f} {p.get("sprint_ev",0):>10,.0f}'
                  f' {p.get("jersey_ev",0):>10,.0f} {p.get("gc_ev",0):>10,.0f}'
                  f' {p.get("total_ev",0):>10,.0f}')
            ev = _ev_single(r, probs)
            assert abs(ev - p.get('total_ev', 0)) < 1, f'_ev_single mismatch for {r}'
    return probs_no, probs_rt


def classify(in_pool, probs_no, probs_rt):
    print()
    print('=' * 72)
    print('CLASSIFICATION')
    print('=' * 72)
    p_no = probs_no.get(TARGET, {})
    p_rt = probs_rt.get(TARGET, {})
    ev_no = p_no.get('total_ev', 0)
    ev_rt = p_rt.get('total_ev', 0)
    user_expected = 140_000  # user's stated expected EV (~140k jersey/GC retention)
    print(f'\n  Eulálio _ev_single under race_type=False: {ev_no:>10,.0f}')
    print(f'  Eulálio _ev_single under race_type=True : {ev_rt:>10,.0f}')
    print(f'  User expected (sprint stage GC retention): ~{user_expected:,}')

    if not in_pool:
        verdict = '(c) NOT IN POOL'
    else:
        # Use dashboard-card config (race-type True) as the canonical comparison
        ev = ev_rt
        if ev >= 100_000:
            verdict = '(a) IN POOL with high EV — SA undersampling'
        elif ev <= 50_000:
            verdict = '(b) IN POOL but EV undercalibrated'
        else:
            verdict = '(d/ambiguous) IN POOL, EV between 50k-100k — decompose required'
    print(f'\n  CLASSIFICATION: {verdict}')
    return verdict


if __name__ == '__main__':
    active, odds, intel, standings, current_team, eu = step1_substrate()
    pool, in_pool, *_ = step2_pool(active, odds, intel, standings, current_team)
    probs_no, probs_rt = step3_ev(active, odds, intel, in_pool)
    verdict = classify(in_pool, probs_no, probs_rt)
    print(f'\nFINAL: {verdict}')
