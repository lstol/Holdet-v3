# Session 15 — Handoff F₁: rename slider buckets + revive forward lookahead

## Bucket rename

Old → new (across optimizer.py, server.py, claude.html):

| old      | new              | display label    |
|----------|------------------|------------------|
| sprint   | bunch_sprint     | Bunch sprint     |
| hilly    | reduced_sprint   | Reduced sprint   |
| hardgc   | gc               | GC               |
| mixed    | breakaway        | Breakaway        |

## Changes

### `claude/engine/optimizer.py`
- Added module-level `SCENARIO_TO_TERRAIN` (4 entries) — the only "scenario
  hardcoding," generic across riders.
- Replaced `TYPE_WIN_WEIGHT` block + the `r.get('type', 'All-rounder')`
  fallback inside `build_forward_probabilities`. New scoring loop reads
  `r['terrain_affinity']` directly (`sprint`, `mixed`, `climbing` — already
  present on every rider record).
- Removed dead `gc_penalty` flag (was always False anyway: relied on the
  same missing `'type'` key).
- Removed the `'gc' / 'hardgc'` fallback — only `'gc'` now.

### `claude/engine/server.py`
- Renamed slider keys in the `_run_optimizer_claude_api_legacy` prompt
  formatter `sl()` (legacy/dead path; renamed for hygiene).

### `claude/dashboard/claude.html`
- Updated default `S.sliders` for `n1/n2/n3` to use the new keys.
- `renderSliders` bucket loop + display-name map switched to the new four
  keys with the new labels.
- `updateSlider` and `updateSumDisplay` switched to the new keys.
- `slStr()` (prompt-copy formatter) updated.
- Added `migrateSliders(blob)` and wired it into `init()` — on first load
  after deploy, the previously-persisted `holdet_sliders` blob (with
  `sprint/hilly/hardgc/mixed`) is rewritten in place to the new keys and
  written back to localStorage. Logs a one-line console message.

## Verification

Server restarted via `launchctl kickstart -k`; up in 1s.

### Lookahead differentiation test (the whole point of F₁)

Two runs against `/run-optimizer` for stage 2, identical except for the
**n+1 (`n2`) sliders**:

- **Test 1**: `n2 = {bunch_sprint: 100}` (sprint-favored)
- **Test 2**: `n2 = {gc: 100}` (gc-favored)

Clearest signal — the **`low-transfer`** strategy (which explicitly minimizes
`compute_transfer_cost(team, team_n1)`):

| Test           | low-transfer team (first 3 riders)             |
|----------------|------------------------------------------------|
| sprint-favored | António Morgado, Jonathan Milan, Arnaud De Lie |
| gc-favored     | Thymen Arensman, Sepp Kuss, Corbin Strong      |

Sprinters → climbers: the matrix is biasing `team_n1` toward riders whose
`terrain_affinity` matches the requested forward scenario. That's the revival.

Secondary signals on the `optimal` strategy's `forward.{transfers_n1,
cost_n1}` (both downstream of the same `team_n1`):

| Test           | transfers_n1 | cost_n1 |
|----------------|--------------|---------|
| sprint-favored | 8            | 483 380 |
| gc-favored     | 7            | 397 340 |

The **lookahead** strategy's own team converges to the same 8 riders across
both tests. That's expected: lookahead's objective is
`base_ev - tc_n1 - 0.7*tc_n2`, and `base_ev` (driven by stage-2 bookmaker
odds, which are sprint-skewed because stage 2 itself is sprint-favored) is
much larger in magnitude than the transfer-cost penalty. So lookahead's
*current-stage* pick is dominated by current-stage EV; the differentiated
`team_n1` shows up in `forward.{transfers_n1, cost_n1}` instead. This is an
architectural property of the lookahead weighting, not an F₁ regression.

### Dashboard sanity

- Restart was clean (1s downtime).
- Served `claude.html` contains zero `(sprint|hilly|hardgc|mixed)` references
  outside `migrateSliders`'s `keymap` (the old→new dict — intended).
- Optimizer round-trips successfully on both test inputs.

Hard refresh on the dashboard should show four sliders per stage with the new
labels, with previously-tuned values migrated in place from the old keys.

## Out of scope (deferred to F₂)

- The `n1` (current-stage) slider still has no effect on current-stage rider
  EV — `build_probabilities` declares `sliders` but never references it.
  F₂ will introduce a tickbox + odds adjustment.
- `gc_penalty` is still read in `compute_transfer_cost` but never set.
  Could be revived with `terrain_affinity`-based semantics, but that's a
  scope expansion not in F₁.
