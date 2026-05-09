# Session 15 — Handoff F₂b: forward costs + transfer-adjusted EV on every card

## Scope

Pure dashboard read. No optimizer math change. No server change.

## Field names confirmed

The actual response shape per team:

```
team.ev_estimate                       # gross stage EV (Monte Carlo mean)
team.transfer_cost                     # current-stage transfer cost (positive)
team.ev_net                            # = ev_estimate − transfer_cost
team.forward.cost_n1                   # n+1 transfer cost (positive)
team.forward.cost_n2                   # n+2 transfer cost (positive)
team.forward.transfers_n1              # n+1 transfer count
team.forward.transfers_n2              # n+2 transfer count
team.forward.total_forward_cost        # = cost_n1 + 0.7 × cost_n2
```

So `team.forward.{cost_n1, cost_n2}` rather than the handoff's hypothesised
`team.cost_n1`. The optimizer **already** publishes `total_forward_cost` with
the exact `0.7` discount the handoff specifies — used directly as the
forward-cost term in the new transfer-adj EV.

## Backend change required?

**No.** [optimizer.py:986-991](claude/engine/optimizer.py:986) populates the
`forward` block inside the per-strategy results loop, so all 4 strategies
already carry `cost_n1`, `cost_n2`, `transfers_n1`, `transfers_n2`,
`total_forward_cost`. JSON sanity check confirmed identical structure across
optimal / depth / low-transfer / lookahead.

## Dashboard change

[claude/dashboard/claude.html](claude/dashboard/claude.html) only.

- New CSS: `.ev-fwd-row`, `.ev-fwd-val`, `.ev-fwd-ann`, `.ev-fwd-row.missing`,
  `.ev-adj-row`, `.ev-adj-val`, `.team-card.adj-best` (subtle inset
  success-color border).
- New `transferAdjHtml(team)` helper next to `fwdHtml(fwd)`. Reads
  `team.forward.{cost_n1, cost_n2, transfers_n1, transfers_n2}` and
  `team.ev_net`, returns three rows:
  - `Forward n+1   −Xk (Y tr)`
  - `Forward n+2   −Xk (Y tr) × 0.7`
  - `Transfer-adj EV   +Zk` (green, bold, separator)
- Calls `transferAdjHtml(team)` inside the existing `tc-ev-section` right
  after the `ev-total-row`.
- Pre-pass at the top of `renderOptimizerOutput` computes the
  index of the optimizer team with the highest `(ev_net − cost_n1 − 0.7
  · cost_n2)` and adds class `adj-best` to that one card. **Card order is
  preserved** (Optimal / Depth / Low-transfer / Lookahead) per Session 13's
  design decision; this is informational highlight only.
- If `cost_n1` or `cost_n2` is missing/null on a team, the corresponding row
  renders `—` (greyed via `.ev-fwd-row.missing`) and the Transfer-adj EV
  row also shows `—`. No NaN, no crash.

## Verification — JSON sanity (stage 2)

| strategy        | net      | cost_n1  | cost_n2   | total_fwd | adj      |
|-----------------|----------|----------|-----------|-----------|----------|
| optimal         | 718,910  | 421,500  | 215,000   | 572,000   | 146,910  |
| depth           | 720,561  | 421,500  | 215,000   | 572,000   | 148,561  |
| low-transfer    | 523,800  |  82,670  | 215,000   | 233,170   | **290,630** |
| lookahead       | 689,167  | 380,050  | 215,000   | 530,550   | 158,617  |

Manual check: `low-transfer` adj = 523,800 − 82,670 − 0.7 × 215,000
= 523,800 − 82,670 − 150,500 = **290,630**. Matches.

`total_forward_cost` matches `cost_n1 + 0.7 × cost_n2` exactly across all
four strategies (off by ≤ 0.1 due to integer rounding in the optimizer).

## Note on which strategy "wins"

In this run **low-transfer wins** transfer-adj EV (290k), beating lookahead
(159k). That's expected for these inputs:

- Low-transfer's objective is `base_ev − 3 × tc_current` — heavy current-stage
  transfer-cost penalty. Its picks already overlap heavily with the user's
  current team, so both `transfer_cost` (current) and `cost_n1` (n+1) come
  out small.
- Lookahead's objective is `base_ev − tc_n1 − 0.7 × tc_n2` — it discounts
  **forward** transfer costs but doesn't penalise the **current**-stage
  transfer cost. So it can pick an 8-transfer current team if the gross
  EV justifies it, which inflates `transfer_cost` and shrinks `ev_net`.

Transfer-adj EV is the user-side comparison metric (now `ev_net − cost_n1
− 0.7 × cost_n2`); whichever strategy minimises **all** transfer costs
together wins on it. That's not a bug — it's exactly what makes transfer-adj
EV a different lens from any single strategy's internal objective.

## Served-HTML sanity

```
new CSS classes (.ev-fwd-row | .ev-adj-row | .adj-best)  → 11 occurrences
function transferAdjHtml served                           → 2 occurrences
adjBestIdx pre-pass served                                → 2 occurrences
```

Server up via `launchctl kickstart -k` in 1s.
