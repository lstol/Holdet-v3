# Session 15 — Handoff D₁: header cleanup + EV breakdown Total → Net EV

Pure dashboard work. No optimizer / server / API changes.

## Item 1 — Bank display removed

- **HTML**: removed `<div class="stat-pill">…<span id="h-bank">50.00M</span>…</div>`
  from the `#header-right` block.
- **JS**: removed `$('h-bank').textContent = fmt_price(S.bankBalance);` from
  `updateHeader`.
- **State (no longer read by anything)**: removed `S.bankBalance: 50000000`
  field from S, and the `S.bankBalance = data.bank_balance || 50_000_000;`
  write inside `loadSnapshot`. `loadSnapshot` still calls `updateHeader()`
  for the stage-meta line.

## Item 2 — Refresh button renamed

- `<button id="refresh-btn">…Refresh</button>` → `…Refresh riders`. Same
  id, same `onclick="refreshData()"`.

## Item 3 — "Not loaded" status removed

- **HTML**: removed `<div class="stat-pill">…<span id="h-data-status">Not
  loaded</span><span id="h-data-note">…</span></div>`.
- **JS**: removed the entire `const statusEl = $('h-data-status'); …` block
  (~13 lines) inside `updateHeader`.
- **State (no longer read)**: removed `S.mockMode: false` and
  `S.dataTimestamp: null` from S, plus the writes
  `S.dataTimestamp = data.timestamp || null; S.mockMode = false;` and
  `S.mockMode = true;` inside `loadRiders`.
- `.stat-pill` and `.mock-badge` CSS rules left in place — no DOM uses
  them now, but they're invisible dead-CSS, not in scope to delete.

## Item 4 — EV breakdown "Total" → "Net EV" (sums all rendered rows)

Inside `buildCard` in `renderOptimizerOutput`:

```diff
 <div class="ev-total-row">
-  <span>Total</span>
-  <span class="ev-total-val">${fmt(team.ev_estimate)}</span>
+  <span>Net EV</span>
+  <span class="ev-total-val">${fmt(team.ev_net !== undefined ? team.ev_net : team.ev_estimate)}</span>
 </div>
 ${transferAdjHtml(team)}
```

Same expression as the green Net-EV value in the card header (line 1900),
so the two are guaranteed to match. The `transferAdjHtml(team)` rows below
already use `team.ev_net` for the Transfer-adj EV calculation — unchanged.

The optimizer publishes `team.ev_net = ev_estimate − transfer_cost`
(server `generate_candidate_teams`), and the breakdown dict already has
`transfer_cost` injected as a negative value. So
`Σ(rendered_breakdown_rows) = Σ(positive components) + (−transfer_cost) =
ev_estimate − transfer_cost = ev_net`. The new label semantically matches
what the rendered rows actually sum to.

### JSON sanity (stage 2, run from main)

| strategy        | ev_estimate | transfer_cost | ev_net    | ev − tc   | match |
|-----------------|-------------|---------------|-----------|-----------|-------|
| optimal         | 1,213,629   | 485,700       | 727,929   | 727,929   | YES   |
| depth           | 1,195,214   | 485,700       | 709,514   | 709,514   | YES   |
| low-transfer    |   840,536   | 322,240       | 518,296   | 518,296   | YES   |
| lookahead       | 1,180,467   | 487,150       | 693,317   | 693,317   | YES   |

`ev_net == ev_estimate − transfer_cost` for all four; the dashboard's
breakdown Net EV (and the header green value) display this same
`team.ev_net`.

### Component-sum drift (informational)

Manually summing the rendered breakdown rows (including the negative
`transfer_cost` row) matches `ev_net` exactly for **optimal**, and is off
by 1–2 kr for the other three. That's pre-existing rounding drift from
the optimizer's `int()` of each component mean inside `simulate_stage`,
not introduced by D₁. The displayed Net EV uses the canonical
`team.ev_net` directly (not a JS-side sum), so the dashboard always shows
the exact value — the off-by-a-few-kr only shows up if a user mentally
adds the visible bar values.

## Served-HTML sanity

```
h-bank refs                  → 0
h-data-status refs           → 0
'>Refresh<' (no 'riders')    → 0
'Refresh riders'             → 1
'<span>Total</span>'         → 0
'<span>Net EV</span>'        → 1
```

Server up via `launchctl kickstart -k` in 1s.
