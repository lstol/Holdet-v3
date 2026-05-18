"""
S17-EV-FIX Phase 1 attempt 2 pre-implementation audit.

Characterizes importance-sampling weight magnitudes for the Option A reweighting
approach. Synthesizes a Stage-9-shape substrate, runs single-pass PL to compute
PL-induced top3/top10 marginals, then computes the per-rider importance ratio
(market / PL) for each tier. Surfaces the per-sample weight magnitude
distribution under the tier-factorized formula:

  w_s = product over riders of (market_tier_i / PL_tier_i) for rider i's tier

Output: weight magnitude stats, ESS projection, PL-marginal MC cost.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))

import numpy as np

from optimizer import C3_WIN, C10_TOP3

# Substrate: 170-rider field, Stage 9 shape (4 strong market canaries).
N_FIELD = 170
rng = np.random.default_rng(seed=42)
log_wins = rng.normal(loc=-4.0, scale=1.5, size=N_FIELD)
log_wins[0] = np.log(0.28)
log_wins[1] = np.log(0.14)
log_wins[2] = np.log(0.10)
wins = np.exp(log_wins)
wins /= wins.sum()

MARKET = {
    'Rider_000': (0.74, 0.95),
    'Rider_001': (0.50, 0.95),
    'Rider_005': (0.31, 0.95),
    'Rider_010': (0.20, 0.70),
}

market_top3  = np.zeros(N_FIELD)
market_top10 = np.zeros(N_FIELD)
for i in range(N_FIELD):
    n = f'Rider_{i:03d}'
    pw = wins[i]
    if n in MARKET:
        t3, t10 = MARKET[n]
    else:
        t3 = min(0.95, pw * C3_WIN)
        t10 = min(0.95, t3 * C10_TOP3)
    market_top3[i]  = t3
    market_top10[i] = t10

# Compute PL-induced top3/top10 marginals via MC.
t0 = time.perf_counter()
N_CAL = 10_000
rng_pl = np.random.default_rng(seed=2026)
u  = rng_pl.uniform(1e-12, 1.0, (N_CAL, N_FIELD))
sc = -np.log(u) / wins
od = np.argsort(sc, axis=1)
in_t3  = np.zeros(N_FIELD, dtype=np.int64)
in_t10 = np.zeros(N_FIELD, dtype=np.int64)
for k in range(3):  np.add.at(in_t3,  od[:, k], 1)
for k in range(10): np.add.at(in_t10, od[:, k], 1)
pl_top3  = in_t3  / N_CAL
pl_top10 = in_t10 / N_CAL
cal_cost_ms = (time.perf_counter() - t0) * 1000

print('S17-EV-FIX Phase 1 attempt 2 pre-implementation audit')
print('=' * 70)
print(f'Field: {N_FIELD} riders; market canaries: {len(MARKET)}')
print()
print(f'[A] PL-marginal calibration cost: {cal_cost_ms:.2f}ms @ n_calibration={N_CAL}')

# Per-rider weight ratios per tier
ratio_t3      = market_top3  / np.maximum(pl_top3,  1e-9)
ratio_t10not3 = (market_top10 - market_top3) / np.maximum(pl_top10 - pl_top3, 1e-9)
ratio_11plus  = (1.0 - market_top10) / np.maximum(1.0 - pl_top10, 1e-9)

print(f'\n[B] Per-rider weight ratios for canary riders (market_tier / PL_tier)')
print(f'  {"rider":<14} {"pl_t3":>7} {"pl_t10":>8} {"r_t3":>7} {"r_t10not3":>11} {"r_11+":>7}')
print('  ' + '-' * 60)
for n_id in MARKET:
    i = int(n_id.split('_')[1])
    print(f'  {n_id:<14} {pl_top3[i]:>7.4f} {pl_top10[i]:>8.4f} {ratio_t3[i]:>7.2f} {ratio_t10not3[i]:>11.2f} {ratio_11plus[i]:>7.3f}')

print(f'\n  Max ratio in top-3 tier:    {ratio_t3.max():.2f}  ({"Rider_" + str(np.argmax(ratio_t3)).zfill(3)})')
print(f'  Max ratio in top-10 tier:   {ratio_t10not3.max():.2f}  ({"Rider_" + str(np.argmax(ratio_t10not3)).zfill(3)})')
print(f'  Max ratio in 11+ tier:      {ratio_11plus.max():.3f}')
print(f'  Min ratio in 11+ tier:      {ratio_11plus.min():.3f}  (suppression when market_top10 > PL_top10)')

# Project per-sample weight magnitude: 3 riders × top3-ratio + 7 × top10-ratio + 160 × 11+-ratio.
# Most riders contribute ratio ≈ 1.0 (derived-not-market); only canary riders have large ratios.
# Log-space accumulation:
log_ratio_t3      = np.log(np.maximum(ratio_t3,      1e-12))
log_ratio_t10not3 = np.log(np.maximum(ratio_t10not3, 1e-12))
log_ratio_11plus  = np.log(np.maximum(ratio_11plus,  1e-12))

# Run a small MC to project weight distribution
N_PROJ = 5_000
rng_pj = np.random.default_rng(seed=99)
u_pj = rng_pj.uniform(1e-12, 1.0, (N_PROJ, N_FIELD))
sc_pj = -np.log(u_pj) / wins
od_pj = np.argsort(sc_pj, axis=1)
# Build rank (sim, rider) → 0-indexed position
rk = np.argsort(od_pj, axis=1)
# For each sim, sum log-ratios per rider based on their tier
log_w = np.zeros(N_PROJ)
for i in range(N_FIELD):
    pos = rk[:, i]
    log_w += np.where(pos < 3,  log_ratio_t3[i],
              np.where(pos < 10, log_ratio_t10not3[i],
                                 log_ratio_11plus[i]))

# Subtract max for numerical stability
log_w_norm = log_w - log_w.max()
w = np.exp(log_w_norm)
print(f'\n[C] Per-sample weight magnitude under tier-factorized IS (n_proj={N_PROJ})')
print(f'  log-weight range: [{log_w.min():.2f}, {log_w.max():.2f}]')
print(f'  After max-subtract → weight range: [{w.min():.3e}, {w.max():.3e}]')
print(f'  Median weight (normalized): {np.median(w):.4f}')
print(f'  Mean weight (normalized):   {w.mean():.4f}')

# ESS = (sum w)^2 / sum w^2
ess = w.sum() ** 2 / (w ** 2).sum()
ess_frac = ess / N_PROJ
print(f'  ESS = {ess:.0f}  ({ess_frac*100:.1f}% of n_sims) — projection')
print(f'  Target: ESS > 0.5 × n_sims for clean reweighting; <0.5 surfaces weight imbalance')

# Max single-sample weight as multiple of median (variance concern)
max_to_median = w.max() / max(np.median(w), 1e-12)
print(f'  Max-to-median weight ratio: {max_to_median:.1f}×')

# What's the marginal recovery look like under this importance-sampling scheme?
# Compute weighted top3 marginal for canary riders
print(f'\n[D] Projected weighted-marginal recovery for canary riders (n_proj={N_PROJ})')
print(f'  {"rider":<14} {"market_t3":>10} {"weighted_t3":>12} {"abs_err":>9}')
print('  ' + '-' * 50)
total_w = w.sum()
for n_id, (target_t3, target_t10) in MARKET.items():
    i = int(n_id.split('_')[1])
    in_top3_mask = (rk[:, i] < 3).astype(np.float64)
    weighted_t3 = (in_top3_mask * w).sum() / total_w
    err = weighted_t3 - target_t3
    print(f'  {n_id:<14} {target_t3:>10.3f} {weighted_t3:>12.3f} {err:>+9.3f}')

# Save
snapshot = {
    'date': '2026-05-18',
    'phase': 'S17-EV-FIX Phase 1 attempt 2 pre-implementation audit',
    'n_field': N_FIELD,
    'n_calibration': N_CAL,
    'calibration_cost_ms': cal_cost_ms,
    'pl_marginals_canary': {n: {'pl_t3': float(pl_top3[int(n.split('_')[1])]),
                                 'pl_t10': float(pl_top10[int(n.split('_')[1])]),
                                 'r_t3': float(ratio_t3[int(n.split('_')[1])]),
                                 'r_t10not3': float(ratio_t10not3[int(n.split('_')[1])]),
                                 'r_11plus': float(ratio_11plus[int(n.split('_')[1])])}
                             for n in MARKET},
    'weight_distribution': {
        'log_range': [float(log_w.min()), float(log_w.max())],
        'median_normalized': float(np.median(w)),
        'mean_normalized': float(w.mean()),
        'ess_projected': float(ess),
        'ess_fraction': float(ess_frac),
        'max_to_median_ratio': float(max_to_median),
    },
}
out_path = Path(__file__).parent / 's17_evfix_phase1a2_audit_results.json'
out_path.write_text(json.dumps(snapshot, indent=2))
print(f'\nSnapshot persisted at {out_path.relative_to(Path.cwd())}')
