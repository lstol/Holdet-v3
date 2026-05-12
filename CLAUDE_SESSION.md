# CLAUDE_SESSION.md — Holdet v3 conversational Claude onboarding

Entry point for any new conversational Claude session in this project. Pair with `ROADMAP.md` (current project state) and `CLAUDE_CODE.md` (executor instructions).

**On every new session, before responding to user content:**

1. Fetch current `ROADMAP.md` from `https://github.com/lstol/Holdet-v3/blob/main/ROADMAP.md` (works via web_fetch from the public blob URL — see Operational notes below)
   - Re-fetch ROADMAP.md after every Claude Code return — Part 0 deltas may have mutated state since the last fetch. The roadmap state in conversational Claude's context is stale otherwise.
2. Read this file
3. Engage with the user's session-specific framing

---

## Project context

Holdet v3 is decision-support for elite-level Holdet.dk fantasy cycling. **Race target**: Tour de France 2026 (early July). **Currently calibrating against**: Giro d'Italia 2026 (in progress). Each Giro divergence between human judgment and optimizer is a labeled training example. Scoring is convex (stage wins dominate, captain multiplies right-tail outcomes, depth bonus non-linear).

- Repo: `https://github.com/lstol/Holdet-v3` (public)
- Local path: `~/Claude/Holdet-v3/` (capital C, H, V)

---

## Roles in this workflow

**Conversational Claude (you).** Reads context, drafts handoffs, captures decisions with user, audits diagnostic findings, holds long-form architectural reasoning. Does not edit code directly; produces handoffs for Claude Code.

**Claude Code.** Executes handoffs. Runs diagnostics, makes code changes, runs tests, commits, pushes. Returns reports to the user, who pastes them back into the conversational session.

**User.** Names goals, ships handoffs to Claude Code (copy-paste), makes decisions on direction, verifies in real dashboard use, captures real-world signal (race outcomes, dashboard observations, expert reads).

---

## Standard handoff structure

Every substantive Claude Code handoff has two parts:

**Part 0 — ROADMAP.md update.** Every handoff includes a Part 0 roadmap delta — closures, new items, scope shifts, corrections. If genuinely no deltas exist, Part 0 explicitly states "no roadmap deltas this handoff" rather than being omitted.

**Part 1 — The substantive work.** One issue per handoff (3-4 fixes maximum, never more). Read-only diagnosis before any mutation. Stop conditions clearly listed. Verification cases specified.

Handoffs must stand alone — Claude Code only has the handoff text, not the conversational thread or prior handoffs. Pack everything needed for execution inside the handoff.

Diagnostic handoffs (read-only) may include sketched diffs in the report — this is encouraged, not separate handoff scope.

Commits are typically split: Part 0 alone (roadmap), then Part 1 alone (the work). Separate commits keep diffs readable.

---

## Operational rules (non-negotiable)

- **Main only.** No worktrees, no feature branches. Session 5's worktree disaster cost multiple sessions to untangle.
- **Read-only diagnosis before mutation.** When state is unexpected, stop and report instead of mutating.
- **One issue per handoff.** Never batch more than 3-4 fixes. Session 5's 11-part monster broke things for two sessions.
- **Server restart clusters at end of handoff.** `pkill -f server.py && sleep 1 && launchctl kickstart -k gui/$(id -u)/com.holdet.server`. Cluster pkill + launchctl together so dashboard downtime is seconds.
- **Stop and report on scope creep.** Don't spiral mid-handoff. A staged approach beats a sprawling one.
- **Field names from real JSON before assuming.** Past handoffs failed when names were guessed.
- **When local main has uncommitted changes**, plan `merge --no-ff`, not `--ff-only`.

---

## Reasoning patterns (decisions made together establish these)

- **Optimization is search for the highest local maximum, not statistical estimation.** Multi-start beats multi-seed averaging. Selection rule shipped in S17-22: EV-best basin with corroboration count ≥ 2 (`ev_best_corroborated`), not EV-best raw chain (`ev_best_seen`) — filters singleton spikes that may be thin-basin one-off chain artifacts rather than robust optima. Both are surfaced for diagnostic visibility; they're typically equal, and divergence flags a singleton.
- **Seed-state-leak shape.** When search-equivalent inputs produce different outputs (a UI toggle that's correctly gated to no-op still shifts the roster; bit-identical probability dicts yield different rosters), check whether those inputs enter a state hash (RNG seed, cache key) downstream of the actual computation. The set of inputs entering the hash must equal the set affecting the function's output; if the hash over-reads, different seeds pick different local optima across nominally-identical inputs. **Origin:** S17-2 — `compute_seed` hashed n1 sliders even when `use_race_type_adjustment=False` made them inert in `build_probabilities`; Tier A fix at [optimizer.py:67-69](claude/engine/optimizer.py:67) conditionally drops inert inputs from the payload. Distinct shape from the latent-invariant pattern (new input paths violating existing assumptions); seed-state-leak is hashes over-reading existing inputs.
- **Calibrate before committing to direction.** When the right value of a tunable (N, threshold, etc.) is unknown, run a small experiment first. The experiment is cheap; baking the wrong default into production code is expensive.
- **Single-stage findings don't generalize.** A diagnostic on one stage with one slider configuration characterizes that point, not optimizer/system behavior across the input space. Phase 1.5's "lookahead Pattern B" finding (Stage 3, neutral sliders) was treated as a property of the strategy; S17-22-followup Phase 1 on Stage 2 across three configs falsified that generalization. Future diagnostics characterizing optimizer behavior should vary inputs deliberately before concluding.
- **Watch for latent invariants exposed by new input paths.** Instances this session: S17-24 (all-zero odds invariant exposed by ✕ buttons), S17-27 (alphabetically-last-snapshot-has-rider-data invariant exposed by per-stage team save), S17-29 (zero-means-missing invariant exposed when top10 odds genuinely unavailable for sprint stages), S17-30 (`AbortController` timeout invariant exposed by structural SA runtime floor), S17-31 (zero-means-missing invariant's second half — don't impute missing data from win — exposed by the same Stage 4 conditions that caught S17-29). Plus S17-25 as a variant shape: "diagnosis correct, implementation deferred until external dependency resolves" (Session 15 D₂ correctly diagnosed the gap; implementation waited for endpoint discovery via user DevTools capture, ultimately landing in Phase 2). Before shipping any feature that creates a new state-writing path, explicitly enumerate the readers of that state and the invariants they assume. **After landing an invariant-defending fix, audit whether ALL code paths that touch the invariant respect it, not just the one the symptom surfaced through** (e.g., S17-29 enforced the input guard; S17-31 enforced the no-imputation-at-fallback rule, the invariant's second half).
- **Pragmatism over architectural purity for in-flight work.** Land tactical fixes that ship; file architectural cleanup as separate roadmap items rather than blocking the tactical fix on the cleanup.
- **Acknowledge mistakes plainly.** When user pushback lands (e.g. "averaging is the wrong frame, this is optimization not estimation"), take the hit, re-derive, name the corrected framing explicitly.
- **Diagnostic-then-fix.** Larger fixes split into a read-only diagnostic handoff first, then a fix handoff after we understand the shape. Especially for ambiguous symptoms.

---

## Operational notes

- **GitHub fetch.** `web_fetch` requires URLs the user provided or that surfaced in prior search/fetch results. The repo URL `https://github.com/lstol/Holdet-v3` is in this file (and any prior context); from there, blob URLs like `https://github.com/lstol/Holdet-v3/blob/main/ROADMAP.md` work. The `raw.githubusercontent.com/...` direct URLs do *not* — they're treated as a different domain with no provenance.
- **Roadmap is authoritative.** When in doubt about scope, status of an item, or what's queued, fetch ROADMAP.md and trust it over conversational memory.
- **Memory system.** Two project-scoped rules currently persisted across sessions: (1) diagnostic handoffs may include sketched diffs in the report; (2) every handoff includes a Part 0 ROADMAP.md delta. Adding more rules is fine but should be deliberate.
- **Report-back format from Claude Code.** Claude Code returns reports in a standardized structure (commits table, verifications table, implementation summary, findings worth surfacing, decisions deferred to user). See `CLAUDE_CODE.md` for the template. When reading a returned report, expect this structure.
- **Decision durability.** Non-trivial decisions made in conversation should land somewhere durable — either as a ROADMAP delta (Sub-B carving evolution style — preserves the "why" alongside the "what") or in `claude/decisions/decisions_log.md`. Memory rules persist across sessions but are bounded (max 30 entries); files don't drift.
- **Harness worktree placement is acceptable.** The Claude Code harness may place sessions in `.claude/worktrees/<auto-name>/` rather than the canonical `~/Claude/Holdet-v3`. This is fine as long as commits fast-forward-push to `origin/main` (no merge commit, no divergence). The "every change goes directly to main" rule is about destination, not workspace.
- **Optimal ≡ depth on flat sprint stages — expected, not bug.** Depth's non-linear top-15 bonus only differentiates from optimal when basin-EV differs in expected top-15 rider count. On stages where all 8 lineup riders have similar top-15 finishing probability (e.g., sprint stages with cleared top10 odds), depth's bonus contribution is uniform across basins, so depth's objective reduces to optimal's. Both strategies converge to the same team. Mountain stages, GC reshuffles, and stages with widely-spread finishing probabilities will separate them. **Origin:** S17-26 verification noted this on Stage 4; worth surfacing to pre-empt the "why does depth show same team as optimal" question. Not a defect to fix.
- **S17-22-followup Phase 2B verification depends on S17-15/16.** Phase 2A's EV-inversion pathology was diagnosed against slider-only forward EV. Whether it persists when forward EV is informed by Axelgaard per-rider ratings is an empirical question that requires S17-15/16 to land first. Phase 2B's first step (re-run basin-landscape diagnostic on B_sprint × lookahead) tests this. If post-S17-16 forward EV resolves the pathology without touching `LOOKAHEAD_TC_WEIGHT`, Phase 2B closes with no code change. If pathology persists, sweep `{1.0, 0.8, 0.6, 0.4}` (range centered higher than pre-S17-16 prior, reflecting improved proxy).
- **Python `requests` + missing `charset=` header → Latin-1 garbage.** Per RFC 7230, `requests` defaults to Latin-1 for text responses without explicit `charset=` in `Content-Type`. Holdet's CDN omits the charset on `text/x-component` responses; same may apply to other endpoints serving Danish-language content. Set `resp.encoding = 'utf-8'` before reading `.text` for any Holdet/Feltet/TV2/Danish-content endpoint. Danish characters (`ø æ å`) garble silently, breaking string matching downstream. **Origin:** S17-25 Phase 2 surfaced this — first smoke run showed "4 unmapped actions" before tracking it down to encoding.
- **Dashboard renderer is semi-hardcoded, not fully field-driven.** S17-28 diagnostic claimed `renderStageResults` in `claude.html` is field-driven so new fields surface automatically. S17-25 Phase 2 surfaced this was wrong — column rendering uses hardcoded `<td>${fmt(r.stage_pts)}</td>` per known field. New fields require explicit column additions to header + row template. Renderer change scope for new fields: small (per-column addition) but non-zero. **Verify by reading the actual template before any handoff that adds a results-schema field.**
- **Intel pipeline — numerical lever vs prompt nudge.** The only per-rider numerical multiplier on probabilities is `INTEL_MULT` at [optimizer.py:105-112](claude/engine/optimizer.py:105) — a 6-cell `(direction, strength)` table, consumed by `build_probabilities` (current stage, line 337). **Forward stages do not consume `INTEL_MULT`** — `build_forward_probabilities` was briefly extended to do so in S17-16 but reverted in S17-γ on architectural grounds (see "Per-rider intel consumption requires a bookmaker distribution" below). Everything else in the intel pipeline is prompt-engineering surface: `expert_sources.yaml` weights are f-string-substituted into the Haiku prompt at `server.py`; the dashboard expert-source sliders feed the same path (Sub-B-plumbing verification pending). Changing a YAML weight or moving a slider changes **no number in the optimizer** — only Haiku's prose judgment. Stage-level intel fields (`summary`, `stage_notes`, `weather`) are rendered in the dashboard but currently unconsumed by the optimizer (S17-19, queued for either wiring or removal). **Implication for tuning conversations:** INTEL_MULT is the numerical knob with observable effects (current stage only); YAML/slider tuning is opaque prompt nudge. **Origin:** S17-1 Sub-B Design Diagnostic; S17-γ revert refined forward-path scope.
- **Per-rider intel consumption requires a bookmaker distribution to re-rank.** `INTEL_MULT` is architecturally a re-ranking operation: multiply per-rider probabilities, renormalise to preserve total mass. The renormalisation invariant only holds when a bookmaker distribution exists as ground truth (current stage's `win` / `top3` / `top10` from Oddschecker/Unibet pastes). Forward stages have no bookmaker distribution — `build_forward_probabilities` constructs synthetic probabilities from `terrain_affinity × slider weights`. Multiplying a synthetic distribution by per-rider intel ratings is not the same operation; the renormalisation invariant doesn't generalise. **Operational corollary:** forward intel (`forward_n1_intel` / `forward_n2_intel` from S17-15; source-tagged per S17-β) is **UI substrate only** — surfaces in dashboard rectangles for user's slider-setting reads, doesn't feed the optimizer. Stage classification (`"Flad etape"` / `"Bjergetape"`) is the load-bearing signal; per-rider star ratings from forward intel are not consumed downstream. **Origin:** S17-γ revert of S17-16. The principle generalises: any future intel-consumption design must explicitly identify the underlying distribution being re-ranked and whether that distribution carries the renormalisation invariant.
- **V4a — same-handoff regression check (not cross-handoff anchor).** Capture optimizer output for a target stage **before** any code change in the current handoff session, apply the change, re-run with the same inputs, verify bit-identical match. Cross-handoff numerical comparisons are fragile because intel JSONs, odds, standings, and holdet snapshots can be modified between handoffs via legitimate dashboard activity — the documented S17-26 / S17-15 / S17-16 numerical baselines (`1,754,129` / `1,740,525` etc.) drifted quickly across S17-15/α/β/γ verifications. Same-handoff pre/post is the reliable shape: pre-deploy snapshot → apply change → post-deploy snapshot → diff. If the change is read-only or doesn't touch optimizer code, V4a is satisfied by construction (note the absence of optimizer-path edits in the commit body). **Origin:** S17-16 verification originated V4a as an absolute-number check; cross-handoff drift across S17-15/α/β surfaced the fragility; S17-γ reformulated.
- **V4b synthetic-intel injection — diagnostic template for intel-consumer verification.** Hand-craft a structured intel dict and inject it through the optimizer pipeline — write the synthetic intel to `stage_N_intel.json`, or invoke the consumer function directly from a test harness — **without running server / scraper / Haiku**. Gives deterministic, fast verification of consumption logic (multiplier lookup, renormalisation invariant, EV shifts) in seconds rather than minutes. Pattern generalises to any structured-data consumer where the producer is expensive or non-deterministic to invoke. **Current applicability post-S17-γ:** consumer is `build_probabilities` (current stage); the future tier-multiplier consumer in S17-INTEL Phase 3 is the next intended target for this pattern. Forward path no longer has an intel consumer to test (S17-γ revert). **Origin:** S17-16 V4b proved `INTEL_MULT` lookup + total-mass-preservation invariant + forward-prob shifts matching multiplier table.
- **Coupled handoffs may decouple when one half has verifiable scope and the other depends on external dependencies.** S17-15/16 was coupled but split during execution: S17-16's consumer was verifiable in-session via synthetic intel injection (V4a slider-only + V4b synthetic); S17-15's orchestration required live TV2 Playwright login + Haiku round-trips, which couldn't be reliably verified without an interactive `/gather-intel` call. Decoupling pattern: ship the verifiable half (S17-16 ✅), defer the half awaiting external dependency (S17-15 🟡), document the unblock condition explicitly in ROADMAP. Verify-before-claim is the principle — half a coupled handoff shipped with full verification is preferable to a fully-coupled handoff shipped on synthetic-only.
- **Dashboard information-coupling principle (S17-δ).** Controls live next to the data they modify, not grouped by control-type. Stage N slider sits with current-stage odds + intel; Stage n+1 / n+2 sliders sit with their forward rectangles; expert-weight sliders sit with the expert intel table; force-in / force-out toggles sit per-rider in the rider table. The principle generalises: when adding a new control, its placement is determined by which data it modifies, not by what kind of control it is. Two reasons: visual proximity makes the modify-relationship legible at a glance; reduces context-switching when adjusting a control to read its downstream effect. **Origin:** S17-δ Panel 1 + Panel 2 redesign, which deleted the unified "Stage type sliders" panel and distributed its contents across the data-coupled panels.
- **Intel source strategy is role-dependent (S17-β, in flight from 2026-05-12).** Current stage and forward stages use different scraping strategies. Current stage prefers Axelgaard's detailed analysis (richer per-rider signal, Playwright + login); falls back to TV2 generic preview when Axelgaard returns the not-found sentinel. Forward stages (n+1, n+2) use the generic preview only — context-shaping signal for lookahead's basin choice doesn't justify Playwright + login cost. Both sources feed the same Haiku extraction pipeline producing the same `key_signals` shape; the `source` field in each `stage_N_intel.json` intel block distinguishes which source produced that block's prose for downstream transparency (`"axelgaard" | "generic_preview" | "both_failed"`). **TV2 generic preview URL is stable:** `https://sport.tv2.dk/cykling/2026-04-14-{N}-etape-eller-giro-ditalia-2026` — the `2026-04-14` creation-date prefix is shared across all 21 Giro stage shells (TV2 created the article shells in advance at race setup). When Axelgaard has published his detailed article for a stage, the generic URL 301-redirects to the detailed one; following the redirect yields the richer prose for free, and the scraper inspects the final URL to set the `source` field accordingly.
- **Intel-table architectural arc (S17-INTEL, in flight from 2026-05-12).** Pipeline migrates from Haiku-synthesized `key_signals` (per-rider direction + strength tuples) to per-source star matrix (per-rider 1–5 star ratings per source, weighted-averaged). Source weights transition from prompt-string nudges (current state per intel-pipeline note above) to **real numerical multipliers**. Staged across 4 phases: schema extraction (Phase 1, no UI / no optimizer change), dashboard star matrix + per-source sliders + tickboxes + live bumps (Phase 2, redoes S17-α's forward rectangles), parallel-path-gated optimizer consumption migration **current-stage only** (Phase 3, post-S17-γ scope refinement — forward path stays slider-driven permanently per the per-rider intel consumption principle above), source registry expansion absorbing S18-7 (Phase 4, Inner Ring repair + new sources). Three-tier multiplier table (proposed: 1.10× / 1.20× / 1.30× at 2–3 / 3–4 / 4–5 average stars) replaces the 6-cell `INTEL_MULT` for current stage. **Epistemic shape — "missing stars ≠ zero":** riders not rated by any source get 1.0× multiplier (no signal → no lift), not a penalty. Same shape as S17-29 odds invariant (zero ≡ missing); avoid imputing absence as a downvote. **Dependency knock-on:** S17-22-followup Phase 2B verification + conditional sweep waits for Phase 3 to land — the current-stage calibration substrate changes again under the migration. Forward-stage calibration substrate is now stable (slider-only permanent after S17-γ), so Phase 2B's forward-path component is no longer affected by Phase 3.
- **Part 0 timing rule.** ROADMAP delivered notes describe shipped work, not predicted work. When a handoff has Part 1 verification gates (V4/V5/V7/V8/etc.), Part 0 must either:
  - **(a) Defer commit until Part 1 verification passes.** Part 0 + Part 1 commit together at the end. Right when Part 0's text contains outcome claims like "Verified Stage 3 Magnier sums to 435k" or "Bit-identical reproducibility confirmed."
  - **(b) Describe only structurally-certain work.** Item-opening status changes, schema additions, declared invariants, queued sub-items. No outcome claims.

  Pattern that breaks this rule (and shipped a false ROADMAP claim on 2026-05-12 in S17-25 Phase 2 attempt): handoff draft writes "Phase 2 closed" with verified-result claims in Part 0, instructs "Commit Part 0 alone," but Part 1's verification hasn't yet run. Claude Code follows the instruction faithfully; ROADMAP becomes false. **Lesson:** when drafting Part 0, ask "is everything in this delivered note structurally certain at this point in execution?" If no → either defer Part 0 commit, or rewrite Part 0 to only describe what's certain.
- **Odds invariant — zero means missing.** Across the codebase, treat `win_pct == 0`, `top3_pct == 0`, `top10_pct == 0` (and any future bucket) as missing data, not as zero probability. Odds are never zero by intent; the source of zero is either the ✕ clear button, a parse failure, or a never-gathered bucket. Code paths must either: (a) fall through to a derived fallback (e.g., `build_probabilities` derives top10 from win when top10 is missing), or (b) exclude the row from the affected calculation entirely. Never propagate zero as a literal probability. Specifically: guards like `if value is not None` are insufficient; they leak `0` into downstream calculations. Use `if (value or 0) > 0` instead. Origin: S17-29 diagnostic surfaced that `optimizer.py:306-309` violated this invariant, causing SA gradient collapse on positions 4-15 when top10 was cleared. The invariant is now project-wide; future code touching odds consumers must respect it.

  **Extrapolation principle for missing odds.** When a rider's odds for a position bucket are missing (per the zero-means-missing invariant), the probability model extrapolates from the nearest-in-nature observed bucket, not from win alone. Top10 from top3 (close in nature) preferred over top10 from win (further removed). Win-only fallback only when no closer signal exists. Calibration constants for the extrapolation ratios are documented in `optimizer.py` and recalibrated periodically from empirical stage data (S17-32). This preserves comparability across riders with different data completeness — a rider with sparse odds isn't artificially penalized in EV, but the extrapolation is disclosed and bounded rather than fabricated.
- **Dashboard verification protocol (post-deploy, for any change touching optimizer / odds / results panels):**
  1. **Page load.** Open dashboard with browser console open. No console errors during initial render.
  2. **Odds round-trip.** Paste win / top3 / top10 → `parse-ok` status → all three columns populated → optimizer button enabled.
  3. **Clear round-trip.** Click ✕ on one bucket → column shows `—` (not "0") → disk shows that bucket = 0 → other buckets preserved on disk.
  4. **Optimizer round-trip on a good state.** "Run optimizer" on a stage with non-empty odds → all expected strategy cards render with EV breakdowns → no fetch errors → no console errors.
  5. **Optimizer pre-flight on cleared state.** "Run optimizer" on a stage where every win-odds row was cleared → immediate error message (no 120s timeout) → user can recover by re-pasting odds.
  6. **"How it unfolded".** Target a completed stage → breakdown renders all columns; `—` only where the underlying data field is genuinely 0/missing.
  7. **Optimizer output sanity check** (post-deploy, for any change touching `build_probabilities`, `simulate_stage`, `compute_objective`, or odds consumers). After V4 (full optimizer round-trip), inspect the strategy output JSON. For each strategy, verify:
     - `ev_estimate` falls within plausible bounds (typically 800k–2M for current Giro stage profile; adjust band as race-day calibration accumulates).
     - `ev_net = ev_estimate − transfer_cost` is within similar bounds.
     - Captain assignment is non-empty and consistent with the strategy's optimization target.
     - No strategy returns NaN/Infinity in any EV field.

     Surface-level UX checks (V1–V6) do not exercise the optimizer's internal math. A regression in `build_probabilities`'s normalization, `simulate_stage`'s MC, or `compute_objective`'s weighting will surface here when EVs collapse or balloon in an order-of-magnitude way. **Origin:** S17-29 — `is not None` vs `> 0` guard on top3/top10 silently zeroed positions 4–15 contribution; pre-fix EVs were under-counted ~30–50% and V1–V6 wouldn't have caught it. **Expected-bounds calibration:** keep the 800k–2M band loose for now; tighten as Giro stages 5–21 accumulate. If a stage returns EVs outside the band, that's a "look at this" signal, not a hard failure — race profile may legitimately differ (TT stages, mountain stages with smaller field).
  8. **Stage results breakdown sanity check** (post-deploy, for any change touching `fetch_stage_results` or the rider-breakdown ingestion path). For each rider in `stage_N_results.json`, the sum of per-bonus fields plus `stage_pts` should equal the rider's aggregate `priceChange` reported by the round-history endpoint. Specifically:

     ```
     sprint_pts + jersey_bonus + gc_bonus + team_bonus + stage_placement + penalty == priceChange
     ```

     The captain bonus is tracked separately (`captain_bonus`) and added to `total` independently. If the equality fails for any rider, the field-mapping table has a missing or mis-routed Danish action label. **Origin:** S17-25 Phase 2 — surfacing a future regression where Holdet adds a new action category (e.g., a new jersey type or scoring rule mid-season) would cause silent under-counting if the mapping table doesn't account for it. V8 makes mapping completeness measurable.
  Page-load-only verification (the V1 pattern that missed S17-20's bug surface) does not exercise these paths. End-to-end round-trip is the standard for any change touching these areas.

---

## Files in this project to know about

| File | Purpose | When to read |
|------|---------|--------------|
| `ROADMAP.md` | Living project state, completed work + future items | Every session start |
| `CLAUDE_CODE.md` | Claude Code's standing instructions | When drafting handoffs that touch unusual areas |
| `CLAUDE_SESSION.md` | This file | Every session start |
| `claude/sessions/*.md` | Session logs | When user references a past session decision |
| `claude/decisions/decisions_log.md` | Decision history | When historical reasoning matters |

---

## What this file is NOT

- Not a substitute for `ROADMAP.md`. The roadmap has current state; this file has the working model.
- Not a code style guide. Project-level coding conventions live in code review, not here.
- Not exhaustive. Patterns emerge during conversations. If a new durable rule appears (memory rule, operational rule, reasoning pattern that we'd want any future session to inherit), propose adding it here as part of a Part 0 delta.

---

## What a session typically opens with

User opens with one of:

- A returned report from Claude Code on a prior handoff (paste-back)
- A finding from the world (race outcome, dashboard observation, expert read, news)
- A new architectural question or scoping conversation
- A direct task ("draft the X handoff")

Conversational Claude's first move: fetch ROADMAP.md to ground in current state, then engage. Don't ask the user to re-explain context that's already in the roadmap or this file.
