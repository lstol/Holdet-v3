# S17-EV-FIX Migration Plan

*Created 2026-05-18, anchored to S17-OPT-AUDIT (commit `86445b1` on main) + S17-EV-FIX planning rollup (commit landing this document).*

**Status:** ⏳ Phase 1 entering execution. Phases 2–5 drafted but not yet sub-handoffed.

**Maintenance:** this document is the durable reference for the migration arc. Update in place as phases close (record landed shape, surprises, scope shifts). Future sub-handoffs anchor here rather than re-deriving from S17-OPT-AUDIT.

---

## 1. Migration goal and rationale

**Goal.** Single coherent migration closing the 5-axis `compute_team_ev` ↔ `simulate_stage` divergence surfaced by S17-OPT-AUDIT (Surprises #3, #4, #5, #6, plus the foundational mutual-exclusivity asymmetry per [audit Section 6](optimizer_architecture_map.md)). End state:

- **Unified MC objective on SA loop.** All three strategies optimize against a substrate-aligned `simulate_stage` (cached-sampling architecture), not `compute_team_ev`.
- **Substrate-aligned `simulate_stage` inputs.** Market top3/top10 marginals from `build_probabilities` consumed via hybrid Plackett-Luce sampling (Phase 1). Sub-B2 standings-aware gc_ev/jersey_ev consumed via per-position retention override (Phase 2).
- **Risk-stratified strategy reshape.** Three cards become p30 / EV-median / p70 percentile of the MC outcome distribution (Phase 5) — replacing the current `optimal`/`depth`/`lookahead` framing whose roster differentiation is currently near-zero on real substrate (per audit Section 11 + per-rider EV diagnostic Stage 9 finding).

**Rationale anchored in audit findings:**

- **5-axis divergence between `compute_team_ev` and `simulate_stage`** (audit Section 6 + Section 12):
  1. **Mutual exclusivity** — marginal sum allows two team riders to both "be 1st" with combined probability >100% conceptually; MC correctly assigns exactly one rider per position. Affects finish/sprint/GC/KOM/depth components.
  2. **Market top3/top10 input** (audit Surprise #3) — `simulate_stage` uses ONLY `win` per rider; market top3/top10 marginals from `build_probabilities` are not consumed.
  3. **Sub-B2 standings-aware retention** (audit Surprise #4) — `compute_team_ev` consumes Sub-B2-overridden gc_ev for top-10 GC riders; `simulate_stage` uses position-based `GC_BONUS[team_pos+1]` lookup on the PL sample. Vingegaard's GC bonus reads from two different sources between the two functions.
  4. **Team-pairs bonus** (audit Surprise #6) — `compute_team_bonus_ev` uses independence-assuming `win`/`p2`/`p3` marginals; `simulate_stage` uses joint event "real team in top 3."
  5. **Captain doubling** (audit Surprise #5) — `compute_team_ev` doubles `max(total_evs)` (marginal); `simulate_stage` doubles the chosen captain's per-sample positive points (joint).

- **Naive cached-sampling would regress market signal and Sub-B2 retention.** Phase 1+2 must land before Phase 3 swaps the SA objective, else the substrate-aligned signal that's currently in `compute_team_ev`'s per-rider `total_ev` (via `build_probabilities` + Sub-B2 path) disappears from the optimizer's view.

- **p30/EV/p70 reshape requires unified MC substrate; impossible under analytical correction.** F2-family fix shapes (analytical correction terms added to `compute_team_ev`) preserve the closed-form structure but cannot produce a percentile aggregation across simulated outcomes. Risk-stratified strategies need a sample matrix.

- **Audit-confirmed Option A direction.** User-confirmed at S17-OPT-AUDIT handoff closure. Alternative shapes (F2 analytical, F3 lazy hybrid) preserved in audit Appendix for reference; not pursued in this migration.

---

## 2. Sub-phase decomposition

### Phase 1 — `simulate_stage` market top3/top10 input alignment

**Scope.** Extend `simulate_stage` to consume market top3/top10 marginals alongside win-only PL sampling. Hybrid PL: riders with market top3/top10 data sample from a constrained distribution honoring their win/top3/top10 marginals (Pass 1); riders without market data sample from PL using win-only marginal into remaining positions (Pass 2). Position mutual-exclusivity preserved across passes.

**Closes:** audit Surprise #3.

**Prerequisites:** S17-OPT-AUDIT landed (✅ commit `86445b1`).

**Dependencies:** None upstream within this arc.

**Estimated time:** ~2-3 days Claude Code.

**Verification target:** market signal recoverable from samples (post-fix top3 fraction ≈ market top3 marginal within MC variance ~0.5-1% at n_sims=10000); mutual exclusivity preserved; scoring-component breakdown documented pre/post on current Giro stage substrate.

**Out of scope for Phase 1:** Sub-B2 integration (Phase 2); SA objective swap (Phase 3); captain/team-bonus MC migration (Phase 4); strategy reshape (Phase 5); `compute_team_ev` modifications (Phase 1 only touches `simulate_stage`).

---

### Phase 2 — Sub-B2 standings-aware retention integration

**Scope.** Wire Sub-B2's `gc_ev`/`jersey_ev` standings-aware path into `simulate_stage` MC sampling. Currently Sub-B2's retention curve produces overridden `gc_ev` in `add_stage_evs` (consumed by `compute_team_ev`), but `simulate_stage` bypasses it via direct `GC_BONUS[team_pos+1]` lookup. Two architectural design options:

- **(a) Position-bucket override.** When a top-10 GC rider lands in a position bucket, override the `GC_BONUS` lookup with the Sub-B2 retention-curve gc_ev (pre-computed in `build_probabilities`). Requires mapping retention probabilities to per-position GC bonus deltas.
- **(b) In-flight override.** Per-sample, check if a roster rider is a top-10 GC rider and apply the retention-curve override to that sim's GC bonus. More flexible but more compute per sim.

Design choice deferred to Phase 2 drafting; Phase 1's hybrid PL shape may make (a) or (b) more natural.

**Closes:** audit Surprise #4.

**Prerequisites:** Phase 1 landed (substrate-aligned `simulate_stage`).

**Dependencies:** Phase 1's hybrid PL output shape shapes Phase 2's integration approach.

**Estimated time:** ~1-2 days Claude Code.

**Verification target:** `simulate_stage`'s GC bonus output matches `compute_team_ev`'s `gc_ev` sum for top-10 GC riders (Vingegaard et al.) within MC variance; non-GC-top-10 riders unchanged from Phase 1.

---

### Phase 3 — Cached-sampling SA objective replacement

**Scope.** Replace `compute_team_ev` in SA's `compute_objective` (optimizer.py:1023) with vectorized cached MC sampling against substrate-aligned `simulate_stage` (Phases 1+2). Architecture:

- **Sample once per SA chain.** Pre-compute a sample matrix (n_sims × n_field rider positions) at SA-chain start, seeded from chain seed.
- **Per-iteration cost amortized.** Each candidate team's EV becomes a vectorized lookup against the cached sample matrix (team_pos indexing + per-component point sum), not a re-sample.
- **`n_iter` recalibration.** If per-iteration cost shifts materially, may need to lower `n_iter` while preserving SA convergence quality. Audit-projected ~10 min wall-clock per SA chain (1.7M ops/call × 200k iter); measure actual.

**Closes:** audit's foundational mutual-exclusivity asymmetry (Section 6); SA objective becomes the same MC formulation as the displayed Net EV.

**Prerequisites:** Phase 1 + Phase 2 landed.

**Dependencies:** Phase 2's `simulate_stage` shape (substrate-aligned, Sub-B2 integrated) is the substrate for Phase 3's cached sampling.

**Estimated time:** ~2-3 days Claude Code.

**Verification target:** three-card-convergence on current Giro stage substrate (SA objective EV ≈ displayed Net EV within MC variance for all three strategies); runtime measured; corroboration metadata stable (best_seen ≈ best_corroborated for converging strategies).

---

### Phase 4 — `select_captain` + `compute_team_bonus_ev` MC-aware migration

**Scope.** Both consume the Phase 3 cached sample matrix:

- **`select_captain`.** Current implementation at `optimizer.py:1844` returns `argmax(total_ev)` over roster (marginal). Post-Phase-4: return `argmax` of joint expected-captain-bonus from the sample matrix (per-rider expected positive sampled points, doubled).
- **`compute_team_bonus_ev`.** Current implementation at `optimizer.py:734` sums marginal win/p2/p3 probabilities × bonus per top-3 position. Post-Phase-4: derived from the sample matrix as the per-sim "real-team-in-top-3" joint event count × `TEAM_BONUS_MAP[position]`, averaged over sims.

**Closes:** audit Surprises #5 (captain doubling), #6 (team-pairs).

**Prerequisites:** Phase 3 landed (sample matrix available in SA loop).

**Dependencies:** Phase 3's sample matrix shape is the substrate.

**Estimated time:** ~0.5-1 day Claude Code.

**Verification target:** captain selection robust under MC (same captain across chains for high-confidence cases; differentiated for marginal cases); team-pair bonus consistent with `simulate_stage`'s team_bonus output for the same roster.

---

### Phase 5 — p30/EV/p70 aggregation parametrization + strategy reshape

**Scope.** Three architectural shifts:

- **Aggregation parametrization.** SA objective post-Phase-3 returns the mean of the sample matrix. Phase 5 parameterizes the aggregation: p30 (risk-averse), median (EV-anchored), p70 (upside-seeking). The three strategies optimize against different percentile aggregations of the same MC outcome distribution.
- **Strategy rename.** `optimal`/`depth`/`lookahead` → risk-stratified names (e.g., `risk_averse_p30` / `ev_median` / `upside_p70`). Display strings, dashboard cards, prompt-build paths all updated.
- **Genuine roster differentiation.** Current `optimal`/`depth` produce nearly-identical SA basins per audit Section 11 + per-rider EV diagnostic finding; risk percentile produces meaningfully different rosters (high-variance riders shift across percentile choices). Empirical verification on remaining Giro stages.

**Closes:** the strategy-card-differentiation gap.

**Prerequisites:** Phase 3 landed (cached sample matrix); Phase 4 landed (captain/team-bonus MC consistency).

**Dependencies:** Phase 3's sample matrix; Phase 4's aggregation correctness.

**Estimated time:** ~1-2 days Claude Code.

**Verification target:** three strategies produce differentiated rosters by risk percentile (cross-strategy roster diff ≥ 2-3 riders typical on real substrate); dashboard updated; existing `lookahead`-specific cross-chain selection (look_obj at `optimizer.py:1208`) reconciled with the new aggregation.

---

## 3. Dependencies between sub-phases

```
                    S17-OPT-AUDIT (✅ commit 86445b1)
                              │
                              ▼
                     ┌─────────────────┐
                     │  Phase 1        │
                     │  market top3/   │
                     │  top10 hybrid   │
                     │  PL             │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │  Phase 2        │
                     │  Sub-B2         │
                     │  retention      │
                     │  integration    │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │  Phase 3        │
                     │  Cached-sampling│
                     │  SA objective   │
                     └────────┬────────┘
                              │
                              ▼
              ┌───────────────┴────────────────┐
              ▼                                ▼
     ┌────────────────┐              ┌────────────────┐
     │  Phase 4       │              │  Phase 5       │
     │  Captain +     │              │  p30/EV/p70    │
     │  team-bonus    │              │  reshape       │
     │  MC migration  │              │                │
     └────────────────┘              └────────────────┘
```

**Strict sequencing rationale.** Phases 1 → 2 → 3 are linear (each shapes the next's substrate). Phases 4 and 5 can in principle be parallelized after Phase 3, but the project rule (no parallelization across sub-handoffs) keeps them strictly sequential too — Phase 4 lands before Phase 5 because Phase 5's risk-stratified aggregation should consume Phase 4's MC-consistent captain selection.

---

## 4. Verification targets per phase

| Phase | Primary verification | Secondary | Operational impact characterization |
|---|---|---|---|
| **Phase 1** | Market top3/top10 marginals recoverable from samples (top3 fraction ≈ market top3 within MC variance for canary riders e.g. Vingegaard) | Mutual exclusivity preserved (every sample has exactly N riders in top-N); scoring-component breakdown documented pre/post; runtime within 2× pre-Phase-1 | Lookahead's displayed Net EV shifts post-Phase-1; capture pre/post diff on current substrate |
| **Phase 2** | `simulate_stage` GC bonus matches `compute_team_ev` `gc_ev` sum for top-10 GC riders (Vingegaard et al.) | Non-GC-top-10 riders unchanged from Phase 1; Sub-B2 retention curve activation traceable in MC output | All three strategies' displayed Net EV shifts; characterize on current substrate |
| **Phase 3** | Three-card-convergence on current substrate (SA objective EV ≈ displayed Net EV per strategy within MC variance) | Runtime measured against audit projection; corroboration metadata stable; bit-identical re-run given same seed | Optimal/Depth recommendations shift materially; first stage where SA sees the unified MC objective |
| **Phase 4** | Captain selection robust under MC (high-confidence cases stable; marginal cases differentiated by joint vs marginal expectation) | Team-pair bonus matches `simulate_stage`'s team_bonus for same roster | Captain choices may shift on stages with non-trivial team-pair dynamics |
| **Phase 5** | Three strategies produce differentiated rosters by risk percentile (cross-strategy diff ≥ 2-3 riders typical) | Dashboard renders new strategy names; lookahead's look_obj path reconciled or retired | Strategy framework reshape — operator workflow shifts |

**Substrate-time-skew capture across all phases.** Each verification captures input intel SHA alongside output optimizer SHA per V4a canonical assertion shape (per CLAUDE_SESSION reasoning patterns). Distinguishes phase code drift from substrate-shift between verification runs.

---

## 5. Operational discipline during migration

**Lookahead remains trustworthy through Phase 3.** Current operational pattern: Lookahead's two-stage forward-cost-aware objective produces aligned recommendations with displayed Net EV (incidentally — per audit Section 3.3 — because it includes current_team riders at zero transfer cost, not because of any MC-awareness). Optimal/Depth continue producing biased recommendations until Phase 3 lands.

**Recommendation:** for committed-team decisions during the migration window, use Lookahead's roster. Optimal/Depth informational only.

**Document at each sub-handoff close** to keep operational discipline aligned with technical state:
- Which strategies are trustworthy
- Which substrate-aligned inputs landed
- Any operational impact observed (e.g., captain stability shifts post-Phase-4)

**Rollback discipline.** Each sub-handoff merges to main only after V4 clean; pre-merge feature branch holds. If Phase N surfaces issues:
- Phases 1..N-1 stay landed and useful (substrate alignment is independently valuable for `simulate_stage`'s displayed Net EV correctness).
- Phase N's branch can be discarded without affecting earlier phase work.

**Substrate-time-skew V4a SHA-pair pattern (per CLAUDE_SESSION).** Capture input intel SHA alongside optimizer output SHA at every verification window. Distinguishes phase code drift from substrate-shift between runs. Especially important during migration because input substrate refreshes daily (intel scrapes, odds updates).

---

## 6. Empirical validation strategy

**Primary substrate during migration:** remaining Giro stages 10-21. Today is 2026-05-18; Stage 9 is the most recent operational stage. Stages 10-21 (~12 stages) provide:

- **Stage 10 ITT** (Viareggio → Massa, 42km) — first ITT post-migration; Sub-B2 ITT retention curves (Sub-B2-followup landed) validate in MC alongside.
- **Mountain stages** — Sub-B2 retention curves (Sub-B2-followup's hybrid-TT activation surface) validate in MC.
- **Sprint stages** — market top3/top10 marginals well-populated; Phase 1 hybrid PL validation substrate.
- **Mixed terrain** — captain-stability stress test for Phase 4.

**Earlier sub-phase landing = more validation substrate available.** If Phase 1 lands by Stage 12, Stages 13-21 provide 9 stages of empirical validation. If Phase 1 slips to Stage 16, only Stages 17-21 (5 stages) remain.

**T-6 backtest amplification.** Post-Giro, T-6 (backtest corrected optimizer against full Giro 2026) provides 21 stages of post-migration substrate for residual error budget characterization. Migration completion before Giro ends amplifies T-6 substrate quality.

**Empirical validation cadence:**
- After each sub-phase merge, re-run optimizer on the most recent 1-2 operational stages; document Net EV diff and recommendation diff.
- Validate against the previous stage's actual outcome where available (Sub-D-style replay).

---

## 7. Risks and contingencies

| Risk | Likelihood | Impact | Contingency |
|---|---|---|---|
| **Phase 1 hybrid PL math doesn't preserve mutual exclusivity** | Medium (Pass 1 algorithm design is load-bearing) | High (foundational invariant violated; algorithm needs redesign) | Pre-implementation user-direction checkpoint (Phase 1 surfaces 2-3 candidate Pass 1 algorithms; user picks one before implementation). V4c verification catches violation pre-merge. |
| **Phase 1 hybrid PL math correctness — joint distribution preservation** | Medium | Medium (per-rider top3 marginal recoverable but joint distribution may distort) | V4b verification recovers market marginals from samples; if joint distortion surfaces, revisit Pass 1 algorithm choice. |
| **Phase 2 Sub-B2 integration design choice (position-bucket vs in-flight override)** | Medium | Low-Medium (both shapes work; choice affects performance + maintainability) | Phase 2 drafting includes explicit design comparison; user direction on shape before implementation. |
| **Phase 3 cached-sampling runtime** | Medium | Medium (audit-projected ~10 min; if actual is materially worse, n_iter recalibration needed) | Phase 3's first verification step is a runtime measurement on current substrate. If >2× audit projection, surface for `n_iter` recalibration discussion before merging. |
| **Phase 3 SA convergence quality under cached sampling** | Low-Medium | Medium (cached sample variance may produce convergence stalls) | Three-card-convergence verification gates Phase 3 merge. Multi-start corroboration metadata (S17-22 infrastructure) detects per-strategy convergence regressions. |
| **Phase 5 dashboard impact** | Low | Low (cosmetic + display logic; no math) | Phase 5 drafting includes dashboard mockup before implementation. |
| **Phase 5 lookahead-specific look_obj path conflict** | Medium | Low-Medium (look_obj cross-chain selection was added by S17-ζ-fix (c); reconciliation needed with risk-percentile aggregation) | Phase 5 drafting explicitly reconciles look_obj with new aggregation. May retire look_obj if redundant under p70 aggregation. |
| **Operational disruption from intermediate state** | Low (each phase merges only after V4 clean) | Low (Lookahead remains trustworthy throughout) | Operational discipline section above; document at each sub-handoff close. |
| **Substrate drift during migration window** (daily intel scrapes + standings updates) | High (expected) | Low (substrate-time-skew SHA pair pattern handles) | Capture input intel SHA + output optimizer SHA at every verification per V4a canonical assertion shape. |

---

## 8. Reference: S17-OPT-AUDIT architecture map

This migration plan is anchored to the audit at [claude/diagnostics/optimizer_architecture_map.md](optimizer_architecture_map.md). Key audit sections referenced:

- **Section 1** — High-level flow (end-to-end optimizer pipeline)
- **Section 3** — SA objective per strategy (lookahead/optimal/depth all use `compute_team_ev`)
- **Section 4** — EV function shapes (`compute_team_ev`, `simulate_stage`, `fast_optimize`, `build_probabilities`, `build_forward_probabilities`)
- **Section 6** — Scoring component decomposition (the 5-axis divergence table)
- **Section 12** — Surprises and architectural concerns (Surprises #3, #4, #5, #6 directly addressed by this migration)
- **Section 13** — Call-site index (used for backward-compat caller verification at each sub-phase)
- **Appendix** — Fix-shape implications (F1/F2/F3/F4 trade-off; this migration is F4-aligned)

**Maintenance discipline:** when this migration plan updates per phase closure, also update the audit map's Section 12 to reflect surprises that have been closed (don't delete; mark with phase reference).

---

## 9. Reference: T-6 post-Giro alignment

**T-6 scope:** "Backtest corrected optimizer against full Giro 2026. Replay every stage with full S17-1 model + actual standings + corrected curves + seeded RNG."

**How this migration affects T-6 scope:**

- **Pre-migration T-6** would have backtested against `compute_team_ev`-based SA objective (the broken substrate). T-6's gap-to-optimal-in-hindsight measurement would conflate two error budgets: the SA-objective bug and the residual model error.
- **Post-migration T-6** isolates the residual error budget cleanly. SA objective is substrate-aligned MC; gap-to-optimal-in-hindsight measures only the model's intrinsic limitations (per-rider EV calibration, market signal extraction, etc.).

**Migration completion before Giro ends amplifies T-6 substrate quality.** Phase 5 landing by Stage 18 means T-6's full-Giro replay uses the migrated optimizer end-to-end. Phase 3 alone (without Phases 4/5) is enough for T-6's primary measurement; Phase 4 + 5 add captain/team-bonus correctness and strategy-card-differentiation insight.

**Cross-references:**
- T-6 is part of the post-Giro holistic optimizer review (S17-22-followup closure 2026-05-15).
- S18-1 mid-Giro INTEL_MULT calibration runs in parallel with this migration; the two are orthogonal (different layers — `build_probabilities` intel multiplier vs SA-objective architecture).
- Sub-B2 retention curves are validated under MC starting in Phase 2; Sub-D (multi-stage verification) uses post-Phase-2 substrate.

---

## Maintenance log

*(append phase closure notes here as the migration progresses; format: date + phase + landed shape + surprises)*

- **2026-05-18** — Planning document drafted. Phase 1 entering execution under same handoff.
