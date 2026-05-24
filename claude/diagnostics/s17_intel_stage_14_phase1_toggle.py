"""
Stage 14 Section D — Phase-1-vs-substrate attribution.

Phase 1 (hybrid simulate_stage) is on the worktree branch only — NOT in
parent repo's main. The operator's dashboard runs parent repo's optimizer
(pre-Phase-1 legacy single-pass PL).

This script imports the WORKTREE's Phase-1-active optimizer.py while reading
the PARENT repo's Stage 14 substrate. Loads each strategy's best_corr roster
from the Stage 14 basin enumeration JSON and computes simulate_stage post-SA
evaluation under hybrid_market_input=True (Phase 1) vs False (legacy).

This isolates the simulate_stage diff — the directly observable Phase 1
effect on dashboard Net EV display. SA basin selection requires a full SA
re-run with the Phase-1 simulate_stage in look_obj cross-chain selection;
deferred to operational validation when Phase 1 actually merges.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Use WORKTREE optimizer (Phase 1 active) reading PARENT substrate.
WORKTREE = Path(__file__).resolve().parents[1].parent
PARENT_REPO = Path('/Users/lassestoltenberg/Claude/Holdet-v3')

sys.path.insert(0, str(WORKTREE / 'claude' / 'engine'))

from optimizer import (  # noqa: E402
    build_probabilities,
    simulate_stage,
    select_captain,
    get_stage_config,
    load_stage_scoring,
)

# Verify Phase 1 is active in this import
import inspect  # noqa: E402
from optimizer import simulate_stage as _ss  # noqa: E402
sig = inspect.signature(_ss)
assert 'hybrid_market_input' in sig.parameters, 'Phase 1 hybrid path not active in this optimizer import!'
print(f'Phase 1 active in optimizer import (hybrid_market_input parameter present)')

SNAP = PARENT_REPO / 'shared' / 'data' / 'snapshots'
STAGE = 14

riders_file = PARENT_REPO / 'shared' / 'data' / 'riders' / 'giro_2026' / 'riders.json'
overrides_file = PARENT_REPO / 'shared' / 'data' / 'riders' / 'giro_2026' / 'terrain_affinity_overrides.json'

# Load riders (with overrides)
riders_data = json.loads(riders_file.read_text())
riders = riders_data['riders']
if overrides_file.exists():
    overrides = json.loads(overrides_file.read_text())
    if isinstance(overrides, dict):
        for r in riders:
            ov = overrides.get(r.get('name')) or overrides.get(r.get('canonical', ''))
            if ov and 'terrain_affinity' in ov:
                r['terrain_affinity'] = {**r.get('terrain_affinity', {}), **ov['terrain_affinity']}
active = [r for r in riders if not r.get('inactive')]
print(f'Active riders: {len(active)}')

# Load substrate
odds = json.loads((SNAP / f'stage_{STAGE}_odds.json').read_text()).get('odds', [])
intel = json.loads((SNAP / f'stage_{STAGE}_intel.json').read_text())
standings = json.loads((SNAP / f'stage_{STAGE - 1}_standings.json').read_text())
print(f'Odds rows: {len(odds)}; intel keys: {list(intel.keys())[:5]}')

probs = build_probabilities(
    active, odds, intel, sliders=None,
    stage_config=None, scoring=None,
    use_race_type=False, standings=standings,
)
print(f'probs entries: {len(probs)}')

# Load stage_config + scoring (mountain stage)
scoring = load_stage_scoring()
stage_cfg = get_stage_config(STAGE, scoring)
print(f"Stage 14 config: sprint_type={stage_cfg.get('sprint_type')}; climbs={len(stage_cfg.get('climbs', []))}")

# Load best_corr rosters from the basin enumeration
basins = json.loads(
    (WORKTREE / 'claude' / 'diagnostics' / 's17_intel_stage_14_output' / 's17_intel_stage_14_strategy_basins.json').read_text()
)

print('\n' + '=' * 80)
print('Phase-1 toggle: simulate_stage diff per strategy best_corr roster')
print('=' * 80)

name_to_rider = {r['name']: r for r in riders}
results = {}
for strat_name, strat in basins['chains_by_strategy'].items():
    bc = strat['best_corr']
    if not bc:
        continue
    team = [name_to_rider[n] for n in bc['team_names'] if n in name_to_rider]
    if len(team) < 8:
        print(f'\n[{strat_name}] roster only {len(team)} riders resolvable; skipping')
        continue
    captain = bc['captain']

    sim_legacy = simulate_stage(team, probs, captain, all_riders=active,
                                n_sims=10_000, stage_config=stage_cfg, scoring=scoring,
                                seed=2026, hybrid_market_input=False)
    sim_hybrid = simulate_stage(team, probs, captain, all_riders=active,
                                n_sims=10_000, stage_config=stage_cfg, scoring=scoring,
                                seed=2026, hybrid_market_input=True)
    delta = sim_hybrid['mean'] - sim_legacy['mean']
    pct = delta / max(abs(sim_legacy['mean']), 1) * 100
    print(f'\n[{strat_name}] roster_SHA={bc["roster_sha"]}  captain={captain}')
    print(f'  legacy stage_EV:  {sim_legacy["mean"]:>11,.0f}')
    print(f'  hybrid stage_EV:  {sim_hybrid["mean"]:>11,.0f}')
    print(f'  delta:            {delta:>+11,.0f}  ({pct:+.1f}%)')
    print(f'  diagnostic stage_EV (in basin JSON, parent repo legacy): {bc["stage_ev"]:>11,d}')
    # Per-component diff
    print(f'  {"component":<18} {"legacy":>11} {"hybrid":>11} {"delta":>11}')
    for k in ('stage_finish','sprint_points','jersey_bonus','gc_bonus',
              'kom_points','captain_bonus','team_bonus','depth_bonus'):
        l = sim_legacy['breakdown'].get(k, 0)
        h = sim_hybrid['breakdown'].get(k, 0)
        print(f'  {k:<18} {l:>11} {h:>11} {h-l:>+11}')
    results[strat_name] = {
        'roster': bc['team_names'], 'captain': captain,
        'legacy': {'mean': sim_legacy['mean'], 'breakdown': sim_legacy['breakdown']},
        'hybrid': {'mean': sim_hybrid['mean'], 'breakdown': sim_hybrid['breakdown']},
        'delta': delta, 'pct': pct,
    }

# Persist
out_path = WORKTREE / 'claude' / 'diagnostics' / 's17_intel_stage_14_output' / 's17_intel_stage_14_phase1_toggle.json'
out_path.write_text(json.dumps({
    'stage': STAGE,
    'substrate_shas': basins['substrate_shas'],
    'phase_1_optimizer': 'worktree (hybrid_market_input parameter present)',
    'substrate_source': 'parent repo /shared/data/snapshots',
    'results_per_strategy': results,
}, indent=2, default=int))
print(f'\nPersisted: {out_path.relative_to(WORKTREE)}')
