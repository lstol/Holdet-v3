# Session 15 — Handoff D₂: intel panel + How it unfolded

## Item 1 — Intel panel fills its rectangle

**Cause**: `#intel-grid` is a 2-column grid (default `align-items: stretch`),
so the right intel-panel stretched to match the taller odds-panel. But
`#intel-display` had `max-height: 200px` and the panel had no flex layout,
so the display stayed 200px and the rest of the right rectangle was blank.

**Fix** (CSS only):

```diff
-.intel-panel { … padding: 12px; }
+.intel-panel { … padding: 12px; display: flex; flex-direction: column; }

-#intel-display { font-size: 12px; max-height: 200px; overflow-y: auto; }
+#intel-display { font-size: 12px; flex: 1; overflow-y: auto; }
```

The panel is now a flex column; `#intel-display` flex-grows to fill the
remaining height. If intel content exceeds the rectangle, it scrolls inside
the panel — same overflow behaviour as before.

## Item 2 — Fetch Ingemann button above its card slot

**Before**: button at [claude.html:583](claude/dashboard/claude.html:583)
inside the intel-panel header, next to "Gather".

**After**: removed from intel header. Added a 300px-wide flex row
(`#ingemann-btn-row`) directly above `#optimizer-output`, matching the
card slot width (cards are `flex: 0 0 300px` per existing CSS). Button
text expanded "Ingemann" → "Fetch Ingemann" since space allows. Same id
(`gather-ingemann-btn`), same `onclick="gatherIngemann()"` — no JS change.

## Item 3 — "New Rider Value" column

**Data source**: per-rider `stage_pts` from `stage_N_results.json`. That
field is the Holdet API's `priceChange` (per
[fetch_riders.py:558](claude/engine/fetch_riders.py:558) — the comment
explicitly calls it "the assets score"). It's exactly the per-rider value
delta the handoff specified.

**Heads-up**: in the current data, `priceChange` (`stage_pts`) and the
existing **Stage** column display the same value, because
`fetch_stage_results` populates only `stage_pts` and `captain_bonus` —
the per-rider `sprint_pts` / `jersey_bonus` / `gc_bonus` / `team_bonus`
breakdown is not surfaced by the API endpoints we use. So the new
column visually duplicates the **Stage** column for non-captain riders.
For the captain, **Total** ≠ **Stage** ≠ **New Rider Value** (Total =
Stage + Captain bonus). Logged here in case you'd rather rename **Stage**
than add a new column.

**Implementation**: new `<th>New Rider Value</th>` after Total in the
table header; widths rebalanced so they still sum to 100%. New `<td>` in
each row reads `r.stage_pts`, formatted via the same `fmt()` helper
(green positive / red negative / grey "—" for zero).

## Item 4 — Depth bonus count (server + snapshot)

**Root cause**: [fetch_riders.py:585](claude/engine/fetch_riders.py:585)
hard-coded `"riders_in_top15": 0`. The dashboard reads this field and
shows `"0/8 in top 15"` regardless of the actual depth bonus paid.

**Why it can't come from rider_results**: the Holdet endpoints we use
(`/api/games/{game}/rounds/{N}/players` etc.) return `priceChange` per
rider but **not** per-rider finish positions. We never see the integer
finish position, only the kr earned.

**Fix**: reverse-map `assets.specialBonus` (the round-level depth bonus
Holdet pays) → rider count, using the authoritative curve from
[shared/rules/game_strategy.md:16](shared/rules/game_strategy.md:16):

```
0/4k/8k/15k/35k/65k/120k/220k/400k for 0–8 riders.
```

The curve values are unique, so the bonus → count mapping is exact. If
the bonus value is off-curve (shouldn't happen with current rules), the
field is `None` and the dashboard shows `?/8` instead of crashing.

Patched **both** the writer (fetch_riders.py) and the existing snapshot
(`shared/data/snapshots/stage_1_results.json`: `riders_in_top15: 0 → 5`)
so the current dashboard render is correct without re-fetching.

**Hand-check**: stage 1 `depth_bonus = 65,000 kr` → curve says **5**
riders → matches user's reported actual of 5/8. Round-trip on all 9
points 0–8 of the curve was verified.

**Out of scope (worth flagging)**: optimizer.py uses a different curve
internally (`{0:0, 1:0, 2:20k, 3:50k, 4:90k, 5:140k, 6:200k, 7:270k,
8:350k}` at lines 33–43), and a stale dashboard footer prompt-text
([claude.html:1897](claude/dashboard/claude.html:1897)) repeats it.
That's a wrong table that drifts the optimizer's depth-bonus EV — not
just a label issue. Separate handoff.

## Verification

Server up via `launchctl kickstart -k` in 1s.

```
$ curl -s "http://localhost:5050/stage-results?target_stage=2" | jq '...'
  found: True, completed_stage: 1
  depth_bonus: 65000, riders_in_top15: 5
  stage_total: 1787000, captain_name: Jonathan Milan
```

Served-HTML structure check:

```
intel-panel flex column?              1
intel-display max-height removed?     0  (replaced by flex:1)
intel-display flex:1?                 1
Ingemann btn in intel header?         0
Ingemann btn in candidates section?   1
'Fetch Ingemann' label visible?       1
'New Rider Value' header?             1
riders_in_top15 == null check?        1
```
