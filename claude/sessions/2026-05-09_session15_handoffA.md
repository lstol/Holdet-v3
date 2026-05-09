# Session 15 — Handoff A findings (slider diagnostic, no changes)

Read-only audit of how stage-type sliders flow from dashboard → server → optimizer.
No code edits, no commits, no server restart.

## Names

Dashboard state uses keys `n1` / `n2` / `n3` (claude.html:717-721). The user-facing
labels are dynamic — `Stage {targetStage}` / `Stage {targetStage+1}` /
`Stage {targetStage+2}` (claude.html:1242-1244). So `n1` = current stage `n`,
`n2` = `n+1`, `n3` = `n+2`. This is the source of confusion at the boundary.

Buckets per stage: `sprint`, `hilly`, `hardgc`, `mixed` (display: Sprint / Hilly /
Hard GC / Mixed). All four are inputs and forced to sum to 100% by
`updateSlider()` (claude.html:1279-1316).

Persisted to `localStorage.holdet_sliders` as one blob.

## Flow

- Dashboard sends entire `S.sliders` blob in request body (claude.html:1870).
- Server splits by sub-key (server.py:408-415):
  - `sliders.n1` → `build_probabilities(...)` for current-stage probs
  - `sliders.n2` → `build_forward_probabilities(...)` → `probs_n1` for stage n+1
  - `sliders.n3` → `build_forward_probabilities(...)` → `probs_n2` for stage n+2
- Forward cost: `estimate_forward_costs` (optimizer.py:567) runs `fast_optimize`
  on probs_n1 and probs_n2 → diffs against current_team for cost_n1, then
  team_n1 → team_n2 for cost_n2. `LOOKAHEAD_DISCOUNT = 0.7` applied in
  `compute_objective` for the lookahead strategy.

## Two real bugs visible from code alone

1. **Current-stage slider is ignored.** `build_probabilities(...)` (optimizer.py:216)
   has `sliders=None` in the signature but the function body never references it.
   The `n1` widget on the dashboard has zero effect on current-stage EV. Current
   stage type weighting comes from `stage_scoring.json` via `stage_config`, not
   from the slider.

2. **Forward stages can't tell riders apart by type.**
   `build_forward_probabilities` at optimizer.py:473 does
   `rtype = r.get('type', 'All-rounder')`. Rider records in `riders.json` carry
   `terrain_affinity` (climbing/sprint/time_trial/mixed scores) but **no
   top-level `type` key** — verified by inspecting `riders.json`. So every
   rider falls back to `'All-rounder'`, the `TYPE_WIN_WEIGHT` mapping returns
   the same scalar for every rider, renormalization gives uniform 1/N, and
   `fast_optimize` for n+1/n+2 picks essentially undifferentiated teams. The
   slider scales a constant but doesn't bias toward sprint-friendly or
   climber-friendly teams.

   The dashboard's `deriveType()` (claude.html:752-764) does compute a type
   client-side from `terrain_affinity`, but it's never written back into the
   rider records the server uses.

## Coverage gaps

- Slider keys read by optimizer (`sprint`, `hilly`, `hardgc` w/ `gc` fallback,
  `mixed`) match what the dashboard sends. No literal name mismatch.
- The `gc`-fallback branch at optimizer.py:462 is dead (dashboard never sends
  `gc`), but harmless — only worth noting for any future rename.

## Note on the "n+2 = 0 bug"

Not literally visible from code. Both `sliders.n2` and `sliders.n3` are read
correctly, and defaults are non-zero. The deeper issue is that the type-fallback
bug above effectively neutralizes the forward weighting regardless of the
slider values, which would feel like "lookahead never matters" / "n+2 has no
effect" from the outside.

Awaiting Handoff F (rename + fix).
