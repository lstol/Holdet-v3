# Optimizer Architecture Map — Holdet v3

*As of 2026-05-17, audit substrate at commit `1a02094` (post-EV-function-asymmetry verification).*

**Scope:** end-to-end optimizer architecture for `/run-optimizer` Flask endpoint. Read-only audit; line numbers cited per current `main` and may drift — function names are the durable references per CLAUDE_SESSION reasoning pattern.

**Maintenance:** future optimizer audits should update this document in-place rather than spawning new architecture-map files. Reference it from future fix handoffs.

---

## 1. High-level flow

```
POST /run-optimizer  ───► server.py:run_optimizer
                              │
                              ├─ Load substrate (stage_N_odds.json, stage_N_intel.json,
                              │   stage_{N-1}_standings.json, stage_{N-1}_results.json
                              │   for current_team + bank_balance)
                              │
                              ├─ build_probabilities(active_riders, odds, intel,
                              │   sliders['n1'], stage_config, scoring,
                              │   use_race_type, standings)        ◄── ALSO calls
                              │       │                                add_stage_evs internally
                              │       └─► returns probs dict (one entry per rider with
                              │           win/top3/top10/top15/finish_probs/finish_ev/
                              │           sprint_ev/jersey_ev/gc_ev/kom_ev/total_ev/
                              │           team_bonus_ev/...)
                              │
                              ├─ build_forward_probabilities(active, sliders['n2'])
                              │   build_forward_probabilities(active, sliders['n3'])
                              │       └─► returns synthetic probs dicts (terrain × slider
                              │           composition; NO odds/intel input)
                              │
                              └─ generate_candidate_teams(...) ───► optimizer.py:1515
                                       │
                                       ├─ fast_optimize for proxy current_team
                                       │     (if current_team is None)
                                       ├─ estimate_forward_costs ──► fast_optimize × 2
                                       │     (team_n1, team_n2 + cost_n1, cost_n2)
                                       ├─ build_tier_union_pool   ──► biased_pool for SA
                                       │
                                       └─ for strategy in [optimal, depth, lookahead]:
                                             for chain_idx in 0..9:    ◄── 10-chain multi-start
                                                 simulated_annealing(...) ──► returns team
                                                 topup_team(...)
                                                 select_captain(...)
                                                 simulate_stage(...)   ◄── Plackett-Luce MC
                                                                            10,000 sims; THIS is
                                                                            what the user sees
                                             corroboration aggregation (S17-22)
                                             ─► best_seen vs best_corroborated team

                                       └─ assemble result JSON (per-strategy teams +
                                                                 forward-cost breakdown +
                                                                 convergence metadata)
```

**Critical asymmetry surfaced (commit `1a02094`):**
- **SA chains optimize `compute_objective` which calls `compute_team_ev`** (naive marginal sum).
- **Post-SA, each chain's team is re-evaluated via `simulate_stage`** (Plackett-Luce Monte Carlo) to produce the displayed `ev_estimate` / `ev_net`.
- These two metrics disagree by 20-54% on Stage 9 substrate (compute_team_ev systematically overstates). On the canonical Optimal-vs-Lookahead test they rank rosters oppositely.

---

## 2. Strategy registration and dispatch

**Location:** `generate_candidate_teams` at `optimizer.py:1586-1619`.

Three strategies defined as a list of dicts. Each carries:

| Field | optimal | depth | lookahead |
|---|---|---|---|
| `name` | `'optimal'` | `'depth'` | `'lookahead'` |
| `strategy_xor` | `0x1` | `0x2` | `0x4` |
| `legacy_seed` | 42 | (depth-internal) | 2026 |
| `objective` | `'ev'` | `'depth'` | `'lookahead'` |
| `n_iter` | 200_000 | 200_000 | 200_000 |
| `max_seconds` | 5 | 5 | 5 |
| `sa_overrides` | `{}` | `{}` | `{'cooling_rate': 0.99999}` |

**`strategy_xor` 0x3 reserved-historical** — retired `low-transfer` strategy (S17-26). Do NOT reuse; preserves bit-identical reproducibility of cached results.

Chain seeds derived per strategy via `chain_seed = base_seed ^ (strategy_xor << 8) ^ chain_xor` where `chain_xor ∈ [0xC0..0xC9]` for the 10 chains (line 1646).

**Lookahead-specific selection rule** (S17-ζ-fix (c), line 1719-1727): for lookahead strategy, cross-chain selection uses `look_obj = ev - tc_current - tc_n1 - 0.7 × tc_n2`, NOT raw stage EV. Other strategies pick chain by raw EV (line 1729-1731).

---

## 3. SA objective per strategy

**Function:** `compute_objective(team, probabilities, all_riders, objective, cost_n1, cost_n2, team_n1, team_n2, current_team)` at `optimizer.py:1023`.

All three branches call `compute_team_ev(team, probabilities)` as their `base_ev`. They differ in what they add/subtract:

### 3.1 Optimal — `objective='ev'`

```python
return compute_team_ev(team, probabilities)
```

Pure marginal-sum team EV. No transfer cost, no forward cost, no depth bonus modifier. **`compute_team_ev` already includes a depth bonus via `DEPTH_BONUS[round(sum(top15))]`** — so "optimal" naturally rewards top-15 coverage, just at the standard DEPTH_BONUS weight.

### 3.2 Depth — `objective='depth'`

```python
expected_top15 = sum(probabilities[r['name']]['top15'] for r in team)
return compute_team_ev(team, probabilities) + DEPTH_BONUS.get(min(8, round(expected_top15)), 0) * 2
```

`base_ev` + an EXTRA `2× DEPTH_BONUS` on top of the depth bonus already baked into `compute_team_ev`. Net: depth bonus weighted 3× (`1× from compute_team_ev + 2× extra`). Pulls SA toward top-15 coverage.

**Note:** `compute_team_ev` uses `round(exp_top15)` and `_compute_objective(depth)` at line 812 uses different weights (`finish_ev × 0.5 + DEPTH_BONUS × 3`); this `_compute_objective` function at line 812 is **deprecated / unused in production path** — `compute_objective` (line 1023) is the actual SA call site per line 1362.

### 3.3 Lookahead — `objective='lookahead'`

```python
tc_current = compute_transfer_cost(current_team or [], team)        if current_team else 0
tc_n1      = compute_transfer_cost(team, team_n1 or [])             if team_n1 else 0
tc_n2      = compute_transfer_cost(team_n1 or [], team_n2 or [])    if team_n1 and team_n2 else 0
return base_ev - tc_current - tc_n1 - LOOKAHEAD_DISCOUNT × tc_n2
```

`LOOKAHEAD_DISCOUNT = 0.7`. Two-stage forward-cost-aware objective.

**Critical observation for fix-shape decision:** Lookahead's SA objective uses `compute_team_ev` (same naive marginal sum as optimal/depth). The `simulate_stage` Plackett-Luce MC is NOT in any SA loop. Lookahead's "better" alignment with displayed Net EV on Stage 9 is incidental — it stems from including current_team riders (zero transfer cost on Vingegaard) rather than from any MC-aware objective.

**Does ANY strategy use `simulate_stage` in SA?** **NO.** All three optimize compute_team_ev variants. simulate_stage is post-SA evaluation only.

---

## 4. EV function shapes

### 4.1 `compute_team_ev(team, probs)` — `optimizer.py:720`

**Method:** naive marginal sum (no mutual-exclusivity).

```python
total_evs = [probs[r['name']]['total_ev'] for r in team]    # 8 per-rider expectations
total  = sum(total_evs)                                      # 8-rider sum
total += max(total_evs)                                      # captain bonus = max rider's total_ev
total += compute_team_bonus_ev(team, probs)                  # team-bonus pairs
exp_top15 = sum(probs[r['name']]['top15'] for r in team)
total += DEPTH_BONUS[min(8, round(exp_top15))]               # depth bonus
return total
```

**Scoring components included:** ALL eight (finish, sprint, jersey, GC, KOM, captain, team-pairs, depth) — but each is computed marginally.

**Where `total_ev` comes from:** `add_stage_evs` (line 359-463) computes per-rider `total_ev = finish_ev + sprint_ev + jersey_ev + gc_ev + kom_ev` for each component independently, where each component is a sum of marginal probabilities × per-position points. **No joint modeling.** Independence-assuming throughout.

### 4.2 `simulate_stage(team_riders, all_probs, captain_name, all_riders, n_sims=10_000, stage_config, scoring, seed)` — `optimizer.py:1867`

**Method:** Plackett-Luce Monte Carlo over the FULL field (~170 riders).

```python
field_probs = np.array([all_probs[n]['win'] for n in all_field_names])    # ONLY win prob used
field_probs /= field_probs.sum()                                            # normalize
u      = rng.uniform(1e-12, 1.0, (n_sims, n_field))
scores = -np.log(u) / field_probs        # PL scores
order  = np.argsort(scores, axis=1)      # finish order per sim (joint dist)
rank   = np.argsort(order, axis=1)
team_pos = rank[:, team_idxs]            # team riders' 0-indexed finish positions
```

**Scoring components ALL covered position-by-position from the joint sample:**
- `finish_pts`: FINISH_POINTS[team_pos] if team_pos < 15 else 0
- `sprint_pts`: per-position sprint points lookup (final + intermediate × `n_intermediate_sprints`)
- `jersey_pts`: winner_jersey if team_pos == 0
- `gc_pts`: GC_BONUS[team_pos+1] if team_pos < 10
- `kom_pts`: per-climb category points based on team_pos
- `team_bonus`: TEAM_BONUS_MAP[position] × (rider's real-world team in any top-3 slot)
- `depth_pts`: DEPTH_BONUS[count_of_team_in_top_15]
- `captain_bonus`: rider_totals[capt_ti] doubled (capped at ≥0)

**Critical:** simulate_stage's PL sampling uses ONLY `win` probability per rider. top3/top10/top15 marginals from build_probabilities are NOT consumed — they're implicitly derived from the joint distribution.

**Outputs:** `{mean, cdf={p25,p50,p75,p90}, breakdown={stage_finish, sprint_points, jersey_bonus, gc_bonus, kom_points, captain_bonus, team_bonus, depth_bonus}}`.

### 4.3 `fast_optimize(candidates, probabilities, all_riders, force_in, force_out, budget, seed)` — `optimizer.py:925`

**Method:** lightweight SA (10,000 iter, biased-swap on top-50-by-EV). Uses `compute_team_ev` as objective (line 943, 972).

**Purpose:** in-vacuum forward-stage proxy (used by `estimate_forward_costs` to compute team_n1, team_n2 — the hypothetical optimal rosters for stages n+1 and n+2 against forward probability distributions).

**Called from:**
- `estimate_forward_costs` (line 990, 991) — × 2 for n+1 and n+2 proxies
- `generate_candidate_teams` (line 1552) — when `current_team` is None (no prior race)

**Does NOT use simulate_stage.**

### 4.4 `build_probabilities(all_riders, odds, intel, sliders, stage_config, scoring, use_race_type, standings)` — `optimizer.py:468`

**Inputs:**
- `all_riders` — list of active rider dicts (each with name, price, team, terrain_affinity)
- `odds` — list of `{name, win_pct, top3_pct, top10_pct}` rows (from `stage_N_odds.json`)
- `intel` — dict with `key_signals: [{rider, direction, strength}, ...]` (from `stage_N_intel.json`)
- `sliders` — n+0 slider dict (only used if `use_race_type=True`)
- `standings` — dict with GC top-10 (used by Sub-B2 standings-aware retention)

**Output:** dict `{rider_name: {win, top3, top10, top15, finish_probs, finish_ev, sprint_ev, jersey_ev, gc_ev, kom_ev, total_ev, p2, p3, p_top15, team, name, team_bonus_ev (?)}}`.

**Computation flow (lines 468-693):**
1. Build `odds_map`, `top3_map`, `top10_map` from `odds` (name-matcher-hardened canonicalization)
2. Build `adj` (intel multiplier per rider) from `intel['key_signals']`: lookup `INTEL_MULT[(direction, strength)]`
3. Per rider: `raw[name] = odds_map.get(name, EPS) × adj.get(name, 1.0)` ◄── **INTEL_MULT APPLICATION POINT**
4. Renormalize: `raw[name] /= total` (sum to 1.0 across all riders)
5. Per rider: derive top3/top10/top15 marginals via fallback chain (S17-31): use market top3/top10 if present, else extrapolate from observed values (per `C3_WIN`, `C10_TOP3`, `C10_WIN` calibration)
6. Build `finish_probs` array (per-position marginal: fp[0]=win, fp[1..2]=top3-share, fp[3..9]=top4-10-share, fp[10..14]=top11-15-share)
7. Compute `finish_ev` from finish_probs × position-weight constants (`_FP_W1`, `_FP_W23`, `_FP_W4_10`, `_FP_W11_15`)
8. If `use_race_type and sliders` and non-uniform: apply race-type multiplier per rider via `SCENARIO_TO_TERRAIN × terrain_affinity`, clamp to [0.6, 1.5], renormalize per-bucket sum-preserving (lines 591-649)
9. Call `add_stage_evs` to add sprint_ev/jersey_ev/gc_ev/kom_ev/total_ev per rider (Sub-B2 standings-aware override for top-10 GC riders if applicable)

**INTEL_MULT renormalization invariant:** after multiplier application, total mass is renormalized to 1.0. Per-rider effective multiplier in stage_EV terms may differ from declared 1.20 due to (a) other riders' bumps diluting via renorm, (b) component composition (intel only affects win/top3/top10/top15 → finish_ev/sprint_ev/jersey_ev pathway; doesn't touch gc_ev from Sub-B2 standings-aware retention OR kom_ev directly).

### 4.5 `build_forward_probabilities(riders, sliders)` — `optimizer.py:857`

Synthetic probability distribution for forward stages (n+1, n+2). NO odds/intel input — purely composed from `terrain_affinity × SCENARIO_TO_TERRAIN × sliders`.

```python
for rider:
    score = Σ_bucket (slider_weight[bucket] × Σ_dim (SCENARIO_TO_TERRAIN[bucket][dim] × ta[dim]))
    raw[name] = max(0.001, score)
total = sum(raw.values())
win[name] = raw[name] / total
top3  = min(0.95, win × 3.5)
top10 = min(0.95, win × 8.0)
top15 = min(0.95, win × 12.0)
```

Per-rider top3/top10/top15 marginals derived from win via fixed multipliers (3.5, 8.0, 12.0). Includes `finish_ev` and `total_ev` (which equals `finish_ev` here — no sprint/GC/jersey/KOM components for forward stages).

**S17-γ revert (2026-05-13):** forward intel consumption deleted. `INTEL_MULT` only applies to current-stage `build_probabilities`, not forward.

---

## 5. Forward-stage handling

**Two layers:**

**Layer 1 — `build_forward_probabilities`** (line 857): builds the probability distribution for forward stages. Slider-only (no odds/intel input). Called for both n+1 and n+2 with respective slider configurations.

**Layer 2 — `estimate_forward_costs`** (line 983): computes the TRANSFER COSTS for hypothetical optimal n+1 and n+2 rosters.

```python
team_n1 = fast_optimize(candidates, probs_n1, ...)   # in-vacuum optimal for n+1
team_n2 = fast_optimize(candidates, probs_n2, ...)   # in-vacuum optimal for n+2
cost_n1 = compute_transfer_cost(current_team, team_n1)
cost_n2 = compute_transfer_cost(team_n1, team_n2)    # chained: n+1 → n+2
```

**Forward-stage handling does NOT include forward EV** — only forward transfer costs feed back into the optimizer. The "two-stage lookahead" is "cost-of-keeping-options-open through n+2," not "EV-over-three-stages."

This is a known architectural property: lookahead's value-of-information for forward stages is bounded by transfer cost (operations expense) rather than expected fantasy points across multiple stages. Per S17-γ revert: per-rider intel consumption requires a bookmaker distribution which only exists current-stage.

---

## 6. Scoring component decomposition

| Component | compute_team_ev | simulate_stage | fast_optimize | build_probabilities |
|---|---|---|---|---|
| **Finish points** | `Σ finish_ev` per rider (finish_probs × FINISH_POINTS marginal) | PL-sampled per-position points (joint, mutual-exclusivity respected) | Same as compute_team_ev | Source of `finish_ev` and `finish_probs` |
| **Sprint points** | `Σ sprint_ev` per rider (from add_stage_evs) | Position-based MC lookup (sprint_kr table) | Same as compute_team_ev | Source of `sprint_ev` via add_stage_evs |
| **GC bonus** | `Σ gc_ev` per rider | Position-based MC lookup (GC_BONUS table) | Same as compute_team_ev | Source of `gc_ev` via add_stage_evs (Sub-B2 standings-aware for top-10 GC) |
| **Jersey bonus** | `Σ jersey_ev` per rider (= win_prob × JERSEY_BONUS) | Position-based (only the winner gets it) | Same | Source of `jersey_ev` via add_stage_evs |
| **KOM points** | `Σ kom_ev` per rider (finish position as proxy for climb position) | Same proxy in MC (per-climb category lookup) | Same | Source of `kom_ev` via add_stage_evs |
| **Captain bonus** | `max(total_evs)` — doubling the highest-EV rider | `max(rider_totals[:, capt_ti], 0)` in PL sample — doubles captain's actual sampled points | Same captain-bonus logic as compute_team_ev | (not relevant) |
| **Team bonus** | `compute_team_bonus_ev` (win/p2/p3 marginals × bonus per top-3 position) | `(top_3_real_team == roster_real_team)` × TEAM_BONUS_MAP[pos] — joint in MC | Same as compute_team_ev | Source of `p2`, `p3` via finish_probs |
| **Depth bonus** | `DEPTH_BONUS[min(8, round(sum(top15)))]` — round of marginal sum | `DEPTH_BONUS[count of team in top 15]` per MC sample — joint counts | Same as compute_team_ev | Source of `top15` |
| **Transfer cost** | NOT included | NOT included | NOT included | NOT applicable |

**Mutual-exclusivity asymmetry analysis per component:**
- **Finish/Sprint/GC/KOM:** position-based scoring tables. Marginal sum allows two team riders to both "be 1st" with combined probability >100% conceptually; MC correctly assigns exactly one rider per position. **Affected.**
- **Jersey:** computed from `win_prob` only (per-rider). Naturally bounded; both metrics equivalent here.
- **Captain:** compute_team_ev doubles the rider with max `total_ev` (deterministic given team). simulate_stage doubles the chosen captain's actual MC sampled points. **Slight difference**: under joint sampling, captain's expected doubled points may differ from `2× total_ev` due to MC-specific captain-position interaction.
- **Team-pairs:** compute_team_ev sums marginal win/p2/p3 probabilities; simulate_stage uses joint event "real team in top 3." **Slightly different** — joint case correctly handles overlapping team participation.
- **Depth:** compute_team_ev uses `round(sum(top15))` which is independence-assuming. simulate_stage counts actual top-15 finishers per sim. **Substantially affected** — overlap between team riders' top-15 chances inflates compute_team_ev's count.
- **Transfer cost:** independent of which EV function; added post-EV in `compute_objective` for lookahead.

**Bug-bounded-or-broad assessment:** the bug is BROAD across position-based components (finish, sprint, GC, KOM, depth, team-pairs). It is bounded-out for jersey (per-rider) and largely bounded-out for captain (per-rider doubling).

---

## 7. Captain-selection algorithm

**Function:** `select_captain(team_riders, all_probs)` at `optimizer.py:1844`.

```python
def select_captain(team_riders, all_probs):
    best_name, best_ev = None, -1.0
    for r in team_riders:
        name = r['name']
        ev = _ev_single(name, all_probs)   # = probs[name]['total_ev']
        if ev > best_ev:
            best_ev, best_name = ev, name
    return {'name': best_name, 'rationale': '...'}
```

**Algorithm:** scan the 8-rider roster, return the rider with the highest single-rider `total_ev` (which is the same `total_ev` computed in `add_stage_evs`).

**Where called from:**
- `generate_candidate_teams` line 1683 (POST-SA, after each chain's roster is determined)

**Captain decision timing:** POST-SA. The SA loop optimizes against `compute_objective` which uses `compute_team_ev`'s "captain bonus = max(total_evs)" — the captain is implicit in the objective (max gets doubled). After SA picks the final roster, `select_captain` re-derives WHICH rider is the captain.

**Captain bonus consistency:** `compute_team_ev`'s `max(total_evs)` IS the captain bonus during SA optimization; `select_captain`'s `max(total_ev)` POST-SA returns the SAME rider (both use `total_ev` precomputed from `add_stage_evs`). Then `simulate_stage` accepts the captain_name argument and doubles that rider's per-sim points.

**Under post-fix MC architecture:** if SA's objective changes to use simulate_stage (F1) or analytical-MC-corrected compute_team_ev (F2), captain decision logic likely needs to be re-examined:
- Under MC, the captain's contribution is `2 × E[captain_points]` where the captain's per-sample points include mutual-exclusivity effects (e.g., captain rarely captures full win_pts when team includes 4 other top-tier riders competing for the win).
- Current select_captain uses `total_ev` which is still independence-assuming.
- Probably want select_captain to use simulate_stage-derived per-rider expected points if F1 lands, OR analytical-MC-corrected per-rider EV if F2 lands.

---

## 8. Intel adjustment flow

**Application site:** `build_probabilities` at `optimizer.py:528-546`.

```python
adj = {}
if isinstance(intel, dict):
    src = intel.get('intel', intel)
    if isinstance(src, dict):
        for sig in src.get('key_signals', []):
            key  = (sig.get('direction', 'neutral'), sig.get('strength', 'weak'))
            mult = INTEL_MULT.get(key, 1.0)
            raw_rider = sig.get('rider')
            if raw_rider:
                matched = _match_rider(raw_rider, all_riders)
                adj[matched['name'] if matched else raw_rider] = mult

# Raw win probabilities (with intel multiplier baked in)
raw = {}
for r in all_riders:
    name = r['name']
    base = odds_map.get(name, 0.0)
    raw[name] = (base * adj.get(name, 1.0)) if base > 0 else EPS

# Renormalise
total = sum(raw.values())
for name in raw:
    raw[name] /= total
```

**`INTEL_MULT` table (line 107-113):**

| direction | strength | multiplier |
|---|---|---|
| up | strong | 1.20 |
| up | moderate | 1.10 |
| up | weak | 1.05 |
| down | weak | 0.95 |
| down | moderate | 0.85 |
| down | strong | 0.75 |

(neutral direction → 1.0; no entry → 1.0)

**Renormalization invariant:** total raw probability sums to 1.0 post-INTEL_MULT-application. Per-rider effective bump diluted when many riders receive multipliers.

**Pre-MC vs post-MC:** INTEL_MULT applies to `win` probability ONLY (at build_probabilities). Both `compute_team_ev` and `simulate_stage` consume the post-INTEL_MULT probabilities — INTEL_MULT is upstream of both EV functions. There's no separate "intel application after sampling" path.

**Top3/top10/top15 marginals: indirectly intel-adjusted.** They're derived from `win` (after the win is normalized including intel). So intel propagates through. But `gc_ev` and `jersey_ev` use `pw` (the normalized win) directly, so they ARE intel-affected. `kom_ev` uses `fp[i]` (finish_probs derived from top3/top10/top15) so ALSO intel-affected.

**`expert_stars` consumption:** NOT consumed by optimizer yet. Phase 1 substrate (`intel.expert_stars`) is present in `stage_N_intel.json` but build_probabilities reads `key_signals` only. Phase 3 migration replaces `INTEL_MULT[(direction,strength)]` lookup with `voting-power-α` weighted average over `expert_stars[rider][source]` mapped to tier multipliers.

**Renormalization invariant under Phase 3:** the per-bucket renormalization in `build_probabilities` (raw[name] /= total) is a property of "multiply all riders' win by some factor, then renormalize to 1." Phase 3 swaps the multiplier source (table lookup → weighted tier) but preserves the consumption pattern. Renormalization invariant unchanged.

---

## 9. Transfer cost handling

**Function:** `compute_transfer_cost(current_team, target_team, probs_next=None)` at `optimizer.py:830`.

```python
current_names = {r['name'] for r in current_team}
buys = [r for r in target_team if r['name'] not in current_names]
cost = sum(r['price'] * TRANSFER_COST_RATE for r in buys)    # 0.01 = 1% of buy price
if probs_next:
    for r in current_team:
        if probs_next[r['name']]['gc_penalty']:
            cost += 50_000
return cost
```

**Per-rider cost:** 1% of buy price (Holdet's actual transfer-fee rule). Only NEW riders (not already in current_team) incur fees — keeping a rider has zero fee.

**Per-strategy weighting (in `compute_objective`):**

| Strategy | tc_current | tc_n1 | tc_n2 | Notes |
|---|---|---|---|---|
| Optimal | NOT applied | NOT applied | NOT applied | Pure stage EV. SA ignores transfer cost. **Display Net EV post-SA subtracts tc_current.** |
| Depth | NOT applied | NOT applied | NOT applied | Same as Optimal. |
| Lookahead | × 1.0 | × 1.0 | × 0.7 (LOOKAHEAD_DISCOUNT) | Two-stage forward-cost-aware. |

**This is operationally load-bearing for the Stage 9 finding:** Optimal/Depth don't reward keeping Vingegaard (zero current-stage transfer cost not a feature of their SA objective). Lookahead rewards keeping Vingegaard (current-team rider → 0 in tc_current contribution).

**Display Net EV computation** (line 1800):
```python
transfer_cost = compute_transfer_cost(current_team or [], team)
ev_net = ev_estimate - transfer_cost
```

So even Optimal's displayed Net EV subtracts tc_current — but SA didn't optimize against it. Optimal's SA picks the team with highest compute_team_ev; the resulting transfer cost is incidental.

---

## 10. Sliders and race-type adjustments

**Slider distribution:** 5 buckets per stage horizon (n+1, n+2, n+3): `bunch_sprint`, `reduced_sprint`, `breakaway`, `gc`, `time_trial`.

**SCENARIO_TO_TERRAIN map (line 848-854):**

```python
SCENARIO_TO_TERRAIN = {
    'bunch_sprint':   {'sprint': 1.0},
    'reduced_sprint': {'sprint': 0.5, 'mixed': 0.5},
    'breakaway':      {'mixed': 1.0},
    'gc':             {'climbing': 1.0},
    'time_trial':     {'time_trial': 1.0},
}
```

**Current-stage application** (`build_probabilities` line 591-649, gated by `use_race_type` tickbox; default OFF):

```python
s = {k: sliders[k] / 100.0 for k in slider_buckets}
if not uniform:
    for rider:
        scenario_score = Σ_bucket weight × Σ_dim SCENARIO_TO_TERRAIN[bucket][dim] × ta[dim]
        baseline       = same with uniform weights = 1/5 = 0.20
        mult = clamp(scenario_score / baseline, 0.6, 1.5)
    for each bucket in (win, top3, top10, top15):
        pre_sum = Σ riders[bucket]
        apply mult per rider
        renormalize to pre_sum (per-bucket preservation)
```

Per-bucket renormalization preserves total mass per bucket (no bookmaker-overround compression).

**Forward-stage application** (`build_forward_probabilities` line 873-922): sliders × SCENARIO_TO_TERRAIN × terrain_affinity is the ONLY signal (no odds, no intel). Pure synthetic distribution.

**Forward sliders affect forward probs differently than current sliders affect current probs:** forward has no bookmaker baseline; sliders × terrain compose directly into win prob. Current has bookmaker baseline; sliders × terrain modify the baseline (race-type adjustment).

---

## 11. Determinism properties (S17-10 verified)

**S17-10 fix landed 2026-05-15** (commit `159bfed`): wall-clock-determinism. `time.time()` early-termination removed from `simulated_annealing` (line 1372 pre-fix) and `fast_optimize` (line 945, 949 pre-fix). Chain length now deterministic given seed payload.

**Canonical termination bound:** `n_iter = 200_000` for SA, `for _ in range(10_000)` for fast_optimize. `max_seconds` parameter retained in SA signature as deprecated-but-accepted (no behavioural effect post-S17-10).

**Seed handling:** `compute_seed(stage, sliders, force_in, force_out, use_race_type_adjustment)` at `optimizer.py:53` — hashes inputs to 64-bit int. Per-strategy XOR sub-seeds (`base_seed ^ (strategy_xor << 8) ^ chain_xor`). Forward proxy sub-seeds: `base_seed ^ 0xA` (n+1), `base_seed ^ 0xB` (n+2). Eval sub-seed for shared simulate_stage: `base_seed ^ 0xF`.

**Tier A conditional-exclusion (S17-2 fix, line 67-69):** under `use_race_type_adjustment=False`, `n1` sliders are dropped from the hash payload because they don't affect output (race-type adjustment block gated OFF). Prevents seed-state-leak across search-equivalent inputs.

**Sample matrix determinism:** simulate_stage uses `rng = np.random.default_rng(seed)`; deterministic given seed. If a future fix lands cached-sampling (F1), the sample matrix would be deterministic per stage + seed. Verified architectural property.

**V4a canonical assertion shape:** byte-identical pre/post-fix when seed payload + intel substrate match. Per CLAUDE_SESSION reasoning pattern, capture intel.json SHA alongside optimizer output SHA across the comparison window — substrate-shift drift (external `/gather-intel` fires) needs disambiguation.

---

## 12. Surprises and architectural concerns

**Surprise 1 — `_compute_objective` at `optimizer.py:812` is dead code in production.** Function exists, takes (team, probs, objective), returns ev/depth-weighted. But `simulated_annealing` calls the OTHER `compute_objective` at line 1023 (line 1362, 1430). `_compute_objective` is only called by `_compute_objective` itself recursively? Actually no — grepping confirms `_compute_objective` is never called from outside its own definition. **Architectural cruft.** Future cleanup item.

**Surprise 2 — Optimal/Depth ignore transfer cost in SA objective.** They optimize pure compute_team_ev with no transfer-cost subtraction. Displayed Net EV subtracts tc_current. This means: an Optimal roster with 6 transfers (411k cost) could score worse on displayed Net EV than an alternative 0-transfer roster with slightly lower compute_team_ev. **SA doesn't see this trade-off** unless the strategy is lookahead. Worth flagging — operationally, users may expect Optimal to balance EV against cost. Architectural design choice surface.

**Surprise 3 — `simulate_stage` uses ONLY `win` probability from build_probabilities.** Plackett-Luce sampling derives all positions from per-rider `win`. The top3/top10/top15 marginals from build_probabilities are NOT consumed by simulate_stage (only consumed by compute_team_ev/add_stage_evs paths). Means: market-paste top3/top10 odds (S17-29) influence compute_team_ev's `total_ev` substantially but influence simulate_stage only indirectly via the win-prob renormalization. **Two EV functions disagree on what counts as "intel input."**

**Surprise 4 — `add_stage_evs` Sub-B2 path overrides bookmaker-derived gc_ev/jersey_ev for top-10 GC riders.** Operationally important — Vingegaard's gc_ev on Stage 9 is from Sub-B2 retention curves, not from bookmaker top-10 odds. This makes Vingegaard's `total_ev` (and thus his weight in compute_team_ev / select_captain) Sub-B2-dependent. Sub-B2 is well-calibrated for GC retention but **does NOT** propagate through simulate_stage (which uses GC_BONUS lookup on PL-sampled position). Means: compute_team_ev's Vingegaard `gc_ev` (Sub-B2-aware) ≠ simulate_stage's gc_pts (position-based from joint PL sample). **Two EV functions disagree on GC bonus computation method too**, not just on mutual exclusivity.

**Surprise 5 — Captain rationale string at line 1857-1860 says "(~Xk doubled as captain)".** The captain contribution under compute_team_ev is `max(total_evs)`, which ADDS one extra copy of the captain's total_ev (so the rider contributes 2× total_ev). Under simulate_stage it's `max(cap_total, 0)` per sim, which doubles the per-sample positive points. Both effectively double. But the doubling-of-what is structurally different (marginal total_ev vs joint per-sample points). Rationale string is approximation.

**Surprise 6 — `compute_team_bonus_ev` uses `win`/`p2`/`p3` marginals.** Team bonus EV computation: for each pair of teammates in roster, sum `trigger.win × 60k + trigger.p2 × 30k + trigger.p3 × 20k`. Independence-assuming — assumes the trigger rider's marginal probability of finishing 1st/2nd/3rd is uncorrelated with whether the partner is also in the top 3. In reality joint events matter. simulate_stage handles this correctly via TEAM_BONUS_MAP[position] × (real-team match in top-3 slots).

**Surprise 7 — Lookahead's `look_obj` for cross-chain selection ≠ `compute_objective`.** SA optimizes `compute_objective(..., objective='lookahead')` which uses `compute_team_ev` as base_ev. Cross-chain selection (line 1719-1727) recomputes `look_obj = ev - tc_current - tc_n1 - 0.7 × tc_n2` where `ev` is the simulate_stage `mean` (joint-sample). **Internal SA objective and cross-chain selection metric use different EV functions.** Per S17-ζ-fix (c) this was intentional — the user-facing transfer-adj EV uses simulate_stage. But it means SA may converge to one basin (compute_team_ev best) and cross-chain selection may prefer a different basin (look_obj best with simulate_stage EV). Quietly architectural.

---

## 13. Call-site index

### `compute_team_ev` callers
| Line | Function | Context |
|---|---|---|
| 819 | `_compute_objective` | Dead-code utility (no external callers) |
| 943 | `fast_optimize` | Initial team EV for forward-stage proxy SA |
| 972 | `fast_optimize` | Inner SA loop for forward-stage proxy |
| 1031 | `compute_objective` | Main SA objective — base_ev for all 3 strategies |
| 1449 | `simulated_annealing` | Post-SA "true analytical EV" for chain diagnostics |

### `simulate_stage` callers
| Line | Function | Context |
|---|---|---|
| 1687 | `generate_candidate_teams` | Per-chain post-SA evaluation → produces displayed Net EV |
| server.py:1959 | `simulate_stage` (separate `/simulate-stage` endpoint?) | Dashboard-direct simulation |

### `fast_optimize` callers
| Line | Function | Context |
|---|---|---|
| 990 | `estimate_forward_costs` | n+1 forward-stage proxy |
| 991 | `estimate_forward_costs` | n+2 forward-stage proxy |
| 1552 | `generate_candidate_teams` | Initial current_team proxy when None |

### `build_probabilities` callers
| Line | Function | Context |
|---|---|---|
| server.py:740 | `run_optimizer_py` | `/run-optimizer` endpoint — current-stage probs |
| server.py:1931 | `simulate_stage_endpoint` | `/simulate-stage` endpoint |

### `simulated_annealing` callers
| Line | Function | Context |
|---|---|---|
| 1661 | `generate_candidate_teams` | Per-chain × per-strategy SA invocation (10 chains × 3 strategies = 30 calls per `/run-optimizer`) |

### `select_captain` callers
| Line | Function | Context |
|---|---|---|
| 1683 | `generate_candidate_teams` | Post-SA, before simulate_stage |
| server.py:34 | (import only) | server.py imports the symbol |
| server.py:1939 | `simulate_stage_endpoint` | Captain resolution for direct simulation |

### `compute_transfer_cost` callers
| Line | Function | Context |
|---|---|---|
| 763 | `is_valid` | Constraint check — budget includes transfer fees |
| 993 | `estimate_forward_costs` | cost_n1 for forward proxy |
| 994 | `estimate_forward_costs` | cost_n2 for forward proxy |
| 1057 | `compute_objective` | Lookahead tc_current |
| 1058 | `compute_objective` | Lookahead tc_n1 |
| 1059 | `compute_objective` | Lookahead tc_n2 |
| 1722 | `generate_candidate_teams` (lookahead branch) | Cross-chain look_obj tc_current |
| 1723 | `generate_candidate_teams` (lookahead branch) | Cross-chain look_obj tc_n1 |
| 1724 | `generate_candidate_teams` (lookahead branch) | Cross-chain look_obj tc_n2 |
| 1791 | `generate_candidate_teams` (result assembly) | Display: actual cost_n1 for "forward" breakdown |
| 1792 | `generate_candidate_teams` (result assembly) | Display: actual cost_n2 for "forward" breakdown |
| 1800 | `generate_candidate_teams` (result assembly) | Display: ev_net = ev_estimate - transfer_cost |

### `add_stage_evs` callers
| Line | Function | Context |
|---|---|---|
| 688 | `build_probabilities` | Internal — annotates per-rider EV components after raw probs computed |

(`add_stage_evs` is internal to build_probabilities; not a public API.)

### `compute_team_bonus_ev` callers
| Line | Function | Context |
|---|---|---|
| 734 | `compute_team_ev` | Team-pairs bonus component |

(Single caller — coupled tightly to compute_team_ev.)

### `compute_objective` callers
| Line | Function | Context |
|---|---|---|
| 1362 | `simulated_annealing` | Initial team objective score |
| 1430 | `simulated_annealing` | Inner SA loop proposal evaluation |

### `build_forward_probabilities` callers
| Line | Function | Context |
|---|---|---|
| server.py:752 | `run_optimizer_py` | probs_n1 for `/run-optimizer` |
| server.py:753 | `run_optimizer_py` | probs_n2 for `/run-optimizer` |

---

## Appendix — Fix-shape implications based on this audit

The user-surfaced bug is **structurally confirmed**: SA optimizes `compute_team_ev` (independence-assuming marginal sum); displayed Net EV uses `simulate_stage` (Plackett-Luce joint MC). On Stage 9 substrate these rank rosters oppositely.

Three previously-sketched fix shapes re-evaluated against this audit:

**F1 — Cached-sampling MC in SA:** replace `compute_team_ev` with `simulate_stage` in SA loop. Audit confirms `simulate_stage` covers ALL scoring components MC-aware. But Section 6 surfaces that:
- simulate_stage uses ONLY `win` probability; top3/top10 market odds (S17-29 substrate) wouldn't feed in.
- Sub-B2 standings-aware gc_ev/jersey_ev are NOT in simulate_stage (which uses GC_BONUS position lookup).
- **F1 would lose the Sub-B2 retention path and the market-paste top3/top10 input** unless simulate_stage is refactored to consume those alongside.

**F2 — Analytical correction to compute_team_ev:** add mutual-exclusivity terms. Audit shows the bug is BROAD across position-based components (finish/sprint/GC/KOM/depth/team-pairs). Each requires its own correction term. Most tractable for depth bonus (`1 - prod(1 - p_top15)` replaces `sum(p_top15)`). Less tractable for FINISH_POINTS where 15 positions have different point values and Plackett-Luce joint dist has no closed-form per-position marginal.

**F3 — Lazy hybrid:** SA uses compute_team_ev for exploration, switches to simulate_stage for convergence. Plausible. Same Sub-B2/market-odds concern as F1.

**Audit-driven new direction (F4) — extend simulate_stage to consume Sub-B2 gc_ev and market top3/top10 directly.** Then F1 becomes architecturally clean: simulate_stage covers ALL paths uniformly.

**Recommendation for next handoff:** the audit surfaces that the bug+fix architecture is broader than just "compute_team_ev vs simulate_stage." Phase 3 INTEL_MULT migration, Sub-B2 path integration, market-top3/top10 simulate_stage consumption, captain-bonus rederivation under MC are all candidate scope. Right next handoff is **fix-shape decision under substrate-anchored scope**, not implementation. Suggested deliverable: a substrate-anchored fix-shape proposal that picks F1/F2/F3/F4 explicitly and enumerates downstream implications per architectural concern surfaced in Section 12 above.
