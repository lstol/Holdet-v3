"""
S17-EV-FIX Phase 1 attempt 3 V4i — operational impact on Stage 2 substrate.

Stage 9 substrate is not in the worktree; Stage 2 is the most complete
substrate available (odds + intel + standings + holdet). Anchors Phase 1's
operational impact on a REAL substrate slice.

Captures the simulate_stage post-SA evaluation diff (hybrid_market_input=True
vs False) on a real team against Stage 2 substrate. This is the directly
testable Phase 1 surface — SA objective is unchanged (Phase 3 work) so SA
roster and captain selection are bit-identical pre/post Phase 1; only the
post-SA simulate_stage Net EV shifts.

Outputs: pre/post Net EV per simulate_stage call, breakdown diff, runtime,
substrate SHAs.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))

import numpy as np  # noqa: F401

from optimizer import build_probabilities, simulate_stage, select_captain  # noqa: E402

DATA = Path('shared/data/snapshots')
STAGE = 2

# Load substrate
with open(DATA / f'stage_{STAGE}_holdet.json') as f:
    holdet = json.load(f)
with open(DATA / f'stage_{STAGE}_odds.json') as f:
    odds_doc = json.load(f)
with open(DATA / f'stage_{STAGE}_intel.json') as f:
    intel = json.load(f)
with open(DATA / f'stage_{STAGE}_standings.json') as f:
    standings = json.load(f)

odds = odds_doc.get('odds', [])

# Active roster — the input shape build_probabilities expects.
all_riders = holdet.get('riders', [])
active = [r for r in all_riders if not r.get('inactive')]
print(f'Stage {STAGE} substrate:')
print(f'  all_riders={len(all_riders)}; active={len(active)}; odds rows={len(odds)}')

# Substrate SHAs (V4g pattern)
def sha16(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]
print(f'  SHAs: holdet={sha16(holdet)}  odds={sha16(odds_doc)}  intel={sha16(intel)}  standings={sha16(standings)}')

# Build probabilities
probs = build_probabilities(
    active, odds, intel, sliders=None,
    stage_config=None, scoring=None,
    use_race_type=False, standings=standings,
)

# Construct a "current team" approximation — first 8 from holdet user team list
# (operational test doesn't need the exact lookahead roster; just a realistic 8)
user_team_names = []
for key in ('current_team', 'team', 'user_team', 'roster'):
    if isinstance(holdet.get(key), list) and holdet[key]:
        user_team_names = [r.get('name') if isinstance(r, dict) else r for r in holdet[key][:8]]
        break

if not user_team_names:
    # Fallback: pick top 8 by build_probabilities total_ev as a representative roster
    sorted_by_ev = sorted(probs.items(), key=lambda kv: -kv[1].get('total_ev', 0))
    user_team_names = [n for n, _ in sorted_by_ev[:8]]
    print(f'  No current_team in holdet snapshot; using top-8 by total_ev as proxy roster')

# Resolve to full rider dicts
name_to_rider = {r['name']: r for r in all_riders}
team_riders = [name_to_rider[n] for n in user_team_names if n in name_to_rider]
if len(team_riders) < 8:
    sorted_by_ev = sorted(probs.items(), key=lambda kv: -kv[1].get('total_ev', 0))
    for n, _ in sorted_by_ev:
        if n in name_to_rider and name_to_rider[n] not in team_riders:
            team_riders.append(name_to_rider[n])
            if len(team_riders) == 8:
                break

print(f'  Team (8 riders): {[r["name"] for r in team_riders]}')

# Resolve captain via select_captain (unchanged by Phase 1)
captain = select_captain(team_riders, probs)['name']
print(f'  Captain (Phase-1-invariant): {captain}')

# ── Phase 1 impact: simulate_stage pre/post hybrid ───────────────────────────
print('\nSimulate_stage post-SA evaluation diff (legacy vs hybrid)')

t0 = time.perf_counter()
out_legacy = simulate_stage(team_riders, probs, captain, all_riders=active,
                            n_sims=10_000, stage_config=None, scoring=None,
                            seed=2026, hybrid_market_input=False)
legacy_ms = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
out_hybrid = simulate_stage(team_riders, probs, captain, all_riders=active,
                            n_sims=10_000, stage_config=None, scoring=None,
                            seed=2026, hybrid_market_input=True)
hybrid_ms = (time.perf_counter() - t0) * 1000

print(f'\n  Runtime: legacy={legacy_ms:.1f}ms, hybrid={hybrid_ms:.1f}ms, ratio={hybrid_ms/legacy_ms:.2f}×')

print(f'\n  {"Component":<18} {"legacy":>12} {"hybrid":>12} {"delta":>12} {"rel":>8}')
print('  ' + '-' * 68)
rel = lambda l, h: f'{(h-l)/max(abs(l), 1)*100:+.1f}%' if l else '   n/a'
print(f'  {"mean":<18} {out_legacy["mean"]:>12.0f} {out_hybrid["mean"]:>12.0f} {out_hybrid["mean"]-out_legacy["mean"]:>+12.0f} {rel(out_legacy["mean"], out_hybrid["mean"]):>8}')
for k in ('stage_finish','sprint_points','jersey_bonus','gc_bonus',
          'kom_points','captain_bonus','team_bonus','depth_bonus'):
    l = out_legacy['breakdown'].get(k, 0)
    h = out_hybrid['breakdown'].get(k, 0)
    print(f'  {k:<18} {l:>12} {h:>12} {h-l:>+12} {rel(l, h):>8}')
print(f'\n  CDF:')
for p in ('p25','p50','p75','p90'):
    l = out_legacy['cdf'][p]; h = out_hybrid['cdf'][p]
    print(f'    {p:<6} {l:>12} {h:>12} {h-l:>+12}')

# Operational read
print('\n' + '=' * 70)
print('Operational read:')
delta_pct = (out_hybrid["mean"] - out_legacy["mean"]) / max(abs(out_legacy["mean"]), 1) * 100
print(f'  Net EV shift: {out_legacy["mean"]:.0f} → {out_hybrid["mean"]:.0f}  ({delta_pct:+.1f}%)')
print(f'  Captain unchanged by Phase 1 (select_captain operates on total_ev, not simulate_stage)')
print(f'  Roster unchanged by Phase 1 (SA objective is Phase 3 work; SA still uses compute_team_ev)')
print(f'  Lookahead cross-chain look_obj DOES consume simulate_stage mean ─ full SA run needed')
print(f'  to characterize whether basin selection shifts; deferred to operational Stage-10+')
print(f'  empirical validation as documented in Phase 1 close.')

snapshot = {
    'phase': 'S17-EV-FIX Phase 1 attempt 3 V4i',
    'date': '2026-05-18',
    'stage': STAGE,
    'note': 'Stage 9 substrate not in worktree; Stage 2 substrate used as best-available real substrate slice',
    'substrate_shas': {
        'holdet': sha16(holdet), 'odds': sha16(odds_doc),
        'intel': sha16(intel), 'standings': sha16(standings),
    },
    'team': [r['name'] for r in team_riders],
    'captain': captain,
    'legacy': {'mean': out_legacy['mean'], 'breakdown': out_legacy['breakdown'], 'cdf': out_legacy['cdf']},
    'hybrid': {'mean': out_hybrid['mean'], 'breakdown': out_hybrid['breakdown'], 'cdf': out_hybrid['cdf']},
    'runtime_ms': {'legacy': legacy_ms, 'hybrid': hybrid_ms, 'ratio': hybrid_ms / legacy_ms},
}
out_path = Path(__file__).parent / 's17_evfix_phase1a3_v4i_stage2_results.json'
out_path.write_text(json.dumps(snapshot, indent=2, default=int))
print(f'\nSnapshot persisted at {out_path.relative_to(Path.cwd())}')
