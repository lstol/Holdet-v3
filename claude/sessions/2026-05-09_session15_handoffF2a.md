# Session 15 — Handoff F₂a: race-type tickbox + n1 odds adjustment

## What changed

### `claude/engine/optimizer.py`
- `build_probabilities` gains `use_race_type=False` parameter.
- After per-rider `result[name] = {...}` is built and **before** `add_stage_evs`,
  apply a SCENARIO_TO_TERRAIN-derived multiplier when `use_race_type` is True
  AND the n1 sliders are non-uniform (skip the work otherwise).
- Multiplier per rider:
  - `match    = Σ_bucket s[bucket] · Σ_dim SCENARIO_TO_TERRAIN[bucket][dim] · ta[dim]`
  - `baseline = Σ_bucket 0.25       · Σ_dim SCENARIO_TO_TERRAIN[bucket][dim] · ta[dim]`
  - `multiplier = clamp(match / baseline, 0.6, 1.5)` (1.0 if baseline tiny)
- Apply to `win`, `top3`, `top10`, **`top15`**, then renormalize each so the
  post-multiplier bucket sum equals the pre-multiplier sum (preserves
  bookmaker overround).
- Recompute `finish_probs`, `p2`, `p3`, `p_top15`, `finish_ev` per rider from
  the rescaled values. `add_stage_evs` then runs as before and picks up the
  new finish_probs/finish_ev to recompute sprint_ev/jersey_ev/gc_ev/kom_ev/
  total_ev consistently.
- **Note on `top15`**: handoff math listed only `win/top3/top10`, but the
  per-position computation uses `d1115 = (top15 − top10) / 5`. Without
  scaling top15, scaling top10 alone could make d1115 go negative (clamped
  to 0, collapsing positions 11-15). Scaling top15 by the same multiplier
  keeps the per-position distribution self-consistent. Same renormalization
  applies — no overround drift.

### `claude/engine/server.py`
- `/run-optimizer` reads `use_race_type_adjustment` from request body
  (default False) and forwards it to `build_probabilities`.
- The `score_ingemann` call site is unchanged: it passes empty sliders and
  the default `use_race_type=False`, so no behavioural change there.

### `claude/dashboard/claude.html`
- New `S.useRaceTypeAdjustment` (default false), persisted to
  `localStorage['holdet_use_race_type']`.
- Tickbox rendered in the **n1 panel header only** ("Adjust odds by race
  type"). Two new helper CSS classes: `.slider-panel.dimmed` (50% opacity
  on rows + sum) and `.race-type-toggle` / `.slider-panel-title.with-toggle`
  for layout.
- When the box is unchecked, the n1 slider rows are dimmed and each row
  carries `title="Tick the box to apply"` so it's clear they're inert.
- `toggleRaceType(checked)` updates state, persists, re-renders.
- `runPyOptimizer` now sends `use_race_type_adjustment: S.useRaceTypeAdjustment`
  in the request body.
- `init()` reads the persisted boolean before the first `renderSliders()`.

## Verification

Server up in 1s. Three tests against `/run-optimizer` for stage 2.

### No-op invariants

**Test 1 (tickbox OFF)** vs **Test 2 (tickbox ON, sliders all 25%)**: at the
team-pick level all four strategies pick the **same 8 riders** in both
runs. The small EV deltas (≤1%) come from `simulate_stage` using an
unseeded `np.random.default_rng()` — Monte Carlo noise, not adjustment
drift.

Direct call to `build_probabilities` confirms the no-op at the per-rider
level:

```
NO-OP CHECK: off vs uniform-on, riders with |Δp_win|>1e-9: 0
```

Sum-preservation (off → 100% breakaway):

| bucket | Σ off       | Σ breakaway | |Δ|       |
|--------|-------------|-------------|-----------|
| win    | 1.000000    | 1.000000    | 0.00e+00  |
| top3   | 6.235222    | 6.235222    | 8.88e-16  |
| top10  | 15.215167   | 15.215167   | 1.78e-15  |
| top15  | 18.141442   | 18.141442   | 0.00e+00  |

### Directional shift (off → 100% breakaway, n1 slider)

**Top 5 gainers** (sorted by Δp_win):

| rider                    | off    | brk    | Δ       | sprint | mixed | climb |
|--------------------------|--------|--------|---------|--------|-------|-------|
| António Morgado          | 8.81%  | 9.69%  | +0.88pp | 0.25   | 0.58  | 0.68  |
| Jonas Vingegaard         | 3.73%  | 4.27%  | +0.53pp | 0.20   | 0.72  | 0.92  |
| Jan Christen             | 3.66%  | 4.14%  | +0.48pp | 0.20   | 0.55  | 0.65  |
| Andrea Vendrame          | 6.68%  | 7.06%  | +0.39pp | 0.42   | 0.62  | 0.58  |
| Lennert Van Eetvelt      | 2.40%  | 2.73%  | +0.33pp | 0.22   | 0.65  | 0.78  |

**Top losers**:

| rider                    | off    | brk    | Δ       | sprint | mixed | climb |
|--------------------------|--------|--------|---------|--------|-------|-------|
| Corbin Strong            | 9.92%  | 7.17%  | −2.75pp | 0.80   | 0.40  | 0.22  |
| Tobias Lund Andresen     | 4.23%  | 3.01%  | −1.22pp | 0.82   | 0.40  | 0.22  |
| Filippo Ganna            | 3.95%  | 3.28%  | −0.66pp | 0.72   | 0.52  | 0.42  |
| Kaden Groves             | 1.55%  | 1.08%  | −0.47pp | 0.85   | 0.40  | 0.22  |

Direction is exactly what the matrix should produce: `breakaway → 1.0 ×
mixed` rewards riders with high `mixed` affinity (all-rounders /
breakaway-friendly types) and pulls win mass away from pure sprinters.
Multiplier clamp [0.6, 1.5] keeps the shift bounded; renormalization keeps
the overall bookmaker overround pinned exactly where it was.

### Team-level shift in Test 3

The `low-transfer` strategy reflects the per-rider shift cleanly: with
breakaway on, **Corbin Strong → Jan Christen** (the biggest individual
loser swapped out for a small-but-rising gainer). The other three
strategies' picks didn't change — the bookmaker odds anchor still
dominates a clamped-1.5× nudge in this odds field. That's expected.

## Dashboard sanity

- Tickbox visible inline in the Stage {targetStage} panel header,
  right-aligned, default unchecked.
- When unchecked, the four n1 slider rows + sum display are 50% opacity
  and carry "Tick the box to apply" tooltips.
- n+1 / n+2 panels remain full-opacity (always apply to lookahead).
- Toggle persists across reload via `localStorage['holdet_use_race_type']`.

## Notes / oddities

- `simulate_stage` uses `np.random.default_rng()` with no seed, so EV
  values fluctuate by O(0.5%) between runs of identical inputs. That's
  why Test 1 vs Test 2 show small ev deltas despite identical team picks.
  Not part of F₂a; flagged here as a known property when reading the
  optimizer output.
- `top15` is also scaled-and-renormalized despite the handoff math
  omitting it; rationale documented in the optimizer.py section above.
