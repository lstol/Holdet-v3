# S17-ι Phase 2 — Tier-union biased-swap pool verification

**Date**: 2026-05-13  
**Substrate**: captured Stage 5 (`shared/data/tmp/s17z_repro_state/`), breakaway-80% sliders  
**Code under test**: `claude/engine/optimizer.py` after S17-ι Phase 1 deploy  
**Test scripts**: `/tmp/s17i_phase2_test_i_iii.py`, `/tmp/s17i_phase2_test_ii.py`, `/tmp/s17i_phase2_tier5_attrib.py`

## Falsifiable tests

All three pre-specified tests **PASS** on the captured Stage 5 substrate.

### Test (i) — Distinct basin count non-decreasing

10 SA lookahead chains per path, distinct roster SHAs:

| Path                          | Distinct basins | Sample basin                                       |
|-------------------------------|-----------------|----------------------------------------------------|
| Legacy (top-50 EV + S17-ζ-d)  | 1               | sha `fdc72d8836cf`, ev_est 1,140,115, cap Narvaez  |
| Tier-union (Phase 1)          | 1               | sha `fdc72d8836cf`, ev_est 1,140,115, cap Narvaez  |

**Verdict**: PASS (1 ≥ 1). Both paths converge to the same single basin under 5s × 10 chains.

### Test (ii) — Best-found Net EV non-decreasing across all 3 active strategies

| Strategy   | Legacy ev_net | Tier-union ev_net | Δ        |
|------------|---------------|-------------------|----------|
| optimal    | 728,597       | 728,597           | +0  ✓    |
| depth      | 728,597       | 728,597           | +0  ✓    |
| lookahead  | 753,485       | 753,485           | +0  ✓    |

_(low_transfer retired per S17-26; tested 3 strategies, not 4.)_

**Verdict**: PASS (all Δ ≥ 0). Tier-union is non-regressing.

### Test (iii) — Magnier-keep reachability guard

Paul Magnier is in the captured `current_team`; the known-bad basin where the optimizer keeps him as captain produces materially worse EV. Reachability count across 10 chains should remain at 0.

| Path        | Magnier-keep count |
|-------------|--------------------|
| Legacy      | 0 / 10             |
| Tier-union  | 0 / 10             |

**Verdict**: PASS. Neither path reaches the known-bad basin; tier-union does not introduce a new regression.

## Tier 5 attribution

Replayed `_tier5_team_bonus_fillers` against the substrate and categorised the per-favourite outcomes. |T1| = 37.

| Outcome                             | Count |
|-------------------------------------|-------|
| FRESH (T5 picks teammate not in T1–T4) | 23 |
| DEDUP (T5 picks teammate already in T1–T4) | 6 |
| SKIP — favourite has no terrain_affinity argmax | 3 |
| SKIP — no same-affinity teammate available | 5 |
| **SUM**                             | **37** ✓ |

- Distinct T5 picks: **22** (multiple favourites can pick the same teammate, e.g. both Engelhardt and Bouwman → Donaldson).
- Net new riders contributed by T5 to the T1–T4 union (size 50): **17**.
- Final pool size: 50 (T1∪T2∪T3∪T4) + 17 (T5 fresh) = **67**, matching the Phase 1 closure number.

### SKIP — no same-affinity teammate (5)

| Favourite                | Team               | Argmax       |
|--------------------------|--------------------|--------------|
| Alec Segaert             | Bahrain Victorious | time_trial   |
| Filippo Ganna            | Netcompany INEOS   | time_trial   |
| Filippo Zana             | Soudal Quick-Step  | climbing     |
| Jasper Stuyven           | Soudal Quick-Step  | sprint       |
| Tobias Lund Andresen     | Decathlon CMA CGM  | sprint       |

The two time-trial-argmax skips are expected (only ~3 TT-argmax riders in the active pool, none likely teammates). The other three reflect roster composition on these specific squads.

### SKIP — favourite has empty `terrain_affinity` (3)

- Gianmarco Garofoli
- Guillermo Thomas Silva
- **Jhonatan Manuel Narvaez Prado**

Notable: the captain in both paths' converged basin (Narvaez Prado) has an empty `terrain_affinity` dict. That is upstream-of-Phase-2 data quality; it has no impact on tier-union semantics since Narvaez is already added via T1 directly.

## Interpretation

**Pre-spec pass criterion met**: all three falsifiable tests pass, and Tier 5 attribution sums correctly with non-trivial net contribution (17/22 picks are fresh additions).

**Negative finding worth flagging**: on this substrate, tier-union and legacy paths produce **bit-identical results** across all 10 chains and all 3 strategies (same roster SHA `fdc72d8836cf`, same captain, same EV). This means:

1. The "+189k EV Stage 5 lookahead Net EV shift" reported in the Phase 1 closure (commit 467bee8) was **confounded**. The live server was not restarted between the name-matcher-hardening landing and Phase 1 deploy, so the "pre-deploy" baseline was running pre-matcher pre-Phase-1 code. The gain came from name-matcher canonicalisation lifting riders into Tier 1 (recall: matcher reduced Tier 1 false-missing from 8 → 0), not from tier-union biased-swap pool composition.
2. With breakaway-80% Stage-5 sliders, the basin landscape has a single dominant attractor that both pools converge to within 5s SA budget. Tier-union's 67-rider pool offers more swap targets than legacy's 50, but every additional target either has worse EV than incumbents (and gets rejected) or is already reachable via random-swap.

**Tier-union is a structural correctness improvement** (pool composition now reflects the actual tier rationale rather than top-50 EV truncation) **that happens to be a no-op on this substrate**. It does not regress, and it remains defensible: a substrate where legacy top-50 EV truncates out a useful affinity-fit teammate is plausible but not present here.

## Phase 3 disposition

Phase 3 (proposal weighting — bias the 70% biased-swap probability toward specific tiers) was queued in the original S17-ι plan. Given Phase 2 findings, **defer Phase 3** until we have evidence on at least one substrate that tier-union actually differentiates from legacy. Until then, Phase 3 would be optimising a no-op.

Suggested unblockers for revisiting Phase 3:
- Capture 2–3 additional stage substrates with diverse slider configurations and re-run Test (i)/(ii)/(iii). If tier-union ever differentiates with a positive Δ, that becomes the substrate for Phase 3 weighting work.
- Alternatively: accept tier-union as a structural-only change and move on to S17-6 (TT bucket — hard deadline 2026-05-17).
