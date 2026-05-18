"""
S17-EV-FIX Phase 1 pre-implementation audit.

Profiles simulate_stage per-call cost on a synthetic 170-rider field at
n_sims=10_000 and n_sims=500. Audit-projected ~1.7M ops/call (Section 12).

Read-only. No optimizer modifications. Output to stdout + JSON snapshot.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))

import numpy as np

from optimizer import (  # noqa: E402
    simulate_stage,
    C3_WIN,
    C10_TOP3,
)

# ── Build synthetic substrate ────────────────────────────────────────────────

N_FIELD = 170  # approximates Giro 2026 active roster size

# Heavy-tailed win distribution to mimic real bookmaker shape: ~3 strong
# favourites, ~10 mid-tier, rest in long tail.
rng = np.random.default_rng(seed=42)
log_wins = rng.normal(loc=-4.0, scale=1.5, size=N_FIELD)
log_wins[0] = np.log(0.28)   # Vingegaard-like
log_wins[1] = np.log(0.14)   # Ciccone-like
log_wins[2] = np.log(0.10)
wins = np.exp(log_wins)
wins /= wins.sum()

field_names = [f'Rider_{i:03d}' for i in range(N_FIELD)]
teams = [f'Team_{i % 22:02d}' for i in range(N_FIELD)]  # 22 teams, 7-8 riders each

probs = {}
for i, n in enumerate(field_names):
    pw = float(wins[i])
    # Stage 9 shape: top3/top10 dense, often clamped near 0.95
    if i < 5:
        t3 = min(0.95, pw * 2.5 + 0.1)
        t10 = 0.95
    elif i < 20:
        t3 = min(0.95, pw * C3_WIN)
        t10 = min(0.95, t3 * C10_TOP3)
    else:
        t3 = min(0.95, pw * C3_WIN)
        t10 = min(0.95, t3 * C10_TOP3)
    fp = [0.0] * 15
    fp[0] = pw
    d23 = max(0.0, t3 - pw) / 2
    d410 = max(0.0, t10 - t3) / 7
    t15 = min(0.95, t10 + t10 * 0.15)
    d1115 = max(0.0, t15 - t10) / 5
    for j in range(1, 3): fp[j] = d23
    for j in range(3, 10): fp[j] = d410
    for j in range(10, 15): fp[j] = d1115
    probs[n] = {
        'win': pw, 'top3': t3, 'top10': t10, 'top15': t15,
        'finish_probs': fp, 'p2': fp[1], 'p3': fp[2], 'p_top15': t15,
        'finish_ev': 0.0, 'sprint_ev': 0.0, 'jersey_ev': 0.0,
        'gc_ev': 0.0, 'kom_ev': 0.0, 'total_ev': 0.0, 'team_bonus_ev': 0.0,
        'team': teams[i], 'name': n,
    }

# Roster: top-8 by win
team_riders = [{'name': field_names[i], 'team': teams[i]} for i in range(8)]
all_riders = [{'name': n, 'team': teams[i]} for i, n in enumerate(field_names)]

# Stage config: hilly stage shape (sprint=A, no climbs)
stage_config = {
    'sprint_type': 'A',
    'sprint_points': [50, 35, 25, 20, 18, 15, 12, 10, 8, 7, 6, 5, 4, 3, 2],
    'n_intermediate_sprints': 1,
    'climbs': [],
}
scoring = {
    'point_value_kr': 3_000,
    'intermediate_sprint_points': [15, 12, 10, 8, 6, 5, 4, 3, 2, 1],
}

# ── Profile ──────────────────────────────────────────────────────────────────

def time_simulate(n_sims, n_trials=5, seed=2026):
    times = []
    for trial in range(n_trials):
        t0 = time.perf_counter()
        out = simulate_stage(
            team_riders, probs, captain_name=team_riders[0]['name'],
            all_riders=all_riders, n_sims=n_sims,
            stage_config=stage_config, scoring=scoring, seed=seed,
        )
        times.append(time.perf_counter() - t0)
    return {
        'n_sims': n_sims,
        'min_ms': min(times) * 1000,
        'median_ms': sorted(times)[len(times) // 2] * 1000,
        'mean_ms': sum(times) / len(times) * 1000,
        'max_ms': max(times) * 1000,
        'n_trials': n_trials,
        'mean_output': out['mean'],
    }

print('S17-EV-FIX Phase 1 pre-implementation audit')
print('=' * 70)
print(f'Synthetic field size: {N_FIELD} riders')
print(f'Roster size: 8 (top by win)')
print()

results = []
for n_sims in (500, 1_000, 5_000, 10_000):
    r = time_simulate(n_sims)
    results.append(r)
    print(f'n_sims={n_sims:>6}  min={r["min_ms"]:>8.2f}ms  median={r["median_ms"]:>8.2f}ms  '
          f'mean={r["mean_ms"]:>8.2f}ms  output_mean={r["mean_output"]:.0f}')

print()

# Audit projection check: 1.7M ops/call ≈ n_sims × n_field × constant_factor.
# A vectorized numpy operation of shape (n_sims, n_field) costs ~O(n_sims × n_field) for
# the dominant -log/division/argsort terms. argsort dominates at O(n_field × log(n_field)) per row.
n_sims_10k = 10_000
ops_estimate_per_call = n_sims_10k * N_FIELD * np.log2(N_FIELD)
print(f'Estimated dominant ops per call (n_sims=10k × n_field × log(n_field)): {ops_estimate_per_call:.2e}')
print(f'Audit projection: ~1.7M ops/call')
print()

# What's needed for Phase 3 cached-sampling: SA chain = 200_000 iterations.
# If each SA iteration costs the simulate_stage equivalent of mass-evaluating
# n_team_candidates against the SAME sample matrix, the per-iteration cost is much
# cheaper than a fresh simulate_stage call. The cached sample matrix is built ONCE
# per SA chain, then per-iteration just indexes team_pos and sums points.
median_per_call = results[-1]['median_ms']
print(f'If cached-sampling Phase 3 reuses sample matrix across 200k SA iterations:')
print(f'  Naive cost (one full simulate_stage per iter): {median_per_call * 200_000 / 1000 / 60:.1f} min per chain × 10 chains × 3 strategies')
print(f'  Cached-sampling cost (build matrix once + 200k indexing): see Phase 3 design')
print()

# Cost of n_sims=500 vs n_sims=10000 — if Phase 3 finds n_sims=500 sufficient for SA convergence,
# the per-call cost drops 20× to ~{n_sims_500 / 1000 / 60 * 200_000:.1f} min full re-sample per chain
if any(r['n_sims'] == 500 for r in results):
    r500 = next(r for r in results if r['n_sims'] == 500)
    fresh_per_chain_min = r500['median_ms'] * 200_000 / 1000 / 60
    print(f'If Phase 3 instead re-samples at n_sims=500 per SA iter (no caching):')
    print(f'  Cost per chain: {fresh_per_chain_min:.1f} min × 10 chains × 3 strategies = {fresh_per_chain_min * 30:.0f} min total')

# Snapshot
snapshot = {
    'audit_date': '2026-05-18',
    'phase': 'S17-EV-FIX Phase 1 pre-implementation',
    'substrate': 'synthetic 170-rider field (Stage 9 shape)',
    'profile_results': results,
    'audit_projection_ops_per_call': 1_700_000,
    'estimated_ops_per_call_log2': ops_estimate_per_call,
}
out_path = Path(__file__).parent / 's17_evfix_phase1_audit_profile.json'
out_path.write_text(json.dumps(snapshot, indent=2))
print()
print(f'Snapshot persisted at {out_path.relative_to(Path.cwd())}')
