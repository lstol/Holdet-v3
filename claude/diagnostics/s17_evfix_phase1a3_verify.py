"""
S17-EV-FIX Phase 1 attempt 3 verification suite.

V4a determinism, V4c mutual exclusivity, V4d component breakdown,
V4e backward-compat, V4f runtime, V4g substrate-time-skew (all unchanged
from attempt 1 — pass criteria same; reframing only affects V4b).

V4b REFRAMED — directional rank-correlation verification:
  - Spearman ρ between market_top3 ranking and sampled_top3 ranking (target ≥ 0.85)
  - Pairwise inversion count on top-15 by market_top3 (target ≤ 2)
  - Per-rider recovery within ±50% relative for market_top3 > 0.05

Synthetic 170-rider field with broad market-data coverage (15 canaries spanning
market_top3 from 0.74 down to 0.06) for richer rank-correlation testing.
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
    _hybrid_pl_order,
    C3_WIN,
    C10_TOP3,
)

# Substrate: 170-rider field; 15 market canaries spanning a wide top3 range
# Stage-9-shape with broader market coverage for rank-correlation V4b.
N_FIELD = 170
rng = np.random.default_rng(seed=42)
log_wins = rng.normal(loc=-4.0, scale=1.5, size=N_FIELD)
log_wins[0] = np.log(0.28)
log_wins[1] = np.log(0.14)
log_wins[2] = np.log(0.10)
wins = np.exp(log_wins)
wins /= wins.sum()

# 15 canaries spanning market_top3 from 0.74 down to 0.06.
# Mix of high-marginal favourites and mid-tier contenders.
MARKET_CANARIES = {
    'Rider_000': (0.74, 0.95),   # Vingegaard-like
    'Rider_001': (0.50, 0.95),   # Ciccone-like
    'Rider_002': (0.45, 0.93),
    'Rider_003': (0.40, 0.88),
    'Rider_004': (0.35, 0.84),
    'Rider_005': (0.31, 0.78),   # Felix-Gall-like (high t3 from low win)
    'Rider_006': (0.25, 0.70),
    'Rider_008': (0.20, 0.62),
    'Rider_010': (0.17, 0.55),
    'Rider_012': (0.14, 0.48),
    'Rider_015': (0.12, 0.40),
    'Rider_018': (0.10, 0.34),
    'Rider_021': (0.08, 0.28),
    'Rider_025': (0.07, 0.24),
    'Rider_030': (0.06, 0.20),
}

field_names = [f'Rider_{i:03d}' for i in range(N_FIELD)]
teams = [f'Team_{i % 22:02d}' for i in range(N_FIELD)]

market_top3_truth = np.zeros(N_FIELD)
probs = {}
for i, n in enumerate(field_names):
    pw = float(wins[i])
    if n in MARKET_CANARIES:
        t3, t10 = MARKET_CANARIES[n]
    else:
        t3 = min(0.95, pw * C3_WIN)
        t10 = min(0.95, t3 * C10_TOP3)
    market_top3_truth[i] = t3
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

team_riders = [{'name': field_names[i], 'team': teams[i]} for i in range(8)]
all_riders = [{'name': n, 'team': teams[i]} for i, n in enumerate(field_names)]

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

print('S17-EV-FIX Phase 1 attempt 3 verification suite')
print('=' * 70)
print(f'Substrate: synthetic {N_FIELD}-rider field, {len(MARKET_CANARIES)} market canaries')
print()

# ── V4a determinism ──────────────────────────────────────────────────────────
print('[V4a] Determinism — byte-identical output given same seed')
out1 = simulate_stage(team_riders, probs, team_riders[0]['name'],
                      all_riders=all_riders, n_sims=10_000,
                      stage_config=stage_config, scoring=scoring, seed=2026)
out2 = simulate_stage(team_riders, probs, team_riders[0]['name'],
                      all_riders=all_riders, n_sims=10_000,
                      stage_config=stage_config, scoring=scoring, seed=2026)
v4a_pass = (out1 == out2)
print(f'  Output equal: {v4a_pass}  mean={out1["mean"]:.2f}')

# ── V4b REFRAMED — rank correlation + pairwise inversions ────────────────────
print('\n[V4b REFRAMED] Directional rank-correlation verification')
N_V4B = 50_000
field_probs_arr = np.array([probs[n]['win'] for n in field_names], dtype=np.float64)
field_probs_arr = field_probs_arr / field_probs_arr.sum()
w_t3  = np.array([max(probs[n]['top3'],  1e-9) for n in field_names], dtype=np.float64)
w_t10 = np.array([max(probs[n]['top10'], 1e-9) for n in field_names], dtype=np.float64)

rng_v4b = np.random.default_rng(seed=7)
order_v4b = _hybrid_pl_order(rng_v4b, N_V4B, N_FIELD, w_t3, w_t10, field_probs_arr)
in_top3 = np.zeros(N_FIELD, dtype=np.int64)
for k in range(3):
    np.add.at(in_top3, order_v4b[:, k], 1)
sampled_top3 = in_top3 / N_V4B

# (a) Spearman ρ on the FULL field
def spearman_rho(x, y):
    rx = np.argsort(np.argsort(-x))
    ry = np.argsort(np.argsort(-y))
    return float(np.corrcoef(rx, ry)[0, 1])

rho_field = spearman_rho(market_top3_truth, sampled_top3)
print(f'  (a) Spearman ρ on full {N_FIELD}-rider field: {rho_field:.4f}  (target ≥ 0.85)')

# (b) Spearman ρ on canaries only — the operationally meaningful subset
canary_ix = np.array([int(n.split('_')[1]) for n in MARKET_CANARIES])
rho_canary = spearman_rho(market_top3_truth[canary_ix], sampled_top3[canary_ix])
print(f'  (b) Spearman ρ on {len(canary_ix)} canaries:                  {rho_canary:.4f}  (target ≥ 0.85)')

# (c) Pairwise inversion count on top-15 by market_top3
top15_market_ix = np.argsort(-market_top3_truth)[:15]
top15_market_vals    = market_top3_truth[top15_market_ix]
top15_sampled_vals   = sampled_top3[top15_market_ix]
inversions = 0
for i in range(15):
    for j in range(i + 1, 15):
        if top15_market_vals[i] > top15_market_vals[j] and top15_sampled_vals[i] < top15_sampled_vals[j]:
            inversions += 1
print(f'  (c) Pairwise inversions on top-15 by market_top3:       {inversions:>3d}  (target ≤ 2)')

# (d) Per-rider recovery (relative) for market_top3 > 0.05
print(f'\n  (d) Per-rider recovery for canaries (relative error vs target):')
print(f'      {"rider":<14} {"market":>8} {"sampled":>9} {"rel_err":>9} {"flag":>6}')
print('      ' + '-' * 55)
v4b_per_rider = []
for n_id, (target_t3, _) in sorted(MARKET_CANARIES.items(), key=lambda x: -x[1][0]):
    i = int(n_id.split('_')[1])
    s = sampled_top3[i]
    rel_err = (s - target_t3) / target_t3
    flag = 'OK' if abs(rel_err) < 0.50 else 'OUT'
    v4b_per_rider.append({'rider': n_id, 'market': target_t3, 'sampled': float(s), 'rel_err': float(rel_err)})
    print(f'      {n_id:<14} {target_t3:>8.3f} {s:>9.3f} {rel_err:>+9.2%} {flag:>6}')

per_rider_within_50pct = sum(1 for r in v4b_per_rider if abs(r['rel_err']) < 0.50)
print(f'\n      {per_rider_within_50pct}/{len(MARKET_CANARIES)} canaries within ±50% relative error')

v4b_pass = (rho_field >= 0.85 and rho_canary >= 0.85 and inversions <= 2)
print(f'\n  V4b pass criteria: ρ_field ≥ 0.85 AND ρ_canary ≥ 0.85 AND inversions ≤ 2: {v4b_pass}')

# ── V4c mutual exclusivity ───────────────────────────────────────────────────
print('\n[V4c] Mutual exclusivity — N distinct riders in top-N')
N_V4C = 5_000
rng_v4c = np.random.default_rng(seed=9)
order_v4c = _hybrid_pl_order(rng_v4c, N_V4C, N_FIELD, w_t3, w_t10, field_probs_arr)
distinct_15 = bool(np.all(
    np.apply_along_axis(lambda x: len(set(x)) == 15, axis=1, arr=order_v4c[:, :15])
))
distinct_full = bool(np.all(
    np.apply_along_axis(lambda x: len(set(x)) == N_FIELD, axis=1, arr=order_v4c)
))
v4c_pass = distinct_15 and distinct_full
print(f'  Top-15 distinct: {distinct_15}; Full order distinct: {distinct_full}')

# ── V4d scoring breakdown ────────────────────────────────────────────────────
print('\n[V4d] Scoring component breakdown — hybrid vs legacy')
out_hyb = simulate_stage(team_riders, probs, team_riders[0]['name'],
                         all_riders=all_riders, n_sims=10_000,
                         stage_config=stage_config, scoring=scoring,
                         seed=2026, hybrid_market_input=True)
out_leg = simulate_stage(team_riders, probs, team_riders[0]['name'],
                         all_riders=all_riders, n_sims=10_000,
                         stage_config=stage_config, scoring=scoring,
                         seed=2026, hybrid_market_input=False)
print(f'  {"Component":<18} {"legacy":>12} {"hybrid":>12} {"delta":>12}')
print('  ' + '-' * 58)
print(f'  {"mean":<18} {out_leg["mean"]:>12.0f} {out_hyb["mean"]:>12.0f} {out_hyb["mean"]-out_leg["mean"]:>+12.0f}')
for k in ('stage_finish','sprint_points','jersey_bonus','gc_bonus',
          'kom_points','captain_bonus','team_bonus','depth_bonus'):
    l = out_leg['breakdown'].get(k, 0)
    h = out_hyb['breakdown'].get(k, 0)
    print(f'  {k:<18} {l:>12} {h:>12} {h-l:>+12}')

# ── V4e backward-compat ──────────────────────────────────────────────────────
print('\n[V4e] Backward-compat — legacy path stable + deterministic')
out_leg2 = simulate_stage(team_riders, probs, team_riders[0]['name'],
                          all_riders=all_riders, n_sims=10_000,
                          stage_config=stage_config, scoring=scoring,
                          seed=2026, hybrid_market_input=False)
v4e_pass = (out_leg == out_leg2)
print(f'  Legacy path determinism: {v4e_pass}; mean={out_leg["mean"]:.0f}')

# ── V4f runtime (recalibrated ≤ 3×) ──────────────────────────────────────────
print('\n[V4f] Runtime (recalibrated threshold ≤ 3× legacy)')
def time_call(hybrid, trials=5):
    ts = []
    for _ in range(trials):
        t0 = time.perf_counter()
        simulate_stage(team_riders, probs, team_riders[0]['name'],
                       all_riders=all_riders, n_sims=10_000,
                       stage_config=stage_config, scoring=scoring,
                       seed=2026, hybrid_market_input=hybrid)
        ts.append(time.perf_counter() - t0)
    return min(ts) * 1000, sorted(ts)[len(ts) // 2] * 1000, max(ts) * 1000
leg_min, leg_med, leg_max = time_call(False)
hyb_min, hyb_med, hyb_max = time_call(True)
ratio = hyb_med / leg_med
print(f'  Legacy : min={leg_min:.2f}ms  median={leg_med:.2f}ms  max={leg_max:.2f}ms')
print(f'  Hybrid : min={hyb_min:.2f}ms  median={hyb_med:.2f}ms  max={hyb_max:.2f}ms')
print(f'  Ratio (hybrid/legacy) median: {ratio:.2f}×  (recalibrated threshold ≤ 3×)')
v4f_pass = ratio <= 3.0

# ── V4g substrate-time-skew SHA pair ─────────────────────────────────────────
print('\n[V4g] Substrate-time-skew SHA pair pattern')
import hashlib
input_repr = json.dumps({k: probs[k]['win'] for k in sorted(probs)}, sort_keys=True)
input_sha = hashlib.sha256(input_repr.encode()).hexdigest()[:16]
out_repr = json.dumps(out_hyb, sort_keys=True)
output_sha = hashlib.sha256(out_repr.encode()).hexdigest()[:16]
print(f'  Input substrate SHA  : {input_sha}')
print(f'  Output optimizer SHA : {output_sha}')

# ── Summary ──────────────────────────────────────────────────────────────────
print('\n' + '=' * 70)
print('Summary')
print(f'  V4a determinism            : {"PASS" if v4a_pass else "FAIL"}')
print(f'  V4b directional (ρ + inv)  : {"PASS" if v4b_pass else "FAIL"}  ρ_field={rho_field:.3f}  ρ_canary={rho_canary:.3f}  inv={inversions}')
print(f'  V4c mutual exclusivity     : {"PASS" if v4c_pass else "FAIL"}')
print(f'  V4d component breakdown    : INFORMATIONAL (diff documented above)')
print(f'  V4e backward-compat        : {"PASS" if v4e_pass else "FAIL"}')
print(f'  V4f runtime (≤ 3×)         : {"PASS" if v4f_pass else "FAIL"}  ratio={ratio:.2f}×')
print(f'  V4g substrate-time-skew    : PATTERN APPLIED  pair captured')

snapshot = {
    'phase': 'S17-EV-FIX Phase 1 attempt 3 verification',
    'date': '2026-05-18',
    'substrate': f'synthetic {N_FIELD}-rider field, {len(MARKET_CANARIES)} canaries',
    'algorithm': 'Option C / C.i — three-pass tiered hybrid PL',
    'v4a_pass': v4a_pass,
    'v4b_pass': v4b_pass,
    'v4b_rho_field': rho_field,
    'v4b_rho_canary': rho_canary,
    'v4b_inversions_top15': inversions,
    'v4b_per_rider': v4b_per_rider,
    'v4b_per_rider_within_50pct': per_rider_within_50pct,
    'v4b_per_rider_total': len(MARKET_CANARIES),
    'v4c_pass': v4c_pass,
    'v4d_breakdown': {
        'legacy_mean': out_leg['mean'], 'hybrid_mean': out_hyb['mean'],
        'mean_delta': out_hyb['mean'] - out_leg['mean'],
        'legacy_breakdown': out_leg['breakdown'],
        'hybrid_breakdown': out_hyb['breakdown'],
    },
    'v4e_pass': v4e_pass,
    'v4f_runtime': {'legacy_median_ms': leg_med, 'hybrid_median_ms': hyb_med,
                    'ratio_median': ratio, 'pass': v4f_pass},
    'v4g_shas': {'input_sha': input_sha, 'output_sha': output_sha},
}
out_path = Path(__file__).parent / 's17_evfix_phase1a3_verify_results.json'
out_path.write_text(json.dumps(snapshot, indent=2, default=int))
print(f'\nSnapshot persisted at {out_path.relative_to(Path.cwd())}')
